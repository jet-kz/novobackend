"""
Refunds.

Money comes back to the customer through Bachs (POST /v1/refunds) when the payment was a card
charge. Bank-transfer payments can't be refunded by Bachs: the refund fails with Bachs' message and
an admin sends the money from the bank, then records it ("manual" refund).

Rules from Bachs (docs: guides/refunds):
- One refund per charge. A partial refund uses it up; a failed refund doesn't count.
- The money comes out of Novo's Bachs balance; too little balance -> the refund is refused.
- Bachs' processing fee is not returned.

When refunds happen:
- Automatically, in full, when a paid order is cancelled (customer, store or admin), when a payment
  lands on an order that was already cancelled, and when a customer pays the same order twice (the
  extra charge is refunded).
- Failed deliveries are NOT refunded automatically: the food was made and left with a rider, so an
  admin checks what happened and who pays, then refunds from the order screen.
- By an admin, full or partial, from the order screen (missing items, wrong order, overpayment...).
  The admin picks who absorbs it: Novo ('platform'), the merchant or the rider. Merchant and rider
  refunds are taken off what we owe them (see PayoutService.earnings).

Order.payment_status for an order that never got delivered follows the refund:
paid -> refund_pending -> refunded (or back to paid if Bachs refuses, so it shows as needing a refund).
Delivered orders stay 'paid' so the merchant's and rider's earnings still count.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Iterable, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders.models import Order
from app.modules.payments.bachs_service import BachsError, bachs_request, money
from app.modules.payments.models import Payment, PaymentTransaction, Refund

logger = logging.getLogger("novo.refunds")

BEARERS = {"platform", "merchant", "rider"}
REASONS = {
    "customer_cancelled": "Customer cancelled",
    "store_cancelled": "Store cancelled",
    "admin_cancelled": "Cancelled by Novo",
    "delivery_failed": "Delivery failed",
    "late_payment": "Paid after the order was cancelled",
    "duplicate_payment": "Paid twice",
    "overpaid": "Paid more than the order total",
    "underpaid": "Paid less than the order total",
    "missing_items": "Items missing",
    "wrong_items": "Wrong items",
    "quality": "Quality problem",
    "late_delivery": "Very late delivery",
    "other": "Other",
}
ACTIVE = ("processing", "succeeded")  # refunds that use up (or will use up) the charge
# Charge rows that hold customer money: the order's payment, a second payment, a short payment.
MONEY_TXN_STATUSES = ("success", "duplicate", "underpaid")
CLOSED_ORDER_STATUSES = ("CANCELLED", "FAILED")


def _now():
    return datetime.now(timezone.utc)


def _meta(txn: PaymentTransaction) -> dict:
    return txn.provider_metadata if isinstance(txn.provider_metadata, dict) else {}


def bachs_charge_id(txn: PaymentTransaction) -> Optional[str]:
    """The id Bachs refunds by. None when the payment didn't come through Bachs or has no charge id."""
    if txn.provider != "bachs":
        return None
    charge_id = _meta(txn).get("charge_id")
    if charge_id:
        return str(charge_id)
    ref = txn.provider_reference or ""
    return ref[len("bachs:"):] if ref.startswith("bachs:ch_") else None


def _bachs_status(value) -> str:
    s = str(value or "").lower()
    if s in ("success", "succeeded", "paid", "completed"):
        return "succeeded"
    if s in ("failed", "rejected", "cancelled", "canceled"):
        return "failed"
    return "processing"


def _friendly(exc: BachsError) -> str:
    msg = exc.message or "Bachs refused the refund"
    low = msg.lower()
    if "insufficient balance" in low:
        return "Not enough money in Novo's Bachs balance. Top up the balance, then try again."
    if exc.status_code >= 500 or exc.status_code == 502:
        return f"Couldn't reach Bachs ({msg}). Try again."
    return f"Bachs: {msg}"


