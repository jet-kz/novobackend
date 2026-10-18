"""Admin console queries: overview figures, user directory, order search, payments, activity log."""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.serializers import model_to_dict
from app.modules.auth.models import Role, UserRole
from app.modules.merchants.models import Merchant
from app.modules.orders.models import Order, OrderStatusHistory
from app.modules.payments.models import Payment, PaymentTransaction, Refund
from app.modules.riders.models import RiderProfile
from app.modules.stores.models import Store
from app.modules.users.models import UserProfile

STUCK_NEW_MINUTES = 15  # store hasn't accepted
STUCK_READY_MINUTES = 15  # no rider has taken it
ACTIVE = ("PENDING", "CONFIRMED", "PREPARING", "READY_FOR_PICKUP", "RIDER_ASSIGNED", "PICKED_UP")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _paid_or_cod():
    return (Order.payment_method != "card") | (Order.payment_status == "paid")


class AdminService:
    # ── Overview ─────────────────────────────────────────────────────────────

    @staticmethod
    async def overview(db: AsyncSession) -> dict:
        from app.modules.pricing.models import PricingSnapshot

        now = _now()
        start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        d7, d30 = now - timedelta(days=7), now - timedelta(days=30)

        async def scalar(stmt):
            return (await db.execute(stmt)).scalar() or 0

        delivered = Order.status == "DELIVERED"
        gmv = lambda since: scalar(select(func.coalesce(func.sum(Order.total), 0)).where(delivered, Order.created_at >= since))
        revenue = lambda since: scalar(
            select(func.coalesce(func.sum(PricingSnapshot.platform_revenue), 0))
            .join(Order, Order.id == PricingSnapshot.order_id)
            .where(delivered, Order.created_at >= since)
        )

        by_status = dict((await db.execute(
            select(Order.status, func.count()).where(Order.created_at >= d30).group_by(Order.status)
        )).all())
        delivered_30 = by_status.get("DELIVERED", 0)

        # Daily orders and delivered value, last 14 days.
        series_rows = (await db.execute(text(
            "select date_trunc('day', created_at at time zone 'Africa/Lagos')::date as d, count(*), "
            "coalesce(sum(case when status = 'DELIVERED' then total end), 0) "
            "from orders where created_at >= now() - interval '14 days' group by 1 order by 1"
        ))).all()
        series = {r[0].isoformat(): {"orders": r[1], "gmv": float(r[2])} for r in series_rows}
        days = [(now - timedelta(days=i)).date().isoformat() for i in range(13, -1, -1)]

        # Things that need someone to act.
        stuck_new = await scalar(select(func.count()).select_from(Order).where(
            Order.status == "PENDING", _paid_or_cod(), Order.created_at < now - timedelta(minutes=STUCK_NEW_MINUTES)
        ))
        stuck_ready = await scalar(select(func.count()).select_from(Order).where(
            Order.status == "READY_FOR_PICKUP", Order.updated_at < now - timedelta(minutes=STUCK_READY_MINUTES)
        ))
        needs_refund = await scalar(select(func.count()).select_from(Order).where(
            Order.status.in_(("CANCELLED", "FAILED")), Order.payment_status == "paid"
        ))
        pending_riders = await scalar(select(func.count()).select_from(RiderProfile).where(
            RiderProfile.approval_status == "pending", RiderProfile.is_deleted == False
        ))
        unverified_stores = await scalar(select(func.count()).select_from(Store).where(
            Store.is_verified == False, Store.is_deleted == False
        ))

        recent = (await db.execute(select(Order).order_by(Order.created_at.desc()).limit(8))).scalars().all()
        stores = {s.id: s.name for s in (await db.execute(select(Store))).scalars().all()}

        return {
            "today": {
                "orders": await scalar(select(func.count()).select_from(Order).where(Order.created_at >= start_today)),
                "gmv": float(await gmv(start_today)),
                "revenue": float(await revenue(start_today)),
            },
            "last_7_days": {"gmv": float(await gmv(d7)), "revenue": float(await revenue(d7))},
            "last_30_days": {
                "gmv": float(await gmv(d30)),
                "revenue": float(await revenue(d30)),
                "orders": sum(by_status.values()),
                "delivered": delivered_30,
                "cancelled": by_status.get("CANCELLED", 0) + by_status.get("FAILED", 0),
                "average_order": round(float(await gmv(d30)) / delivered_30, 2) if delivered_30 else 0,
            },
            "live_orders": {s: by_status.get(s, 0) for s in ACTIVE},
            "counts": {
                "customers": await scalar(text(
                    "select count(*) from auth.users u where not exists (select 1 from user_roles r "
                    "where r.user_id = u.id::text and r.role_id <> 'role_customer')"
                )),
                "merchants": await scalar(select(func.count()).select_from(Merchant).where(Merchant.is_deleted == False)),
                "stores": await scalar(select(func.count()).select_from(Store).where(Store.is_deleted == False)),
                "riders_approved": await scalar(select(func.count()).select_from(RiderProfile).where(
                    RiderProfile.approval_status == "approved", RiderProfile.is_deleted == False)),
                "riders_online": await scalar(select(func.count()).select_from(RiderProfile).where(
                    RiderProfile.status.in_(("online", "busy")), RiderProfile.is_deleted == False)),
            },
            "attention": {
                "orders_not_accepted": stuck_new,
                "orders_waiting_for_rider": stuck_ready,
                "refunds_to_handle": needs_refund,
                "riders_to_review": pending_riders,
                "stores_to_approve": unverified_stores,
            },
            "daily": [{"date": d, **series.get(d, {"orders": 0, "gmv": 0.0})} for d in days],
            "recent_orders": [
                {"id": o.id, "customer_name": o.customer_name, "store_name": stores.get(o.store_id), "total": o.total,
                 "status": o.status, "payment_method": o.payment_method, "payment_status": o.payment_status,
                 "created_at": o.created_at.isoformat() if o.created_at else None}
                for o in recent
            ],
        }

    # ── Users ────────────────────────────────────────────────────────────────

    @staticmethod
    async def users(db: AsyncSession, q: str = "", role: str = "", status_filter: str = "", limit: int = 50, offset: int = 0) -> dict:
        where, params = ["u.deleted_at is null"], {"limit": min(limit, 200), "offset": offset}
        if q:
            where.append("(u.email ilike :q or p.full_name ilike :q or p.phone ilike :q)")
            params["q"] = f"%{q.strip()}%"
        if status_filter == "suspended":
            where.append("p.is_active = false")
        elif status_filter == "active":
            where.append("coalesce(p.is_active, true) = true")
        role_sql = {
            "admin": "'admin' = any(r.roles) or 'super_admin' = any(r.roles)",
            "merchant": "'merchant_owner' = any(r.roles)",
            "rider": "'rider' = any(r.roles)",
            "customer": "r.roles is null or r.roles <@ array['customer']::varchar[]",
        }.get(role)
        if role_sql:
            where.append(f"({role_sql})")
        base = (
            "from auth.users u "
            "left join user_profiles p on p.user_id = u.id::text "
            "left join (select ur.user_id, array_agg(ro.name)::varchar[] as roles from user_roles ur "
            "           join roles ro on ro.id = ur.role_id group by ur.user_id) r on r.user_id = u.id::text "
            f"where {' and '.join(where)}"
        )
        total = (await db.execute(text(f"select count(*) {base}"), params)).scalar() or 0
        rows = (await db.execute(text(
            "select u.id::text, u.email, p.full_name, p.phone, coalesce(r.roles, array['customer']::varchar[]), "
            "coalesce(p.is_active, true), u.created_at, u.last_sign_in_at, u.email_confirmed_at is not null, "
            "(select count(*) from orders o where o.customer_id = u.id::text) "
            f"{base} order by u.created_at desc limit :limit offset :offset"
        ), params)).all()
        return {
            "total": total,
            "items": [
                {"id": r[0], "email": r[1], "name": r[2], "phone": r[3], "roles": list(r[4]), "is_active": r[5],
                 "created_at": r[6].isoformat() if r[6] else None,
                 "last_sign_in_at": r[7].isoformat() if r[7] else None,
                 "email_verified": r[8], "orders": r[9]}
                for r in rows
            ],
        }

    @staticmethod
    async def _profile(db: AsyncSession, user_id: str) -> UserProfile:
        profile = (await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))).scalar_one_or_none()
        if not profile:
            exists = (await db.execute(text("select 1 from auth.users where id::text = :id"), {"id": user_id})).first()
            if not exists:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
            profile = UserProfile(user_id=user_id, is_active=True)
            db.add(profile)
        return profile

    @staticmethod
    async def set_active(db: AsyncSession, user_id: str, active: bool, actor: dict, reason: Optional[str]) -> None:
        import asyncio

        from app.core.audit import record
        from app.integrations.supabase.client import supabase

        if user_id == actor["user_id"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You can't suspend your own account")
        profile = await AdminService._profile(db, user_id)
        profile.is_active = active
        # Ban in Supabase too so they can't sign in again; lifted on reactivation.
        await asyncio.to_thread(supabase.auth.admin.update_user_by_id, user_id, {"ban_duration": "none" if active else "876000h"})
        record(db, actor, "user.reactivate" if active else "user.suspend", "user", user_id, {"reason": reason} if reason else None)
        await db.commit()

    @staticmethod
    async def set_admin(db: AsyncSession, user_id: str, grant: bool, actor: dict) -> None:
        from app.core.audit import record

        if user_id == actor["user_id"] and not grant:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You can't remove your own admin access")
        await AdminService._profile(db, user_id)
        role = (await db.execute(select(Role).where(Role.name == "admin"))).scalar_one_or_none()
        if not role:
            role = Role(id="role_admin", name="admin")
            db.add(role)
            await db.flush()
        link = (await db.execute(select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role.id))).scalar_one_or_none()
        if grant and not link:
            db.add(UserRole(user_id=user_id, role_id=role.id))
        elif not grant:
            await db.execute(
                UserRole.__table__.delete().where(
                    UserRole.user_id == user_id,
                    UserRole.role_id.in_(select(Role.id).where(Role.name.in_(("admin", "super_admin")))),
                )
            )
        record(db, actor, "admin.grant" if grant else "admin.revoke", "user", user_id)
        await db.commit()

    @staticmethod
    async def invite_admin(db: AsyncSession, email: str, full_name: str, actor: dict) -> dict:
        """Make an existing user admin, or create the account and email them a code to set a password."""
        import asyncio

        from app.integrations.supabase.client import supabase
        from app.modules.auth.service import AuthService

        email = (email or "").strip().lower()
        if "@" not in email:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Enter a valid email")
        user = await AuthService.find_user(db, email)
        if user:
            user_id = user.id
        else:
            created = await asyncio.to_thread(supabase.auth.admin.create_user, {
                "email": email,
                "password": secrets.token_urlsafe(24),  # never used: they set their own via the reset code
                "email_confirm": True,
                "user_metadata": {"full_name": full_name},
            })
            user_id = created.user.id
            db.add(UserProfile(user_id=user_id, full_name=full_name or None, is_active=True))
            await db.commit()
        await AdminService.set_admin(db, user_id, True, actor)
        await AuthService.send_code(db, email, "reset", full_name)
        return {"user_id": user_id, "email": email, "existing_account": bool(user)}

    # ── Orders ───────────────────────────────────────────────────────────────

    @staticmethod
    async def orders(
        db: AsyncSession, view: str = "all", q: str = "", limit: int = 50, offset: int = 0,
    ) -> dict:
        from app.modules.orders.service import OrderService

        now = _now()
        filters = []
        if view == "active":
            filters.append(Order.status.in_(ACTIVE))
        elif view == "attention":
            filters.append(or_(
                and_(Order.status == "PENDING", _paid_or_cod(), Order.created_at < now - timedelta(minutes=STUCK_NEW_MINUTES)),
                and_(Order.status == "READY_FOR_PICKUP", Order.updated_at < now - timedelta(minutes=STUCK_READY_MINUTES)),
            ))
        elif view == "awaiting_payment":
            filters.append(and_(Order.payment_method == "card", Order.payment_status != "paid", Order.status.notin_(("CANCELLED", "FAILED"))))
        elif view == "delivered":
            filters.append(Order.status == "DELIVERED")
        elif view == "cancelled":
            filters.append(Order.status.in_(("CANCELLED", "FAILED")))
        elif view == "refunds":
            filters.append(and_(Order.status.in_(("CANCELLED", "FAILED")), Order.payment_status.in_(("paid", "refunded"))))
        if q:
            like = f"%{q.strip()}%"
            filters.append(or_(Order.id.ilike(like), Order.customer_name.ilike(like), Order.customer_phone.ilike(like),
                               Order.customer_email.ilike(like), Order.delivery_address.ilike(like)))
        stmt = select(Order).where(*filters)
        total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
        rows = (await db.execute(stmt.order_by(Order.created_at.desc()).limit(min(limit, 200)).offset(offset))).scalars().all()
        items = await OrderService._decorate(db, rows, include_pickup_code=True)
        for item, o in zip(items, rows):
            item["needs_refund"] = o.status in ("CANCELLED", "FAILED") and o.payment_status == "paid"
            item["stuck"] = (o.status == "PENDING" and o.created_at and o.created_at < now - timedelta(minutes=STUCK_NEW_MINUTES)) or (
                o.status == "READY_FOR_PICKUP" and o.updated_at and o.updated_at < now - timedelta(minutes=STUCK_READY_MINUTES))
        return {"total": total, "items": items}

    @staticmethod
    async def order_detail(db: AsyncSession, order_id: str) -> dict:
        from app.modules.orders.service import OrderService

        order = await OrderService._load(db, order_id)
        data = (await OrderService._decorate(db, [order], include_pickup_code=True))[0]
        history = (await db.execute(
            select(OrderStatusHistory).where(OrderStatusHistory.order_id == order_id).order_by(OrderStatusHistory.created_at)
        )).scalars().all()
        payments = (await db.execute(select(Payment).where(Payment.order_id == order_id))).scalars().all()
        txns, refunds = [], []
        if payments:
            ids = [p.id for p in payments]
            txns = (await db.execute(select(PaymentTransaction).where(PaymentTransaction.payment_id.in_(ids)))).scalars().all()
            refunds = (await db.execute(select(Refund).where(Refund.payment_id.in_(ids)))).scalars().all()
        changers = {h.changed_by_id for h in history}
        emails = {}
        if changers:
            rows = (await db.execute(text("select id::text, email from auth.users where id::text = any(:ids)"), {"ids": list(changers)})).all()
            emails = dict(rows)
        return {
            **data,
            "needs_refund": order.status in ("CANCELLED", "FAILED") and order.payment_status == "paid",
            "history": [{**model_to_dict(h), "changed_by_email": emails.get(h.changed_by_id)} for h in history],
            "transactions": [model_to_dict(t) for t in txns],
            "refunds": [model_to_dict(r) for r in refunds],
        }

    @staticmethod
    async def record_refund(db: AsyncSession, order_id: str, reference: str, note: Optional[str], actor: dict) -> dict:
        """Mark a cancelled, paid order as refunded (refund done in the Bachs dashboard or by transfer)."""
        from app.core.audit import record
        from app.modules.payments.service import PaymentService

        order = await db.get(Order, order_id)
        if not order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        if order.status not in ("CANCELLED", "FAILED") or order.payment_status != "paid":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only paid orders that were cancelled can be refunded")
        payment = await PaymentService._get_or_create_payment(db, order)
        db.add(Refund(payment_id=payment.id, amount=float(order.total), currency=order.currency or "NGN", status="processed",
                      reason=f"{reference.strip()}{' — ' + note.strip() if note else ''}"[:500] or None))
        payment.status = "refunded"
        order.payment_status = "refunded"
        record(db, actor, "order.refund", "order", order_id, {"reference": reference, "note": note, "amount": order.total})
        await db.commit()
        return await AdminService.order_detail(db, order_id)

    # ── Payments ─────────────────────────────────────────────────────────────

    @staticmethod
    async def payments(db: AsyncSession, limit: int = 100, offset: int = 0) -> dict:
        stmt = (
            select(PaymentTransaction, Payment.order_id, Order.customer_name, Order.total, Order.status)
            .join(Payment, Payment.id == PaymentTransaction.payment_id)
            .join(Order, Order.id == Payment.order_id)
        )
        total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
        rows = (await db.execute(stmt.order_by(PaymentTransaction.created_at.desc()).limit(min(limit, 200)).offset(offset))).all()
        collected = (await db.execute(select(func.coalesce(func.sum(PaymentTransaction.amount), 0)).where(
            PaymentTransaction.txn_type == "charge", PaymentTransaction.status == "success"))).scalar() or 0
        refunded = (await db.execute(select(func.coalesce(func.sum(Refund.amount), 0)).where(Refund.status == "processed"))).scalar() or 0
        cod = (await db.execute(select(func.coalesce(func.sum(Order.total), 0)).where(
            Order.status == "DELIVERED", Order.payment_method.in_(("cash", "transfer"))))).scalar() or 0
        return {
            "total": total,
            "totals": {"collected_online": float(collected), "refunded": float(refunded), "collected_on_delivery": float(cod)},
            "items": [
                {**model_to_dict(t), "order_id": oid, "customer_name": name, "order_total": ot, "order_status": ost}
                for t, oid, name, ot, ost in rows
            ],
        }

    # ── Activity log ─────────────────────────────────────────────────────────

    @staticmethod
    async def activity(db: AsyncSession, limit: int = 100, offset: int = 0) -> dict:
        from app.modules.audit.models import AuditLog

        total = (await db.execute(select(func.count()).select_from(AuditLog))).scalar() or 0
        rows = (await db.execute(select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(min(limit, 200)).offset(offset))).scalars().all()
        actors = list({r.actor for r in rows})
        emails = dict((await db.execute(text("select id::text, email from auth.users where id::text = any(:ids)"), {"ids": actors})).all()) if actors else {}
        return {
            "total": total,
            "items": [
                {"id": r.id, "actor": r.actor, "actor_email": emails.get(r.actor), "action": r.action,
                 "entity_type": r.entity_type, "entity_id": r.entity_id, "details": r.action_metadata,
                 "at": r.timestamp.isoformat() if r.timestamp else None}
                for r in rows
            ],
        }


