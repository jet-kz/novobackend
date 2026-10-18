"""
Event -> email notifications.

Every public function here is fire-and-forget: it schedules a background task that opens
its own DB session (the request's session may already be closed), looks up recipients and
sends. Call them only after the triggering change has been committed.
"""
import logging
import uuid

from sqlalchemy import text
from sqlalchemy.future import select

from app.core.database import AsyncSessionLocal
from app.core.mailer import run_in_background, send_email
from app.modules.notifications import templates

logger = logging.getLogger("novo.notifications")


async def get_user_contact(db, user_id: str | None) -> tuple[str | None, str | None]:
    """(email, full_name) for a Supabase auth user id."""
    if not user_id:
        return None, None
    try:
        uuid.UUID(str(user_id))
    except ValueError:
        return None, None
    row = (await db.execute(
        text(
            "select u.email, p.full_name from auth.users u "
            "left join user_profiles p on p.user_id = u.id::text where u.id = cast(:id as uuid)"
        ),
        {"id": str(user_id)},
    )).first()
    return (row[0], row[1]) if row else (None, None)


async def _send_to_user(db, user_id: str | None, build) -> None:
    email, name = await get_user_contact(db, user_id)
    if not email:
        return
    built = build(name)
    if built:
        await send_email(email, *built)


async def _send_to_customer(db, order, build) -> None:
    """Order emails: the account's address, or the email a guest gave at checkout."""
    email, name = await get_user_contact(db, order.customer_id)
    email = email or order.customer_email
    if not email:
        return
    built = build(name or order.customer_name)
    if built:
        await send_email(email, *built)


def _guarded(fn):
    """Run fn(db, ...) in the background with its own session, logging any failure."""
    def schedule(*args, **kwargs):
        async def runner():
            try:
                async with AsyncSessionLocal() as db:
                    await fn(db, *args, **kwargs)
            except Exception:
                logger.exception("Notification %s failed", fn.__name__)
        run_in_background(runner())
    schedule.__name__ = fn.__name__
    return schedule


async def _order_context(db, order_id: str):
    from app.modules.merchants.models import Merchant
    from app.modules.orders.models import Order, OrderItem
    from app.modules.stores.models import Store

    order = await db.get(Order, order_id)
    if not order:
        return None
    store = await db.get(Store, order.store_id) if order.store_id else None
    merchant = await db.get(Merchant, store.merchant_id) if store else None
    items = (await db.execute(select(OrderItem).where(OrderItem.order_id == order_id))).scalars().all()
    order_dict = {
        "id": order.id,
        "subtotal": order.subtotal,
        "delivery_fee": order.delivery_fee,
        "service_fee": order.service_fee,
        "tip": order.tip,
        "total": order.total,
        "payment_method": order.payment_method,
        "delivery_address": order.delivery_address,
        "customer_name": order.customer_name,
    }
    item_rows = [{"name": i.name, "quantity": i.quantity, "total": (i.price or 0) * (i.quantity or 1)} for i in items]
    return order, order_dict, store, merchant, item_rows


# ── Account ──────────────────────────────────────────────────────────────────

@_guarded
async def welcome(db, user_id: str, role: str) -> None:
    await _send_to_user(db, user_id, lambda name: templates.welcome(name, role))


@_guarded
async def password_changed(db, user_id: str) -> None:
    await _send_to_user(db, user_id, templates.password_changed)


# ── Orders ───────────────────────────────────────────────────────────────────

@_guarded
async def order_placed(db, order_id: str, track_url: str | None = None) -> None:
    ctx = await _order_context(db, order_id)
    if not ctx:
        return
    order, data, store, merchant, items = ctx
    store_name = store.name if store else "the store"
    await _send_to_customer(db, order, lambda name: templates.order_placed(name, data, store_name, items, track_url))
    # Card orders reach the merchant once paid (see payment_received).
    if order.payment_method != "card" and merchant:
        await _send_to_user(db, merchant.owner_id, lambda _: templates.merchant_new_order(store_name, data, items))


