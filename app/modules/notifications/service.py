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


async def alert(
    db,
    *,
    title: str,
    body: str,
    url: str,
    user_ids: list | None = None,
    guest_order_id: str | None = None,
    kind: str = "order",
    tag: str | None = None,
) -> None:
    """
    Real-time alert: an in-app notification (bell / inbox) for each signed-in user, plus a push
    notification to every device they (or a guest following guest_order_id) subscribed.
    """
    from sqlalchemy import or_

    from app.core.push import push_enabled, send_push
    from app.modules.notifications.models import Notification, PushSubscription

    ids = [str(u) for u in dict.fromkeys(user_ids or []) if u and not str(u).startswith("guest:")]
    for uid in ids:
        db.add(Notification(user_id=uid, title=title[:150], body=body, kind=kind))
    if ids:
        await db.commit()
    if not push_enabled():
        return

    conditions = []
    if ids:
        conditions.append(PushSubscription.user_id.in_(ids))
    if guest_order_id:
        conditions.append(PushSubscription.guest_order_id == guest_order_id)
    if not conditions:
        return
    subs = (await db.execute(select(PushSubscription).where(or_(*conditions)))).scalars().all()
    # Guests open their private tracking link; everyone else the given url.
    by_url: dict[str, list] = {}
    for sub in subs:
        target = sub.open_url if (sub.guest_order_id and not sub.user_id and sub.open_url) else url
        by_url.setdefault(target, []).append(sub)
    gone = []
    for target, group in by_url.items():
        gone += await send_push(group, title, body, target, tag)
    for sub in gone:
        await db.delete(sub)
    if gone:
        await db.commit()


_CUSTOMER_PUSH = {
    "CONFIRMED": ("Order accepted", "{store} accepted your order."),
    "PREPARING": ("Being prepared", "{store} is preparing your order."),
    "READY_FOR_PICKUP": ("Order ready", "Your order is packed and waiting for a rider."),
    "RIDER_ASSIGNED": ("Rider assigned", "A rider is heading to {store} for your order."),
    "PICKED_UP": ("On the way", "Your rider has your order and is heading to you."),
    "DELIVERED": ("Delivered", "Your order from {store} has arrived. Enjoy!"),
    "CANCELLED": ("Order cancelled", "Your order from {store} was cancelled.{reason}"),
    "FAILED": ("Delivery problem", "We couldn't deliver your order from {store}.{reason}"),
}


def _customer_url(order) -> str:
    return f"/orders?orderId={order.id}"


async def _alert_merchant_new_order(db, order, merchant) -> None:
    pay = {"card": "paid online", "cash": "cash on delivery", "transfer": "transfer on delivery"}.get(order.payment_method, "")
    await alert(
        db,
        title=f"New order · ₦{float(order.total or 0):,.0f}",
        body=f"{order.customer_name or 'A customer'} placed order {order.id} ({pay}). Tap to accept.",
        url="/merchant/orders",
        user_ids=[merchant.owner_id],
        tag=f"order-{order.id}",
    )


async def _alert_riders_new_job(db, order, store) -> None:
    """Tell every approved rider who is online that a job is waiting."""
    from app.modules.riders.models import RiderProfile

    riders = (await db.execute(
        select(RiderProfile.id).where(
            RiderProfile.status == "online", RiderProfile.approval_status == "approved", RiderProfile.is_deleted == False
        )
    )).scalars().all()
    if not riders:
        return
    area = [a.strip() for a in (order.delivery_address or "").split(",")[-2:] if a.strip()]
    await alert(
        db,
        title="New delivery job",
        body=f"Pick up at {store.name if store else 'a store'}"
        + (f" → {', '.join(area)}" if area else "") + ". First to accept gets it.",
        url="/rider",
        user_ids=list(riders),
        kind="job",
        tag="new-job",
    )


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
        await _alert_merchant_new_order(db, order, merchant)
        await _send_to_user(db, merchant.owner_id, lambda _: templates.merchant_new_order(store_name, data, items))


