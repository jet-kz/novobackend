from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException, status
from app.modules.riders.models import RiderProfile
from app.modules.deliveries.models import Delivery
from typing import Optional


class RiderService:
    @staticmethod
    async def get_all_riders(db: AsyncSession, rider_status: Optional[str] = None, vehicle_type: Optional[str] = None):
        stmt = select(RiderProfile).where(RiderProfile.is_deleted == False)
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
    async def create_rider(db: AsyncSession, user_id: str, data: dict):
        data["id"] = user_id  # Use Supabase auth user ID as rider ID
        rider = RiderProfile(**data)
        db.add(rider)
        await db.commit()
        await db.refresh(rider)
        return rider

    @staticmethod
    async def update_status(db: AsyncSession, rider_id: str, new_status: str):
        if new_status not in ("online", "offline", "busy"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Status must be: online, offline, or busy")
        result = await db.execute(select(RiderProfile).where(RiderProfile.id == rider_id))
        rider = result.scalar_one_or_none()
        if not rider:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rider not found")
        rider.status = new_status
        await db.commit()
        await db.refresh(rider)
        return rider

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
        rider.is_deleted = True
        rider.status = "offline"
        await db.commit()
