"""Admin console API. Everything here needs the admin role; managing admins needs super_admin."""
from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_role
from app.modules.admin.service import AdminService

router = APIRouter()
admin_only = require_role("admin")


def _require_super(user: dict) -> None:
    if "super_admin" not in (user.get("roles") or []):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only a super admin can manage admins")


@router.get("/overview")
async def overview(db: AsyncSession = Depends(get_db), _: dict = Depends(admin_only)):
    return {"success": True, "data": await AdminService.overview(db)}


# ── Users ────────────────────────────────────────────────────────────────────

@router.get("/users")
async def users(
    q: str = Query(""), role: str = Query(""), status_filter: str = Query("", alias="status"),
    limit: int = Query(50), offset: int = Query(0),
    db: AsyncSession = Depends(get_db), _: dict = Depends(admin_only),
):
    """Every account (customers, merchants, riders, admins) with email, roles and order count."""
    return {"success": True, "data": await AdminService.users(db, q, role, status_filter, limit, offset)}


@router.post("/users/{user_id}/suspend")
async def suspend_user(user_id: str = Path(...), payload: dict = Body(default={}), db: AsyncSession = Depends(get_db), actor: dict = Depends(admin_only)):
    """Block sign-in and API access immediately."""
    await AdminService.set_active(db, user_id, False, actor, (payload or {}).get("reason"))
    return {"success": True, "message": "Account suspended", "data": None}


@router.post("/users/{user_id}/reactivate")
async def reactivate_user(user_id: str = Path(...), db: AsyncSession = Depends(get_db), actor: dict = Depends(admin_only)):
    await AdminService.set_active(db, user_id, True, actor, None)
    return {"success": True, "message": "Account reactivated", "data": None}


@router.post("/users/{user_id}/password-reset")
async def send_password_reset(user_id: str = Path(...), db: AsyncSession = Depends(get_db), actor: dict = Depends(admin_only)):
    """Email the user a reset code (they choose the new password themselves)."""
    from sqlalchemy import text

    from app.core.audit import record
    from app.modules.auth.service import AuthService

    row = (await db.execute(text("select email from auth.users where id::text = :id"), {"id": user_id})).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    await AuthService.forgot_password(db, row[0])
    record(db, actor, "user.password_reset_sent", "user", user_id)
    await db.commit()
    return {"success": True, "message": f"Reset code sent to {row[0]}", "data": None}


@router.put("/users/{user_id}/admin")
async def set_admin(user_id: str = Path(...), payload: dict = Body(...), db: AsyncSession = Depends(get_db), actor: dict = Depends(admin_only)):
    """Super admin: give or remove admin access. Body: {grant: true|false}."""
    _require_super(actor)
    await AdminService.set_admin(db, user_id, bool(payload.get("grant")), actor)
    return {"success": True, "message": "Admin access updated", "data": None}


@router.post("/admins")
async def invite_admin(payload: dict = Body(...), db: AsyncSession = Depends(get_db), actor: dict = Depends(admin_only)):
    """Super admin: add an admin by email. New accounts get an email code to set their password."""
    _require_super(actor)
    data = await AdminService.invite_admin(db, payload.get("email"), str(payload.get("full_name") or "").strip(), actor)
    return {"success": True, "message": f"{data['email']} is now an admin", "data": data}


# ── Orders, payments, activity ───────────────────────────────────────────────

@router.get("/orders")
async def orders(
    view: str = Query("all", description="all | active | attention | awaiting_payment | delivered | cancelled | refunds"),
    q: str = Query(""), limit: int = Query(50), offset: int = Query(0),
    db: AsyncSession = Depends(get_db), _: dict = Depends(admin_only),
):
    return {"success": True, "data": await AdminService.orders(db, view, q, limit, offset)}


@router.get("/orders/{order_id}")
async def order_detail(order_id: str = Path(...), db: AsyncSession = Depends(get_db), _: dict = Depends(admin_only)):
    """Order with items, contacts, pickup code, status history (who changed what), payments and refunds."""
    return {"success": True, "data": await AdminService.order_detail(db, order_id)}


@router.post("/orders/{order_id}/refund")
async def record_refund(order_id: str = Path(...), payload: dict = Body(...), db: AsyncSession = Depends(get_db), actor: dict = Depends(admin_only)):
    """Record that a cancelled, paid order was refunded. Body: {reference, note?}."""
    reference = str(payload.get("reference") or "").strip()
    if not reference:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Add the refund reference (from Bachs or your bank)")
    data = await AdminService.record_refund(db, order_id, reference, payload.get("note"), actor)
    return {"success": True, "message": "Refund recorded", "data": data}


@router.get("/payments")
async def payments(limit: int = Query(100), offset: int = Query(0), db: AsyncSession = Depends(get_db), _: dict = Depends(admin_only)):
    return {"success": True, "data": await AdminService.payments(db, limit, offset)}


@router.get("/activity")
async def activity(limit: int = Query(100), offset: int = Query(0), db: AsyncSession = Depends(get_db), _: dict = Depends(admin_only)):
    """Who did what in the admin console, newest first."""
    return {"success": True, "data": await AdminService.activity(db, limit, offset)}


@router.get("/merchants")
async def merchants(db: AsyncSession = Depends(get_db), _: dict = Depends(admin_only)):
    """Merchants with owner contact details and their stores."""
    from app.modules.admin.service import merchants_with_stores

    return {"success": True, "data": await merchants_with_stores(db)}
