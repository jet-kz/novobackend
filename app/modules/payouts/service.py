"""
Payout flow (Bachs Connect, "separate transfers"):

1. A merchant or rider adds their bank details once -> we create a Bachs connected account
   (recipient) for them and attach the bank as its payout destination. Bachs may ask for ID
   verification, done on Bachs' hosted onboarding page.
2. Novo collects every customer payment on its own Bachs account.
3. What each payee has earned is computed from delivered orders (see earnings()).
4. An admin settles: POST /v1/transfers moves the amount from Novo's available balance to the
   payee's connected account.
5. The payee withdraws: POST /v1/payouts (as their account) sends it to their bank.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import config
from app.modules.payments.bachs_service import (
    BachsError, available_amount, bachs_request, capability_status, money, requirements_due,
)
from app.modules.payouts.models import PayoutAccount, Settlement, Withdrawal

logger = logging.getLogger("novo.payouts")

DEFAULT_COMMISSION = 0.10  # used only for orders that predate pricing snapshots

# Fallback when Bachs' bank list can't be fetched. CBN bank codes.
NIGERIAN_BANKS = [
    ("044", "Access Bank"), ("023", "Citibank"), ("050", "Ecobank"), ("070", "Fidelity Bank"),
    ("011", "First Bank"), ("214", "FCMB"), ("058", "GTBank"), ("030", "Heritage Bank"),
    ("301", "Jaiz Bank"), ("082", "Keystone Bank"), ("076", "Polaris Bank"), ("101", "Providus Bank"),
    ("221", "Stanbic IBTC"), ("068", "Standard Chartered"), ("232", "Sterling Bank"), ("100", "Suntrust Bank"),
    ("032", "Union Bank"), ("033", "UBA"), ("215", "Unity Bank"), ("035", "Wema Bank"), ("057", "Zenith Bank"),
]


def _http(exc: BachsError) -> HTTPException:
    code = exc.status_code if 400 <= exc.status_code < 500 else status.HTTP_502_BAD_GATEWAY
    return HTTPException(status_code=code, detail=f"Bachs: {exc.message}")


class PayoutService:
    # ── Identity ─────────────────────────────────────────────────────────────

    @staticmethod
    async def payee_for_user(db: AsyncSession, user: dict) -> tuple[str, str, str]:
        """(payee_type, payee_id, display_name) for the signed-in merchant owner or rider."""
        from app.core.access import get_owned_merchant

        roles = user.get("roles") or []
        if "merchant_owner" in roles:
            merchant = await get_owned_merchant(db, user["user_id"])
            if merchant:
                return "merchant", str(merchant.id), merchant.name
        if "rider" in roles:
            return "rider", user["user_id"], user.get("email") or "Rider"
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only merchants and riders have payouts")

    @staticmethod
    async def account_for(db: AsyncSession, payee_type: str, payee_id: str) -> Optional[PayoutAccount]:
        res = await db.execute(
            select(PayoutAccount).where(PayoutAccount.owner_type == payee_type, PayoutAccount.owner_id == payee_id)
        )
        return res.scalar_one_or_none()

    # ── Earnings ─────────────────────────────────────────────────────────────

    @staticmethod
    async def earnings(db: AsyncSession, payee_type: str, payee_id: str) -> dict:
        """
        earned: from delivered orders (card orders only once paid).
        cash_collected (riders): cash/transfer-on-delivery money the rider took from customers,
        which belongs to Novo and is netted off what we owe them.
        settled: already sent to their connected account.
        owed = earned - cash_collected - settled (negative means they owe Novo).
        """
        from app.modules.deliveries.models import Delivery
        from app.modules.orders.models import Order
        from app.modules.pricing.models import PricingSnapshot
        from app.modules.stores.models import Store

        paid_or_cod = (Order.payment_method != "card") | (Order.payment_status == "paid")
        earned = cash = 0.0
        orders = 0
        if payee_type == "merchant":
            rows = (await db.execute(
                select(Order.subtotal, PricingSnapshot.restaurant_net_earning)
                .join(Store, Store.id == Order.store_id)
                .outerjoin(PricingSnapshot, PricingSnapshot.order_id == Order.id)
                .where(Store.merchant_id == uuid.UUID(payee_id), Order.status == "DELIVERED", paid_or_cod)
            )).all()
            orders = len(rows)
            earned = sum(float(net if net is not None else (sub or 0) * (1 - DEFAULT_COMMISSION)) for sub, net in rows)
        else:
            rows = (await db.execute(
                select(Delivery.rider_earnings, Order.payment_method, Order.total)
                .join(Order, Order.id == Delivery.order_id)
                .where(Delivery.rider_id == payee_id, Delivery.status == "delivered", paid_or_cod)
            )).all()
            orders = len(rows)
            earned = sum(float(e or 0) for e, _, _ in rows)
            cash = sum(float(t or 0) for _, method, t in rows if method in ("cash", "transfer"))

        settled = (await db.execute(
            select(func.coalesce(func.sum(Settlement.amount), 0)).where(
                Settlement.payee_type == payee_type, Settlement.payee_id == payee_id,
                Settlement.status.in_(("processing", "paid")),
            )
        )).scalar() or 0
        owed = round(earned - cash - float(settled), 2)
        return {
            "orders": orders,
            "earned": round(earned, 2),
            "cash_collected": round(cash, 2),
            "settled": round(float(settled), 2),
            "owed": owed,
        }

    # ── Connected account ────────────────────────────────────────────────────

    @staticmethod
    async def refresh_account(db: AsyncSession, account: PayoutAccount) -> PayoutAccount:
        """Pull capability/requirements status from Bachs."""
        if not account.bachs_account_id:
            return account
        try:
            data = await bachs_request("GET", f"/v1/accounts/{account.bachs_account_id}")
        except BachsError as exc:
            logger.warning("Couldn't refresh %s: %s", account.bachs_account_id, exc.message)
            return account
        account.requirements_due = requirements_due(data)
        # Sandbox reports capabilities active before details are in, so outstanding requirements also block.
        account.transfers_enabled = capability_status(data, "transfers") == "active" and not account.requirements_due
        account.payouts_enabled = capability_status(data, "payouts") == "active" and not account.requirements_due
        if account.transfers_enabled and account.payouts_enabled:
            account.status = "active"
        elif account.requirements_due:
            account.status = "incomplete"
        elif "rejected" in (capability_status(data, "payouts"), capability_status(data, "transfers")):
            account.status = "restricted"
        else:
            account.status = "in_review"
        await db.commit()
        return account

    @staticmethod
    async def setup_account(db: AsyncSession, user: dict, data: dict) -> PayoutAccount:
        payee_type, payee_id, display_name = await PayoutService.payee_for_user(db, user)
        bank_code = str(data.get("bank_code") or "").strip()
        account_number = "".join(ch for ch in str(data.get("account_number") or "") if ch.isdigit())
        account_name = str(data.get("account_name") or "").strip()
        first = str(data.get("first_name") or "").strip()
        last = str(data.get("last_name") or "").strip()
        if not bank_code or len(account_number) != 10:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Choose your bank and enter your 10-digit account number")
        if len(account_name) < 3 or not first or not last:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Enter the account name and your first and last name")

        account = await PayoutService.account_for(db, payee_type, payee_id)
        if not account:
            account = PayoutAccount(owner_type=payee_type, owner_id=payee_id, user_id=user["user_id"], status="incomplete")
            db.add(account)
            await db.flush()

        try:
            if not account.bachs_account_id:
                created = await bachs_request("POST", "/v1/accounts", json={
                    "contact_email": user.get("email"),
                    "display_name": display_name[:100],
                    "country": "NG",
                    "entity_type": "company" if data.get("entity_type") == "company" else "individual",
                    "configuration": {"recipient": {}},
                    "metadata": {"novo_payee_type": payee_type, "novo_payee_id": payee_id},
                }, idempotency_key=f"novo-acct-{account.id}")
                account.bachs_account_id = created.get("id")
                await db.commit()
            await bachs_request("POST", f"/v1/accounts/{account.bachs_account_id}", json={
                "fields": {
                    "persons": [{"first_name": first, "last_name": last, "relationship": {"representative": True}}],
                    "payout_destination": {
                        "currency": "NGN",
                        "type": "bank_account",
                        "account_number": account_number,
                        "account_name": account_name,
                        "bank_code": bank_code,
                    },
                }
            })
        except BachsError as exc:
            await db.commit()
            raise _http(exc)

        account.bank_code = bank_code
        account.bank_name = str(data.get("bank_name") or dict(NIGERIAN_BANKS).get(bank_code) or "")[:100]
        account.account_last4 = account_number[-4:]
        account.account_name = account_name[:150]
        account.destination_id = None  # looked up again at withdrawal time
        await db.commit()
        return await PayoutService.refresh_account(db, account)

    @staticmethod
    async def onboarding_link(db: AsyncSession, user: dict) -> str:
        payee_type, payee_id, _ = await PayoutService.payee_for_user(db, user)
        account = await PayoutService.account_for(db, payee_type, payee_id)
        if not account or not account.bachs_account_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Add your bank details first")
        back = f"{config.FRONTEND_URL}{'/merchant/earnings' if payee_type == 'merchant' else '/rider/earnings'}"
        try:
            link = await bachs_request("POST", f"/v1/accounts/{account.bachs_account_id}/account-links", json={
                "type": "onboarding" if account.status != "active" else "update",
                "return_url": f"{back}?verification=done",
                "refresh_url": f"{back}?verification=expired",
            })
        except BachsError as exc:
            raise _http(exc)
        url = link.get("url") or link.get("link") or link.get("account_link_url")
        if not url:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Bachs didn't return a verification link")
        return url

    @staticmethod
    async def connected_balance(account: PayoutAccount) -> Optional[float]:
        if not account.bachs_account_id:
            return None
        try:
            return available_amount(await bachs_request("GET", "/v1/balances", account_id=account.bachs_account_id))
        except BachsError:
            return None

    # ── Settle (admin) ───────────────────────────────────────────────────────

    @staticmethod
    async def settle(db: AsyncSession, payee_type: str, payee_id: str, amount: float, note: Optional[str], admin_id: str) -> Settlement:
        from app.modules.notifications import service as notify

        if payee_type not in ("merchant", "rider"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="payee_type must be merchant or rider")
        amount = round(float(amount or 0), 2)
        if amount <= 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Enter an amount greater than zero")
        account = await PayoutService.account_for(db, payee_type, payee_id)
        if not account or not account.bachs_account_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This payee hasn't added their bank details yet")
        account = await PayoutService.refresh_account(db, account)
        if not account.transfers_enabled:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Bachs hasn't finished verifying this payee yet")
        owed = (await PayoutService.earnings(db, payee_type, payee_id))["owed"]
        if amount > owed + 0.01:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"That's more than they're owed (₦{owed:,.2f})")

        settlement = Settlement(
            payee_type=payee_type, payee_id=payee_id, amount=amount, currency="NGN",
            status="processing", note=(note or "")[:255] or None, created_by=admin_id,
        )
        db.add(settlement)
        await db.commit()  # reserve it before calling Bachs so a double click can't overpay
        try:
            transfer = await bachs_request("POST", "/v1/transfers", json={
                "destination": account.bachs_account_id,
                "amount": money(amount),
                "currency": "NGN",
                "transfer_group": f"novo-settlement-{settlement.id}",
                "description": f"Novo settlement {str(settlement.id)[:8]}",
            }, idempotency_key=f"novo-settlement-{settlement.id}")
        except BachsError as exc:
            settlement.status = "failed"
            settlement.failure_reason = exc.message[:500]
            await db.commit()
            if exc.code == "INSUFFICIENT_BALANCE":
                raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                    detail="Novo's available Bachs balance is too low for this settlement. Wait for recent payments to settle.")
            raise _http(exc)

        settlement.bachs_transfer_id = transfer.get("id")
        if str(transfer.get("status") or "").lower() in ("paid", "succeeded", "completed"):
            settlement.status = "paid"
            settlement.settled_at = datetime.now(timezone.utc)
        await db.commit()
        notify.settlement_sent(account.user_id, amount, "/merchant/earnings" if payee_type == "merchant" else "/rider/earnings")
        return settlement

    # ── Withdraw (payee) ─────────────────────────────────────────────────────

    @staticmethod
    async def _destination_id(account: PayoutAccount) -> str:
        if account.destination_id:
            return account.destination_id
        res = await bachs_request("GET", "/v1/payouts/destinations", account_id=account.bachs_account_id)
        items = res if isinstance(res, list) else (res.get("items") or res.get("destinations") or res.get("data") or [])
        usable = [d for d in items if isinstance(d, dict) and d.get("is_usable", True) and str(d.get("currency") or "NGN").upper() == "NGN"]
        if not usable:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Your bank account is still being checked by Bachs. Try again shortly.")
        default = next((d for d in usable if d.get("is_default")), usable[0])
        account.destination_id = default.get("id")
        return account.destination_id

    @staticmethod
    async def withdraw(db: AsyncSession, user: dict, amount: Optional[float]) -> Withdrawal:
        payee_type, payee_id, _ = await PayoutService.payee_for_user(db, user)
        account = await PayoutService.account_for(db, payee_type, payee_id)
        if not account or not account.bachs_account_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Add your bank details first")
        account = await PayoutService.refresh_account(db, account)
        if not account.payouts_enabled:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Finish verification with Bachs before withdrawing")
        available = await PayoutService.connected_balance(account) or 0.0
        amount = round(float(amount or available), 2)
        if amount <= 0 or amount > available + 0.005:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"You can withdraw up to ₦{available:,.2f}")

        try:
            destination = await PayoutService._destination_id(account)
        except BachsError as exc:
            raise _http(exc)
        withdrawal = Withdrawal(payout_account_id=account.id, amount=amount, currency="NGN", status="pending")
        db.add(withdrawal)
        await db.commit()
        try:
            payout = await bachs_request("POST", "/v1/payouts", json={
                "destination": destination,
                "amount": money(amount),
                "reference": f"NOVO-WD-{str(withdrawal.id)[:12]}",
            }, account_id=account.bachs_account_id, idempotency_key=f"novo-withdrawal-{withdrawal.id}")
        except BachsError as exc:
            withdrawal.status = "failed"
            withdrawal.failure_reason = exc.message[:500]
            await db.commit()
            raise _http(exc)
        withdrawal.bachs_payout_id = payout.get("id")
        withdrawal.status = str(payout.get("status") or "processing").lower()
        await db.commit()
        return withdrawal

    # ── Webhooks ─────────────────────────────────────────────────────────────

    @staticmethod
    async def handle_event(db: AsyncSession, kind: str, data: dict, account_id: Optional[str]) -> None:
        from app.modules.notifications import service as notify

        if kind in ("account.updated", "capability.updated"):
            # Connect events carry the account at the top level ("account"); the payload may too.
            data_id = str(data.get("id") or "")
            acct_id = account_id or data.get("account") or data.get("account_id") or (data_id if data_id.startswith("acct_") else None)
            if acct_id:
                res = await db.execute(select(PayoutAccount).where(PayoutAccount.bachs_account_id == acct_id))
                account = res.scalar_one_or_none()
                if account:
                    was_active = account.status == "active"
                    await PayoutService.refresh_account(db, account)
                    if account.status == "active" and not was_active:
                        notify.payout_account_active(account.user_id)
        elif kind == "transfer.created":
            res = await db.execute(select(Settlement).where(Settlement.bachs_transfer_id == data.get("id")))
            settlement = res.scalar_one_or_none()
            if settlement and settlement.status == "processing" and str(data.get("status") or "paid").lower() in ("paid", "succeeded", "completed"):
                settlement.status = "paid"
                settlement.settled_at = datetime.now(timezone.utc)
                await db.commit()
        elif kind in ("payout.paid", "payout.failed"):
            res = await db.execute(select(Withdrawal).where(Withdrawal.bachs_payout_id == data.get("id")))
            withdrawal = res.scalar_one_or_none()
            if not withdrawal:
                return
            withdrawal.status = "completed" if kind == "payout.paid" else "failed"
            if kind == "payout.paid":
                withdrawal.completed_at = datetime.now(timezone.utc)
            else:
                withdrawal.failure_reason = str(data.get("failure_reason") or "")[:500] or None
            await db.commit()
            account = await db.get(PayoutAccount, withdrawal.payout_account_id)
            if account:
                notify.withdrawal_finished(account.user_id, withdrawal.amount, kind == "payout.paid", withdrawal.failure_reason)
