from fastapi import APIRouter, Depends, status, Path, Body, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.modules.merchants.service import MerchantService

router = APIRouter()


@router.get("", status_code=status.HTTP_200_OK)
async def list_merchants(db: AsyncSession = Depends(get_db)):
    """List all active merchants on the platform."""
    merchants = await MerchantService.get_all(db)
    return {"success": True, "message": "Merchants retrieved", "data": merchants}


@router.get("/{merchant_id}", status_code=status.HTTP_200_OK)
async def get_merchant(merchant_id: str = Path(...), db: AsyncSession = Depends(get_db)):
    """Get a single merchant by ID."""
    merchant = await MerchantService.get_by_id(db, merchant_id)
    return {"success": True, "message": "Merchant retrieved", "data": merchant}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_merchant(payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Register a new merchant account. Owner is set to authenticated user."""
    merchant = await MerchantService.create(db, current_user["user_id"], payload)
    return {"success": True, "message": "Merchant created", "data": merchant}


@router.put("/{merchant_id}", status_code=status.HTTP_200_OK)
async def update_merchant(merchant_id: str = Path(...), payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Update merchant profile. Only the owner or admin can update."""
    merchant = await MerchantService.update(db, merchant_id, current_user["user_id"], payload)
    return {"success": True, "message": "Merchant updated", "data": merchant}


@router.patch("/{merchant_id}/status", status_code=status.HTTP_200_OK)
async def toggle_merchant_status(merchant_id: str = Path(...), payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(require_role("admin"))):
    """Admin only: Activate or suspend a merchant account."""
    merchant = await MerchantService.set_status(db, merchant_id, payload.get("status"))
    return {"success": True, "message": f"Merchant status set to {payload.get('status')}", "data": merchant}


@router.get("/{merchant_id}/stores", status_code=status.HTTP_200_OK)
async def get_merchant_stores(merchant_id: str = Path(...), db: AsyncSession = Depends(get_db)):
    """Get all stores belonging to a merchant."""
    stores = await MerchantService.get_stores(db, merchant_id)
    return {"success": True, "message": "Merchant stores retrieved", "data": stores}
