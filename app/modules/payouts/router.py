from fastapi import APIRouter, Body, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.core.serializers import model_to_dict
from app.modules.payments.bachs_service import BachsError, available_amount, bachs_enabled, bachs_request
from app.modules.payouts.models import PayoutAccount, Settlement, Withdrawal
from app.modules.payouts.service import NIGERIAN_BANKS, PayoutService

router = APIRouter()


def _account_view(account: PayoutAccount | None) -> dict | None:
    if not account:
        return None
    return {
        "status": account.status,
        "transfers_enabled": account.transfers_enabled,
        "payouts_enabled": account.payouts_enabled,
        "requirements_due": account.requirements_due or [],
        "bank_name": account.bank_name,
        "account_last4": account.account_last4,
        "account_name": account.account_name,
    }


@router.get("/banks", status_code=status.HTTP_200_OK)
async def list_banks():
    """Nigerian banks for the payout form (from Bachs when available)."""
    if bachs_enabled():
        try:
            res = await bachs_request("GET", "/v1/reference/banks", params={"country": "NG"})
            items = res if isinstance(res, list) else (res.get("items") or res.get("banks") or [])
            banks = [{"code": str(b.get("code") or b.get("bank_code")), "name": b.get("name")} for b in items if isinstance(b, dict)]
            if banks:
                return {"success": True, "data": sorted(banks, key=lambda b: b["name"] or "")}
        except BachsError:
            pass
    return {"success": True, "data": [{"code": c, "name": n} for c, n in sorted(NIGERIAN_BANKS, key=lambda x: x[1])]}


# ── Merchant / rider ─────────────────────────────────────────────────────────

@router.get("/me", status_code=status.HTTP_200_OK)
async def my_payouts(db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Earnings, payout account status, money ready to withdraw, and history."""
    payee_type, payee_id, _ = await PayoutService.payee_for_user(db, current_user)
    account = await PayoutService.account_for(db, payee_type, payee_id)
    if account:
        account = await PayoutService.refresh_account(db, account)
    settlements = (await db.execute(
        select(Settlement).where(Settlement.payee_type == payee_type, Settlement.payee_id == payee_id)
        .order_by(Settlement.created_at.desc()).limit(30)
    )).scalars().all()
    withdrawals = []
    if account:
        withdrawals = (await db.execute(
            select(Withdrawal).where(Withdrawal.payout_account_id == account.id).order_by(Withdrawal.created_at.desc()).limit(30)
        )).scalars().all()
    return {"success": True, "data": {
        "payee_type": payee_type,
        "earnings": await PayoutService.earnings(db, payee_type, payee_id),
        "account": _account_view(account),
        "withdrawable": await PayoutService.connected_balance(account) if account else None,
        "settlements": [model_to_dict(s) for s in settlements],
        "withdrawals": [model_to_dict(w) for w in withdrawals],
    }}


@router.post("/me/account", status_code=status.HTTP_200_OK)
async def set_up_payout_account(payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Add/replace bank details. Body: bank_code, bank_name, account_number, account_name, first_name, last_name, entity_type."""
    account = await PayoutService.setup_account(db, current_user, payload)
    return {"success": True, "message": "Payout account saved", "data": _account_view(account)}


@router.post("/me/verification-link", status_code=status.HTTP_200_OK)
async def verification_link(db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Bachs-hosted page where the payee completes identity checks."""
    return {"success": True, "data": {"url": await PayoutService.onboarding_link(db, current_user)}}


@router.post("/me/withdraw", status_code=status.HTTP_201_CREATED)
async def withdraw(payload: dict = Body(default={}), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Send settled money to the payee's bank. Omit amount to withdraw everything available."""
    withdrawal = await PayoutService.withdraw(db, current_user, (payload or {}).get("amount"))
    return {"success": True, "message": "Withdrawal started", "data": model_to_dict(withdrawal)}


# ── Admin ────────────────────────────────────────────────────────────────────

@router.get("/admin/overview", status_code=status.HTTP_200_OK)
async def admin_overview(db: AsyncSession = Depends(get_db), _: dict = Depends(require_role("admin"))):
    """Everyone Novo owes (or who owes Novo cash), their payout setup, and Novo's Bachs balance."""
    from app.modules.merchants.models import Merchant
    from app.modules.riders.models import RiderProfile
    from app.modules.users.models import UserProfile

    accounts = {(a.owner_type, a.owner_id): a for a in (await db.execute(select(PayoutAccount))).scalars().all()}
    payees = []
    for m in (await db.execute(select(Merchant).where(Merchant.is_deleted == False))).scalars().all():
        payees.append(("merchant", str(m.id), m.name))
    riders = (await db.execute(select(RiderProfile).where(RiderProfile.is_deleted == False, RiderProfile.approval_status == "approved"))).scalars().all()
    names = {}
    if riders:
        res = await db.execute(select(UserProfile).where(UserProfile.user_id.in_([r.id for r in riders])))
        names = {p.user_id: p.full_name for p in res.scalars().all()}
    payees += [("rider", r.id, names.get(r.id) or "Rider") for r in riders]

    rows = []
    for payee_type, payee_id, name in payees:
        rows.append({
            "payee_type": payee_type,
            "payee_id": payee_id,
            "name": name,
            "earnings": await PayoutService.earnings(db, payee_type, payee_id),
            "account": _account_view(accounts.get((payee_type, payee_id))),
        })

    balance = None
    if bachs_enabled():
        try:
            balance = available_amount(await bachs_request("GET", "/v1/balances"))
        except BachsError:
            balance = None
    recent = (await db.execute(select(Settlement).order_by(Settlement.created_at.desc()).limit(50))).scalars().all()
    return {"success": True, "data": {
        "bachs_configured": bachs_enabled(),
        "available_balance": balance,
        "payees": rows,
        "settlements": [model_to_dict(s) for s in recent],
    }}


@router.post("/admin/settle", status_code=status.HTTP_201_CREATED)
async def settle(payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(require_role("admin"))):
    """Transfer money from Novo's Bachs balance to a payee's account. Body: payee_type, payee_id, amount, note?"""
    settlement = await PayoutService.settle(
        db, str(payload.get("payee_type") or ""), str(payload.get("payee_id") or ""),
        payload.get("amount"), payload.get("note"), current_user["user_id"],
    )
    return {"success": True, "message": "Settlement sent", "data": model_to_dict(settlement)}
