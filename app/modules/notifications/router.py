import uuid
from datetime import datetime, timezone

from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, status
from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import get_db
from app.core.security import get_current_user, get_optional_user
from app.core.serializers import model_to_dict
from app.modules.notifications.models import Notification

router = APIRouter()


@router.get("/me", status_code=status.HTTP_200_OK)
async def my_notifications(db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Latest 50 messages for the signed-in user, newest first, plus the unread count."""
    uid = current_user["user_id"]
    rows = (await db.execute(
        select(Notification).where(Notification.user_id == uid).order_by(Notification.created_at.desc()).limit(50)
    )).scalars().all()
    unread = (await db.execute(
        select(func.count()).select_from(Notification).where(Notification.user_id == uid, Notification.read_at.is_(None))
    )).scalar() or 0
    return {"success": True, "data": {"items": [model_to_dict(r) for r in rows], "unread": unread}}


@router.post("/{notification_id}/read", status_code=status.HTTP_200_OK)
async def mark_read(notification_id: uuid.UUID = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    await db.execute(
        update(Notification)
        .where(Notification.id == notification_id, Notification.user_id == current_user["user_id"], Notification.read_at.is_(None))
        .values(read_at=datetime.now(timezone.utc))
    )
    await db.commit()
    return {"success": True, "data": None}


@router.post("/read-all", status_code=status.HTTP_200_OK)
async def mark_all_read(db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    await db.execute(
        update(Notification)
        .where(Notification.user_id == current_user["user_id"], Notification.read_at.is_(None))
        .values(read_at=datetime.now(timezone.utc))
    )
    await db.commit()
    return {"success": True, "data": None}


# ── Web push subscriptions ───────────────────────────────────────────────────

@router.get("/push/key", status_code=status.HTTP_200_OK)
async def push_public_key():
    """VAPID public key the browser needs to subscribe. Empty when push isn't configured."""
    from app.core import config

    return {"success": True, "data": {"public_key": config.VAPID_PUBLIC_KEY or None}}


@router.post("/push/subscribe", status_code=status.HTTP_200_OK)
async def push_subscribe(
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    user: Optional[dict] = Depends(get_optional_user),
):
    """
    Save this device for push. Signed-in users get all their alerts; guests pass guest_order_id +
    guest_token to follow one order (open_url is their private tracking link).
    """
    from app.modules.notifications.models import PushSubscription
    from app.modules.orders.service import OrderService

    sub = payload.get("subscription") or {}
    endpoint = str(sub.get("endpoint") or "")
    keys = sub.get("keys") or {}
    if not endpoint.startswith("https://") or not keys.get("p256dh") or not keys.get("auth"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid push subscription")

    guest_order_id = None
    open_url = None
    if payload.get("guest_order_id"):
        order = await OrderService.load_guest_order(db, str(payload["guest_order_id"]), str(payload.get("guest_token") or ""))
        guest_order_id = order.id
        candidate = str(payload.get("open_url") or "")
        open_url = candidate[:500] if candidate.startswith("/track/") else None
    if not user and not guest_order_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in or open your order link to turn on alerts")

    row = (await db.execute(select(PushSubscription).where(PushSubscription.endpoint == endpoint))).scalar_one_or_none()
    if not row:
        row = PushSubscription(endpoint=endpoint)
        db.add(row)
    row.p256dh, row.auth = str(keys["p256dh"])[:255], str(keys["auth"])[:255]
    row.user_agent = str(payload.get("user_agent") or "")[:255] or None
    if user:
        row.user_id = user["user_id"]
    if guest_order_id:
        row.guest_order_id, row.open_url = guest_order_id, open_url
    await db.commit()
    return {"success": True, "data": None}


@router.post("/push/unsubscribe", status_code=status.HTTP_200_OK)
async def push_unsubscribe(payload: dict = Body(...), db: AsyncSession = Depends(get_db)):
    from app.modules.notifications.models import PushSubscription

    row = (await db.execute(
        select(PushSubscription).where(PushSubscription.endpoint == str(payload.get("endpoint") or ""))
    )).scalar_one_or_none()
    if row:
        await db.delete(row)
        await db.commit()
    return {"success": True, "data": None}