async def merchants_with_stores(db: AsyncSession) -> list[dict]:
    """Every merchant with owner contact, status, and their stores (approval, open, pinned, orders)."""
    from app.modules.orders.service import real_store_location

    merchants = (await db.execute(select(Merchant).where(Merchant.is_deleted == False).order_by(Merchant.created_at.desc()))).scalars().all()
    stores = (await db.execute(select(Store).where(Store.is_deleted == False))).scalars().all()
    owner_ids = list({m.owner_id for m in merchants})
    owners = {}
    if owner_ids:
        rows = (await db.execute(text(
            "select u.id::text, u.email, p.full_name, p.phone from auth.users u "
            "left join user_profiles p on p.user_id = u.id::text where u.id::text = any(:ids)"
        ), {"ids": owner_ids})).all()
        owners = {r[0]: {"email": r[1], "name": r[2], "phone": r[3]} for r in rows}
    counts = dict((await db.execute(
        select(Order.store_id, func.count()).where(Order.status == "DELIVERED").group_by(Order.store_id)
    )).all())
    by_merchant: dict = {}
    for s in stores:
        by_merchant.setdefault(s.merchant_id, []).append({
            "id": str(s.id), "name": s.name, "category": s.store_type, "address": s.address, "phone": s.phone,
            "is_verified": bool(s.is_verified), "is_open": bool(s.is_open), "pinned": real_store_location(s) is not None,
            "logo": s.logo, "delivered_orders": counts.get(s.id, 0),
            "created_at": s.created_at.isoformat() if s.created_at else None,
        })
    return [
        {"id": str(m.id), "name": m.name, "status": m.status, "owner": owners.get(m.owner_id, {}), "owner_id": m.owner_id,
         "created_at": m.created_at.isoformat() if m.created_at else None, "stores": by_merchant.get(m.id, [])}
        for m in merchants
    ]