@_guarded
async def payment_received(db, order_id: str, amount) -> None:
    ctx = await _order_context(db, order_id)
    if not ctx:
        return
    order, data, store, merchant, items = ctx
    await _send_to_customer(db, order, lambda name: templates.payment_received(name, order.id, amount))
    if merchant:
        store_name = store.name if store else "your store"
        await _send_to_user(db, merchant.owner_id, lambda _: templates.merchant_new_order(store_name, data, items))


@_guarded
async def order_status_changed(db, order_id: str, new_status: str, reason: str | None = None, by_customer: bool = False) -> None:
    ctx = await _order_context(db, order_id)
    if not ctx:
        return
    order, _, store, merchant, _ = ctx
    store_name = store.name if store else "the store"
    if not by_customer:
        await _send_to_customer(
            db, order,
            lambda name: templates.order_status_update(
                name, order.id, new_status, store_name, reason, show_link=not order.guest_token_hash
            ),
        )
    if new_status == "CANCELLED" and by_customer and merchant:
        await _send_to_user(db, merchant.owner_id, lambda _: templates.merchant_order_cancelled(store_name, order.id, reason))


@_guarded
async def rider_assigned(db, order_id: str, rider_id: str, earnings) -> None:
    ctx = await _order_context(db, order_id)
    if not ctx:
        return
    order, _, store, _, _ = ctx
    await _send_to_user(
        db, rider_id,
        lambda name: templates.rider_job_assigned(
            name, order.id, store.name if store else "the store", store.address if store else None, earnings
        ),
    )


# ── Admin actions ────────────────────────────────────────────────────────────

@_guarded
async def store_verification_changed(db, store_id, verified: bool) -> None:
    from app.modules.merchants.models import Merchant
    from app.modules.stores.models import Store

    store = await db.get(Store, store_id)
    merchant = await db.get(Merchant, store.merchant_id) if store else None
    if merchant:
        await _send_to_user(db, merchant.owner_id, lambda name: templates.store_verification(name, store.name, verified))


@_guarded
async def merchant_status_changed(db, owner_id: str, new_status: str) -> None:
    await _send_to_user(db, owner_id, lambda name: templates.merchant_status(name, new_status))


@_guarded
async def rider_deactivated(db, rider_id: str) -> None:
    await _send_to_user(db, rider_id, templates.rider_deactivated)


# ── In-app notifications (stored) + email copy ───────────────────────────────

async def create_notifications(
    db, user_ids: list[str], title: str, body: str, *, kind: str = "message",
    sender_id: str | None = None, email: bool = True, cta_path: str | None = None,
) -> int:
    """Store a notification per user (caller commits) and email each of them in the background."""
    from app.modules.notifications.models import Notification

    ids = [str(u) for u in dict.fromkeys(user_ids) if u]
    for uid in ids:
        db.add(Notification(user_id=uid, title=title[:150], body=body, kind=kind, sender_id=sender_id))
    if email and ids:
        _email_many(ids, title, body, cta_path)
    return len(ids)


@_guarded
async def _email_many(db, user_ids: list[str], title: str, body: str, cta_path: str | None) -> None:
    for uid in user_ids:
        await _send_to_user(db, uid, lambda name: templates.direct_message(name, title, body, cta_path))


@_guarded
async def rider_reviewed(db, rider_id: str, approved: bool, note: str | None) -> None:
    await _send_to_user(db, rider_id, lambda name: templates.rider_review(name, approved, note))


# ── Payouts ──────────────────────────────────────────────────────────────────

@_guarded
async def settlement_sent(db, user_id: str, amount, path: str) -> None:
    await _send_to_user(db, user_id, lambda name: templates.settlement_sent(name, amount, path))


@_guarded
async def payout_account_active(db, user_id: str) -> None:
    await _send_to_user(db, user_id, templates.payout_account_active)


@_guarded
async def withdrawal_finished(db, user_id: str, amount, ok: bool, reason: str | None) -> None:
    await _send_to_user(db, user_id, lambda name: templates.withdrawal_finished(name, amount, ok, reason))