@_guarded
async def payment_received(db, order_id: str, amount) -> None:
    ctx = await _order_context(db, order_id)
    if not ctx:
        return
    order, data, store, merchant, items = ctx
    await _send_to_customer(db, order, lambda name: templates.payment_received(name, order.id, amount))
    await alert(
        db, title="Payment received", body=f"We got your payment for order {order.id}. The store has it now.",
        url=_customer_url(order), user_ids=[order.customer_id], guest_order_id=order.id, tag=f"order-{order.id}",
    )
    if merchant:
        store_name = store.name if store else "your store"
        await _alert_merchant_new_order(db, order, merchant)
        await _send_to_user(db, merchant.owner_id, lambda _: templates.merchant_new_order(store_name, data, items))


@_guarded
async def order_status_changed(db, order_id: str, new_status: str, reason: str | None = None, by_customer: bool = False) -> None:
    ctx = await _order_context(db, order_id)
    if not ctx:
        return
    order, _, store, merchant, _ = ctx
    store_name = store.name if store else "the store"
    copy = _CUSTOMER_PUSH.get(new_status)
    if copy and not by_customer:
        title, body = copy
        await alert(
            db, title=title, body=body.format(store=store_name, reason=f" Reason: {reason}." if reason else ""),
            url=_customer_url(order), user_ids=[order.customer_id], guest_order_id=order.id, tag=f"order-{order.id}",
        )
    if new_status == "READY_FOR_PICKUP":
        await _alert_riders_new_job(db, order, store)
    if new_status == "CANCELLED" and by_customer and merchant:
        await alert(
            db, title="Order cancelled", body=f"The customer cancelled order {order.id}. Don't prepare it.",
            url="/merchant/orders", user_ids=[merchant.owner_id], tag=f"order-{order.id}",
        )
    if new_status in ("PICKED_UP", "DELIVERED") and merchant:
        await alert(
            db,
            title="Rider picked up" if new_status == "PICKED_UP" else "Order delivered",
            body=f"Order {order.id} " + ("has left your store." if new_status == "PICKED_UP" else "reached the customer."),
            url="/merchant/orders", user_ids=[merchant.owner_id], tag=f"order-{order.id}",
        )
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
    order, _, store, merchant, _ = ctx
    if merchant:
        await alert(
            db, title="Rider on the way", body=f"A rider accepted order {order.id} and is coming to pick it up.",
            url="/merchant/orders", user_ids=[merchant.owner_id], tag=f"order-{order.id}",
        )
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
    if ids:
        _push_only(ids, title, body, cta_path or "/")
    return len(ids)


@_guarded
async def _push_only(db, user_ids: list[str], title: str, body: str, url: str) -> None:
    """Push to devices without storing another inbox row (the caller already stored one)."""
    from app.core.push import push_enabled, send_push
    from app.modules.notifications.models import PushSubscription

    if not push_enabled():
        return
    subs = (await db.execute(select(PushSubscription).where(PushSubscription.user_id.in_(user_ids)))).scalars().all()
    for sub in await send_push(subs, title, body[:180], url):
        await db.delete(sub)
    await db.commit()


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
    await alert(db, title="Money settled to you", body=f"₦{float(amount):,.2f} is ready to withdraw.", url=path,
                user_ids=[user_id], kind="payout")
    await _send_to_user(db, user_id, lambda name: templates.settlement_sent(name, amount, path))


@_guarded
async def payout_account_active(db, user_id: str) -> None:
    await _send_to_user(db, user_id, templates.payout_account_active)


@_guarded
async def withdrawal_finished(db, user_id: str, amount, ok: bool, reason: str | None) -> None:
    await alert(
        db, title="Withdrawal paid" if ok else "Withdrawal failed",
        body=f"₦{float(amount):,.2f} " + ("is in your bank account." if ok else "couldn't be sent. Check your bank details."),
        url="/", user_ids=[user_id], kind="payout",
    )
    await _send_to_user(db, user_id, lambda name: templates.withdrawal_finished(name, amount, ok, reason))
