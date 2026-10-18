import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import get_db
from app.core.security import get_current_user
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
