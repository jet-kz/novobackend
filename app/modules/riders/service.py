from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException, status
from app.modules.riders.models import RiderProfile
from app.modules.deliveries.models import Delivery
from typing import Optional
from datetime import datetime, timedelta, timezone
from app.modules.notifications import service as notify

VEHICLE_TYPES = ("motorcycle", "bicycle", "car")


class RiderService:
    @staticmethod
    async def get_all_riders(
        db: AsyncSession, rider_status: Optional[str] = None, vehicle_type: Optional[str] = None,
        approval_status: Optional[str] = None,
    ):
        stmt = select(RiderProfile).where(RiderProfile.is_deleted == False)
        if approval_status:
            stmt = stmt.where(RiderProfile.approval_status == approval_status)
        if rider_status:
            stmt = stmt.where(RiderProfile.status == rider_status)
        if vehicle_type:
            stmt = stmt.where(RiderProfile.vehicle_type == vehicle_type)
        result = await db.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def get_by_id(db: AsyncSession, rider_id: str):
        result = await db.execute(select(RiderProfile).where(RiderProfile.id == rider_id, RiderProfile.is_deleted == False))
        rider = result.scalar_one_or_none()
        if not rider:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rider not found")
        return rider

    @staticmethod
    async def get_or_create_for_user(db: AsyncSession, user_id: str, data: Optional[dict] = None) -> RiderProfile:
        """Rider rows are keyed by the auth user id. Create one on first use (flush only; caller commits)."""
        rider = await db.get(RiderProfile, user_id)
        if rider and rider.is_deleted:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This rider account has been deactivated")
        if rider:
            return rider
        data = data or {}
        vehicle = str(data.get("vehicle_type") or "motorcycle").lower()
        rider = RiderProfile(
            id=user_id,
            vehicle_type=vehicle if vehicle in VEHICLE_TYPES else "motorcycle",
            vehicle_plate=(str(data.get("vehicle_plate")).strip()[:50] if data.get("vehicle_plate") else None),
            status="offline",
            rating=5.0,
            total_deliveries=0,
        )
        db.add(rider)
        await db.flush()
        return rider

    @staticmethod
    async def create_rider(db: AsyncSession, user_id: str, data: dict):
        rider = await RiderService.get_or_create_for_user(db, user_id, data)
        if data.get("vehicle_type") in VEHICLE_TYPES:
            rider.vehicle_type = data["vehicle_type"]
        if data.get("vehicle_plate"):
            rider.vehicle_plate = str(data["vehicle_plate"]).strip()[:50]
        await db.commit()
        await db.refresh(rider)
        return rider

    @staticmethod
    async def update_status(db: AsyncSession, rider_id: str, new_status: Optional[str]):
        rider = await RiderService.get_or_create_for_user(db, rider_id)
        if not new_status:
            new_status = "offline" if rider.status in ("online", "busy") else "online"
        if new_status not in ("online", "offline"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Status must be online or offline")
        if new_status == "online" and rider.approval_status != "approved":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account is still being reviewed. You can go online once it's approved."
                if rider.approval_status == "pending" else "Your application wasn't approved. Update your details and we'll review it again.",
            )
        if new_status == "offline" and rider.status == "busy":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Finish your current delivery before going offline")
        rider.status = new_status
        await db.commit()
        await db.refresh(rider)
        return rider

    @staticmethod
    async def update_me(db: AsyncSession, rider_id: str, data: dict) -> RiderProfile:
        """Rider edits vehicle details / ID document. A rejected rider who updates goes back to review."""
        rider = await RiderService.get_or_create_for_user(db, rider_id)
        changed = False
        vehicle = str(data.get("vehicle_type") or "").lower()
        if vehicle in VEHICLE_TYPES:
            rider.vehicle_type, changed = vehicle, True
        if "vehicle_plate" in data:
            rider.vehicle_plate, changed = (str(data["vehicle_plate"] or "").strip()[:50] or None), True
        if "id_document_path" in data:
            # Storage path inside the private rider-documents bucket, under the rider's own folder.
            path = str(data["id_document_path"] or "").strip()[:500]
            if path and not path.startswith(f"{rider_id}/"):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Upload the document from your own account")
            rider.id_document_url, changed = (path or None), True
        if changed and rider.approval_status == "rejected":
            rider.approval_status = "pending"
        uploaded_id = "id_document_path" in data and bool(rider.id_document_url)
        await db.commit()
        await db.refresh(rider)
        if uploaded_id and rider.approval_status == "pending":
            from app.modules.notifications import service as notify

            notify.rider_ready_for_review(rider.id)
        return rider

    @staticmethod
    async def review(db: AsyncSession, rider_id: str, decision: str, note: Optional[str], reviewer_id: str) -> RiderProfile:
        """Admin approves or rejects a rider's onboarding, then notifies them (in-app + email)."""
        from app.modules.notifications import service as notify

        if decision not in ("approve", "reject"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="decision must be approve or reject")
        rider = await RiderService.get_by_id(db, rider_id)
        approved = decision == "approve"
        note = (note or "").strip()[:500] or None
        rider.approval_status = "approved" if approved else "rejected"
        rider.approval_note = note
        rider.reviewed_at = datetime.now(timezone.utc)
        if not approved and rider.status == "online":
            rider.status = "offline"
        await notify.create_notifications(
            db, [rider.id],
            "You're approved to ride" if approved else "Your rider application needs attention",
            ("You can now go online and start taking deliveries." if approved else "We couldn't approve your account yet.")
            + (f"\n\nNote from our team: {note}" if note else ""),
            kind="approval", sender_id=reviewer_id, email=False,
        )
        await db.commit()
        await db.refresh(rider)
        notify.rider_reviewed(rider.id, approved, note)
        return rider

    @staticmethod
    async def message(db: AsyncSession, rider_ids: list[str], title: str, body: str, sender_id: str) -> int:
        from app.modules.notifications import service as notify

        title, body = (title or "").strip(), (body or "").strip()
        if not body:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message can't be empty")
        sent = await notify.create_notifications(
            db, rider_ids, title or "Message from Novo", body, sender_id=sender_id, cta_path="/rider/messages"
        )
        await db.commit()
        return sent

    @staticmethod
    async def get_earnings(db: AsyncSession, rider_id: str) -> dict:
        from app.modules.orders.models import Order

        now = datetime.now(timezone.utc)
        start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_week = start_today - timedelta(days=start_today.weekday())
        res = await db.execute(
            select(Delivery, Order.tip)
            .join(Order, Order.id == Delivery.order_id)
            .where(Delivery.rider_id == rider_id, Delivery.status == "delivered")
        )
        today = week = tips_today = total = 0.0
        count = 0
        for delivery, tip in res.all():
            amount = float(delivery.rider_earnings or 0)
            total += amount
            count += 1
            at = delivery.delivered_at
            if at and at.tzinfo is None:
                at = at.replace(tzinfo=timezone.utc)
            if at and at >= start_week:
                week += amount
            if at and at >= start_today:
                today += amount
                tips_today += float(tip or 0)
        return {
            "earnings_today": round(today, 2),
            "earnings_this_week": round(week, 2),
            "tips_today": round(tips_today, 2),
            "earnings_total": round(total, 2),
            "total_deliveries": count,
        }

    @staticmethod
    async def get_deliveries(db: AsyncSession, rider_id: str):
        result = await db.execute(select(Delivery).where(Delivery.rider_id == rider_id))
        return result.scalars().all()

    @staticmethod
    async def deactivate(db: AsyncSession, rider_id: str):
        result = await db.execute(select(RiderProfile).where(RiderProfile.id == rider_id))
        rider = result.scalar_one_or_none()
        if not rider:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rider not found")
        was_active = not rider.is_deleted
        rider.is_deleted = True
        rider.status = "offline"
        await db.commit()
        if was_active:
            notify.rider_deactivated(rider.id)
