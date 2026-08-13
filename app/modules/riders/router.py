from fastapi import APIRouter, Depends, status, Path, Body, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.modules.riders.service import RiderService

router = APIRouter()


@router.get("", status_code=status.HTTP_200_OK)
async def list_riders(
    rider_status: Optional[str] = Query(None, description="online, offline, busy"),
    vehicle_type: Optional[str] = Query(None, description="motorcycle, bicycle, car"),
    db: AsyncSession = Depends(get_db)
):
    """List riders. Filter by status or vehicle type."""
    riders = await RiderService.get_all_riders(db, rider_status=rider_status, vehicle_type=vehicle_type)
    return {"success": True, "message": "Riders retrieved successfully", "data": riders}


@router.get("/{rider_id}", status_code=status.HTTP_200_OK)
async def get_rider(rider_id: str = Path(...), db: AsyncSession = Depends(get_db)):
    """Get a single rider's profile by ID."""
    rider = await RiderService.get_by_id(db, rider_id)
    return {"success": True, "message": "Rider retrieved", "data": rider}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_rider_profile(payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Register the authenticated user as a rider on the platform."""
    rider = await RiderService.create_rider(db, current_user["user_id"], payload)
    return {"success": True, "message": "Rider registered successfully", "data": rider}


@router.patch("/me/status", status_code=status.HTTP_200_OK)
async def update_rider_status(payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Rider: Toggle online/offline status."""
    rider = await RiderService.update_status(db, current_user["user_id"], payload.get("status"))
    return {"success": True, "message": f"Rider is now {payload.get('status')}", "data": rider}


@router.get("/me/deliveries", status_code=status.HTTP_200_OK)
async def get_my_deliveries(db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Rider: Get all deliveries assigned to the current rider."""
    deliveries = await RiderService.get_deliveries(db, current_user["user_id"])
    return {"success": True, "message": "Rider deliveries retrieved", "data": deliveries}


@router.delete("/{rider_id}", status_code=status.HTTP_200_OK)
async def deactivate_rider(rider_id: str = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(require_role("admin"))):
    """Admin: Soft-deactivate a rider account."""
    await RiderService.deactivate(db, rider_id)
    return {"success": True, "message": "Rider deactivated", "data": None}