class RefundService:
    # ── Reading ──────────────────────────────────────────────────────────────

    @staticmethod
    async def _charges(db: AsyncSession, order_id: str) -> list[PaymentTransaction]:
        rows = await db.execute(
            select(PaymentTransaction)
            .join(Payment, Payment.id == PaymentTransaction.payment_id)
            .where(Payment.order_id == order_id, PaymentTransaction.txn_type == "charge",
                   PaymentTransaction.status.in_(MONEY_TXN_STATUSES))
            .order_by(PaymentTransaction.created_at)
        )
        return list(rows.scalars().all())

    @staticmethod
    async def _refunds(db: AsyncSession, order_id: str) -> list[Refund]:
        rows = await db.execute(
            select(Refund).join(Payment, Payment.id == Refund.payment_id)
            .where(or_(Refund.order_id == order_id, Payment.order_id == order_id))
            .order_by(Refund.created_at)
        )
        return list(rows.scalars().all())

    @staticmethod
    async def summary(db: AsyncSession, order: Order) -> dict:
        """What was paid, what was refunded, what can still be refunded, and what needs attention."""
        charges = await RefundService._charges(db, order.id)
        refunds = await RefundService._refunds(db, order.id)
        out = []
        for txn in charges:
            mine = [r for r in refunds if r.charge_reference == txn.provider_reference]
            active = [r for r in mine if r.status in ACTIVE]
            used = sum(float(r.amount or 0) for r in active)
            charge_id = bachs_charge_id(txn)
            out.append({
                "reference": txn.provider_reference,
                "provider": txn.provider,
                "kind": {"success": "payment", "duplicate": "second payment", "underpaid": "short payment"}[txn.status],
                "status": txn.status,
                "amount": float(txn.amount or 0),
                "overpaid_by": float(_meta(txn).get("overpaid_by") or 0),
                "refunded": round(used, 2),
                # Bachs takes one refund per charge, so after any active refund nothing more goes through Bachs.
                "refundable_via_bachs": bool(charge_id) and not active,
                "refundable": round(max(float(txn.amount or 0) - used, 0), 2),
                "created_at": txn.created_at.isoformat() if txn.created_at else None,
            })
        paid = sum(c["amount"] for c in out)
        if not out and order.payment_method in ("cash", "transfer") and order.payment_status == "paid":
            paid = float(order.total or 0)  # collected at the door; only a manual refund is possible
        refunded = sum(float(r.amount or 0) for r in refunds if r.status == "succeeded")
        pending = sum(float(r.amount or 0) for r in refunds if r.status == "processing")
        attention = []
        if order.status in CLOSED_ORDER_STATUSES and order.payment_status == "paid":
            attention.append("Paid order was cancelled — refund the customer" if order.status == "CANCELLED" else "Delivery failed on a paid order — check what happened, then refund")
        for c in out:
            if c["status"] in ("duplicate", "underpaid") and c["refunded"] == 0:
                attention.append(f"Unrefunded {c['kind']} of ₦{c['amount']:,.2f}")
            if c["overpaid_by"] > 0 and c["refunded"] == 0:
                attention.append(f"Customer overpaid by ₦{c['overpaid_by']:,.2f}")
        return {
            "charges": out,
            "paid": round(paid, 2),
            "refunded": round(refunded, 2),
            "refund_pending": round(pending, 2),
            "attention": attention,
        }

    @staticmethod
    def needs_refund_clause():
        """SQL: orders that have customer money we still owe back (for list filters and counts)."""
        unrefunded_extra = exists(
            select(PaymentTransaction.id)
            .join(Payment, Payment.id == PaymentTransaction.payment_id)
            .where(
                Payment.order_id == Order.id,
                PaymentTransaction.txn_type == "charge",
                PaymentTransaction.status.in_(("duplicate", "underpaid")),
                ~exists(select(Refund.id).where(
                    Refund.charge_reference == PaymentTransaction.provider_reference, Refund.status.in_(ACTIVE),
                )),
            )
        )
        return or_(and_(Order.status.in_(CLOSED_ORDER_STATUSES), Order.payment_status == "paid"), unrefunded_extra)

    @staticmethod
    def has_refund_activity_clause():
        """SQL: orders with any refund or extra payment, for the admin 'refunds' view."""
        return or_(
            and_(Order.status.in_(CLOSED_ORDER_STATUSES),
                 Order.payment_status.in_(("paid", "refund_pending", "refunded", "partially_refunded"))),
            exists(select(Refund.id).where(Refund.order_id == Order.id)),
            RefundService.needs_refund_clause(),
        )

    # ── Order payment status ─────────────────────────────────────────────────

    @staticmethod
    async def sync_order_status(db: AsyncSession, order: Order) -> None:
        if order.status == "DELIVERED" or order.payment_status not in ("paid", "refund_pending", "refunded", "partially_refunded"):
            return
        charges = [c for c in await RefundService._charges(db, order.id) if c.status == "success"]
        if not charges:
            return
        refs = {c.provider_reference for c in charges}
        refunds = [r for r in await RefundService._refunds(db, order.id) if r.charge_reference in refs or r.charge_reference is None]
        paid = sum(float(c.amount or 0) for c in charges)
        done = sum(float(r.amount or 0) for r in refunds if r.status == "succeeded")
        pending = any(r.status == "processing" for r in refunds)
        if pending:
            order.payment_status = "refund_pending"
        elif done >= paid - 0.005:
            order.payment_status = "refunded"
        elif done > 0:
            order.payment_status = "partially_refunded"
        else:
            order.payment_status = "paid"
        payment = (await db.execute(select(Payment).where(Payment.order_id == order.id))).scalars().first()
        if payment:
            payment.status = {"refunded": "refunded"}.get(order.payment_status, "paid")

    # ── Writing ──────────────────────────────────────────────────────────────

    @staticmethod
    async def refund_charge(
        db: AsyncSession,
        order: Order,
        txn: PaymentTransaction,
        *,
        amount: Optional[float] = None,
        reason_code: str,
        note: Optional[str] = None,
        bearer: str = "platform",
        actor_id: str = "system",
    ) -> Refund:
        """Refund one charge through Bachs. Always returns the Refund row (status may be 'failed')."""
        # Lock the payment row so two refunds for the same charge can't race.
        await db.execute(select(Payment).where(Payment.id == txn.payment_id).with_for_update())
        prior = (await db.execute(select(Refund).where(
            Refund.charge_reference == txn.provider_reference, Refund.status.in_(ACTIVE),
        ))).scalars().first()
        if prior:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="This payment already has a refund. Bachs allows only one refund per payment.")
        full = float(txn.amount or 0)
        amount = full if amount is None else round(float(amount), 2)
        if amount <= 0 or amount > full + 0.005:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Refund must be between ₦0 and ₦{full:,.2f}")

        reason_text = REASONS.get(reason_code, reason_code) + (f" — {note.strip()}" if note and note.strip() else "")
        refund = Refund(
            id=uuid.uuid4(), payment_id=txn.payment_id, order_id=order.id, amount=amount, currency=txn.currency or "NGN",
            status="processing", reason=reason_text[:500], charge_reference=txn.provider_reference, method="bachs",
            bearer=bearer, reason_code=reason_code, created_by=actor_id,
        )
        refund.reference = f"novo-rf-{refund.id.hex[:24]}"
        db.add(refund)

        charge_id = bachs_charge_id(txn)
        if not charge_id:
            refund.status = "failed"
            refund.failure_reason = "This payment didn't go through Bachs card checkout, so Bachs can't refund it. Send the money by bank transfer and record it."
        else:
            body = {"charge_id": charge_id, "reference": refund.reference, "reason": reason_text[:500],
                    "idempotency_key": refund.reference}
            if amount < full - 0.005:
                body["amount"] = money(amount)  # leave it out for a full refund: Bachs refunds the whole charge
            try:
                res = await bachs_request("POST", "/v1/refunds", json=body, idempotency_key=refund.reference)
                RefundService._apply_bachs(refund, res)
            except BachsError as exc:
                logger.warning("Bachs refund for %s (%s) refused: %s %s", order.id, charge_id, exc.status_code, exc.message)
                found = None
                if exc.status_code == 409 or exc.status_code >= 500:
                    # Docs: after a network error or conflict, look the refund up by charge before retrying.
                    try:
                        found = await bachs_request("GET", f"/v1/refunds/by-charge/{charge_id}")
                    except BachsError:
                        found = None
                    if isinstance(found, list):
                        found = next((f for f in found if isinstance(f, dict) and _bachs_status(f.get("status")) != "failed"), None)
                if isinstance(found, dict) and (found.get("refund_id") or found.get("id")) and _bachs_status(found.get("status")) != "failed":
                    RefundService._apply_bachs(refund, found)
                else:
                    refund.status = "failed"
                    refund.failure_reason = _friendly(exc)[:500]
        if refund.status == "succeeded":
            refund.completed_at = _now()
        await db.flush()
        await RefundService.sync_order_status(db, order)
        await db.commit()
        RefundService._notify(order.id, refund)
        return refund

    @staticmethod
    def _apply_bachs(refund: Refund, res) -> None:
        res = res if isinstance(res, dict) else {}
        refund.provider_refund_id = str(res.get("refund_id") or res.get("id") or "") or None
        refund.status = _bachs_status(res.get("status"))
        if refund.status == "failed":
            refund.failure_reason = str(res.get("failure_reason") or res.get("reason") or "Bachs marked the refund failed")[:500]

    @staticmethod
    async def record_manual(
        db: AsyncSession,
        order: Order,
        *,
        reference: str,
        amount: Optional[float],
        reason_code: str,
        note: Optional[str],
        bearer: str,
        actor_id: str,
        charge_reference: Optional[str] = None,
    ) -> Refund:
        """An admin sent the money themselves (bank transfer, cash) and records it here."""
        from app.modules.payments.service import PaymentService

        charges = await RefundService._charges(db, order.id)
        refunds = await RefundService._refunds(db, order.id)
        if charge_reference:
            txn = next((c for c in charges if c.provider_reference == charge_reference), None)
            if not txn:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That payment isn't on this order")
            paid = float(txn.amount or 0)
            used = sum(float(r.amount or 0) for r in refunds if r.charge_reference == charge_reference and r.status in ACTIVE)
        else:
            # Cash / transfer on delivery, or a payment we have no record of: cap at what the order cost.
            txn = next((c for c in charges if c.status == "success"), None)
            charge_reference = txn.provider_reference if txn else None
            paid = sum(float(c.amount or 0) for c in charges) or (float(order.total or 0) if order.payment_status == "paid" else 0)
            used = sum(float(r.amount or 0) for r in refunds if r.status in ACTIVE)
        left = round(paid - used, 2)
        if left <= 0:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Nothing left to refund on this order")
        amount = left if amount is None else round(float(amount), 2)
        if amount <= 0 or amount > left + 0.005:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Refund must be between ₦0 and ₦{left:,.2f}")
        if (await db.execute(select(Refund.id).where(Refund.reference == reference.strip()[:128]))).first():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That refund reference was already recorded")

        payment = await PaymentService._get_or_create_payment(db, order)
        refund = Refund(
            payment_id=txn.payment_id if txn else payment.id, order_id=order.id, amount=amount, currency=order.currency or "NGN",
            status="succeeded", method="manual", reference=reference.strip()[:128], charge_reference=charge_reference,
            bearer=bearer, reason_code=reason_code, created_by=actor_id, completed_at=_now(),
            reason=(REASONS.get(reason_code, reason_code) + (f" — {note.strip()}" if note and note.strip() else ""))[:500],
        )
        db.add(refund)
        await db.flush()
        await RefundService.sync_order_status(db, order)
        await db.commit()
        RefundService._notify(order.id, refund)
        return refund

    # ── Automatic refunds ────────────────────────────────────────────────────

    @staticmethod
    async def auto_refund_order(db: AsyncSession, order_id: str, reason_code: str) -> list[Refund]:
        """Full refund of every unrefunded payment on a cancelled/failed order."""
        order = await db.get(Order, order_id)
        if not order or order.status not in CLOSED_ORDER_STATUSES:
            return []
        done = []
        refunds = await RefundService._refunds(db, order.id)
        for txn in await RefundService._charges(db, order.id):
            if any(r.charge_reference == txn.provider_reference and r.status in ACTIVE for r in refunds):
                continue
            try:
                done.append(await RefundService.refund_charge(db, order, txn, reason_code=reason_code))
            except HTTPException as exc:
                logger.info("Auto refund skipped for %s / %s: %s", order.id, txn.provider_reference, exc.detail)
        return done

    @staticmethod
    async def auto_refund_charge(db: AsyncSession, order_id: str, reference: str, reason_code: str) -> Optional[Refund]:
        order = await db.get(Order, order_id)
        txn = (await db.execute(select(PaymentTransaction).where(PaymentTransaction.provider_reference == reference))).scalar_one_or_none()
        if not order or not txn:
            return None
        try:
            return await RefundService.refund_charge(db, order, txn, reason_code=reason_code)
        except HTTPException as exc:
            logger.info("Auto refund skipped for %s / %s: %s", order_id, reference, exc.detail)
            return None

    # ── Bachs refund webhooks ────────────────────────────────────────────────

    @staticmethod
    async def handle_event(db: AsyncSession, kind: str, data: dict) -> None:
        refund_id = str(data.get("refund_id") or data.get("id") or "")
        reference = str(data.get("reference") or "")
        conds = [c for c in (Refund.provider_refund_id == refund_id if refund_id else None,
                             Refund.reference == reference if reference else None) if c is not None]
        if not conds:
            return
        refund = (await db.execute(select(Refund).where(or_(*conds)))).scalars().first()
        if not refund:
            logger.info("Bachs %s for unknown refund %s / %s", kind, refund_id, reference)
            return
        new = {"refund.paid": "succeeded", "refund.failed": "failed"}.get(kind) or _bachs_status(data.get("status"))
        if refund.status == new or refund.status == "succeeded":
            return  # repeat delivery, or a late event after we already know it's done
        refund.status = new
        refund.provider_refund_id = refund.provider_refund_id or refund_id or None
        if new == "succeeded":
            refund.completed_at = _now()
            if data.get("refunded_amount"):
                try:
                    refund.amount = float(data["refunded_amount"])
                except (TypeError, ValueError):
                    pass
        elif new == "failed":
            refund.failure_reason = str(data.get("failure_reason") or data.get("reason") or "Bachs couldn't complete the refund")[:500]
        order = await db.get(Order, refund.order_id) if refund.order_id else None
        if order:
            await RefundService.sync_order_status(db, order)
        await db.commit()
        if new == "failed":
            RefundService._notify(refund.order_id, refund)

    # ── Notifications ────────────────────────────────────────────────────────

    @staticmethod
    def _notify(order_id: Optional[str], refund: Refund) -> None:
        from app.modules.notifications import service as notify

        if not order_id:
            return
        if refund.status in ("processing", "succeeded"):
            notify.refund_started(order_id, refund.amount, refund.method or "bachs")
        else:
            notify.refund_problem(order_id, refund.amount, refund.failure_reason)


def schedule_auto_refund(order_id: str, reason_code: str, reference: Optional[str] = None) -> None:
    """Run an automatic refund after the current request, in its own DB session."""
    from app.core.database import AsyncSessionLocal
    from app.core.mailer import run_in_background

    async def runner():
        try:
            async with AsyncSessionLocal() as db:
                if reference:
                    await RefundService.auto_refund_charge(db, order_id, reference, reason_code)
                else:
                    await RefundService.auto_refund_order(db, order_id, reason_code)
        except Exception:
            logger.exception("Automatic refund for %s failed", order_id)

    run_in_background(runner())


def cancel_reason_code(actor_role: Optional[str], target: str) -> str:
    if target == "FAILED":
        return "delivery_failed"
    return {"merchant": "store_cancelled", "admin": "admin_cancelled"}.get(actor_role or "", "customer_cancelled")


__all__: Iterable[str] = ["RefundService", "schedule_auto_refund", "cancel_reason_code", "REASONS", "BEARERS"]
