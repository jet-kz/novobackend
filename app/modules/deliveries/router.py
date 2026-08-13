from fastapi import APIRouter, Depends, status, Path, Body, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.modules.deliveries.service import DeliveryService

router = APIRouter()


@router.get("/{delivery_id}", status_code=status.HTTP_200_OK)
async def get_delivery(delivery_id: str = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get delivery details including current status and assignment history."""
    delivery = await DeliveryService.get_by_id(db, delivery_id)
    return {"success": True, "message": "Delivery retrieved", "data": delivery}


@router.get("/order/{order_id}", status_code=status.HTTP_200_OK)
async def get_delivery_for_order(order_id: str = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get the active delivery for a specific order."""
    delivery = await DeliveryService.get_by_order(db, order_id)
    return {"success": True, "message": "Order delivery retrieved", "data": delivery}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_delivery(payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(require_role("dispatcher"))):
    """Dispatcher: Create and dispatch a new delivery for an order."""
    delivery = await DeliveryService.create(db, payload)
    return {"success": True, "message": "Delivery created and dispatched", "data": delivery}


@router.post("/{delivery_id}/assign/{rider_id}", status_code=status.HTTP_200_OK)
async def assign_rider(delivery_id: str = Path(...), rider_id: str = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(require_role("dispatcher"))):
    """Dispatcher: Offer a delivery to a specific rider."""
    assignment = await DeliveryService.assign_rider(db, delivery_id, rider_id)
    return {"success": True, "message": "Delivery offered to rider", "data": assignment}


@router.patch("/{delivery_id}/status", status_code=status.HTTP_200_OK)
async def update_delivery_status(delivery_id: str = Path(...), payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Rider: Update delivery status (picked_up, delivered, failed)."""
    delivery = await DeliveryService.update_status(db, delivery_id, payload.get("status"), current_user["user_id"])
    return {"success": True, "message": f"Delivery status updated to {payload.get('status')}", "data": delivery}


@router.post("/rider/location", status_code=status.HTTP_200_OK)
async def update_rider_location(payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Rider: Push live GPS location update."""
    await DeliveryService.update_rider_location(db, current_user["user_id"], payload)
    return {"success": True, "message": "Location updated", "data": None}
