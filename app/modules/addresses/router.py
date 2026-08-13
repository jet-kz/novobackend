from fastapi import APIRouter, Depends, status, Path, Body
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from app.core.database import get_db
from app.core.security import get_current_user
from app.modules.addresses.service import AddressService

router = APIRouter()


@router.get("", status_code=status.HTTP_200_OK)
async def list_addresses(db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get all saved addresses for the authenticated user."""
    addresses = await AddressService.get_user_addresses(db, current_user["user_id"])
    return {"success": True, "message": "Addresses retrieved successfully", "data": addresses}


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_address(payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Save a new delivery address for the authenticated user."""
    address = await AddressService.create_address(db, current_user["user_id"], payload)
    return {"success": True, "message": "Address saved successfully", "data": address}


@router.put("/{address_id}", status_code=status.HTTP_200_OK)
async def update_address(address_id: str = Path(...), payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Update an existing delivery address."""
    address = await AddressService.update_address(db, address_id, current_user["user_id"], payload)
    return {"success": True, "message": "Address updated successfully", "data": address}


@router.patch("/{address_id}/default", status_code=status.HTTP_200_OK)
async def set_default_address(address_id: str = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Set a specific address as the user's default delivery address."""
    address = await AddressService.set_default(db, address_id, current_user["user_id"])
    return {"success": True, "message": "Default address updated", "data": address}


@router.delete("/{address_id}", status_code=status.HTTP_200_OK)
async def delete_address(address_id: str = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Soft-delete a delivery address."""
    await AddressService.delete_address(db, address_id, current_user["user_id"])
    return {"success": True, "message": "Address removed successfully", "data": None}
