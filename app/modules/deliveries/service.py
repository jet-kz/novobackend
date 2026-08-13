from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from fastapi import HTTPException, status
from datetime import datetime, timedelta, timezone
from app.modules.deliveries.models import Delivery, DeliveryAssignment, RiderLocationHistory
from app.modules.riders.models import RiderProfile


class DeliveryService:
    @staticmethod
    async def get_by_id(db: AsyncSession, delivery_id: str):
        result = await db.execute(select(Delivery).where(Delivery.id == delivery_id))
        delivery = result.scalar_one_or_none()
        if not delivery:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery not found")
        return delivery

    @staticmethod
    async def get_by_order(db: AsyncSession, order_id: str):
        result = await db.execute(select(Delivery).where(Delivery.order_id == order_id))
        delivery = result.scalar_one_or_none()
        if not delivery:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No delivery found for this order")
        return delivery

    @staticmethod
    async def create(db: AsyncSession, data: dict):
        pickup = data.pop("pickup_location", None)
        dropoff = data.pop("dropoff_location", None)
        if pickup:
            data["pickup_location"] = f"SRID=4326;POINT({pickup['longitude']} {pickup['latitude']})"
        if dropoff:
            data["dropoff_location"] = f"SRID=4326;POINT({dropoff['longitude']} {dropoff['latitude']})"
        delivery = Delivery(**data)
        db.add(delivery)
        await db.commit()
        await db.refresh(delivery)
        return delivery

    @staticmethod
    async def assign_rider(db: AsyncSession, delivery_id: str, rider_id: str):
        result = await db.execute(select(Delivery).where(Delivery.id == delivery_id))
        delivery = result.scalar_one_or_none()
        if not delivery:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery not found")

        expires_at = datetime.now(timezone.utc) + timedelta(minutes=3)
        assignment = DeliveryAssignment(
            delivery_id=delivery_id,
            rider_id=rider_id,
            status="offered",
            expires_at=expires_at
        )
        delivery.rider_id = rider_id
        delivery.assigned_at = datetime.now(timezone.utc)
        delivery.status = "assigned"
        db.add(assignment)
        await db.commit()
        await db.refresh(assignment)
        return assignment

    @staticmethod
    async def update_status(db: AsyncSession, delivery_id: str, new_status: str, rider_id: str):
        result = await db.execute(select(Delivery).where(Delivery.id == delivery_id))
        delivery = result.scalar_one_or_none()
        if not delivery:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery not found")
        if str(delivery.rider_id) != rider_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the assigned rider for this delivery")
        delivery.status = new_status
        now = datetime.now(timezone.utc)
        if new_status == "picked_up":
            delivery.picked_up_at = now
        elif new_status == "delivered":
            delivery.delivered_at = now
        await db.commit()
        await db.refresh(delivery)
        return delivery

    @staticmethod
    async def update_rider_location(db: AsyncSession, rider_id: str, data: dict):
        lon = data.get("longitude")
        lat = data.get("latitude")
        if not lon or not lat:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="longitude and latitude required")

        wkt = f"SRID=4326;POINT({lon} {lat})"

        # Update rider's current location on their profile
        result = await db.execute(select(RiderProfile).where(RiderProfile.id == rider_id))
        rider = result.scalar_one_or_none()
        if rider:
            rider.last_location = wkt

        # Log to history
        history_entry = RiderLocationHistory(rider_id=rider_id, location=wkt)
        db.add(history_entry)
        await db.commit()
