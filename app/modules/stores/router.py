from fastapi import APIRouter, Depends, status, Path, Body, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.modules.stores.service import StoreService

router = APIRouter()


@router.get("", status_code=status.HTTP_200_OK)
async def list_stores(
    store_type: Optional[str] = Query(None, description="Filter by type: restaurant, pharmacy, grocery"),
    is_open: Optional[bool] = Query(None, description="Filter by open status"),
    db: AsyncSession = Depends(get_db)
):
    """List all active stores. Optional filters by type and open status."""
    stores = await StoreService.get_all_stores(db, store_type=store_type, is_open=is_open)
    return {"success": True, "message": "Stores retrieved successfully", "data": stores}


@router.get("/{store_id}", status_code=status.HTTP_200_OK)
async def get_store(store_id: str = Path(...), db: AsyncSession = Depends(get_db)):
    """Get a single store by ID."""
    store = await StoreService.get_by_id(db, store_id)
    return {"success": True, "message": "Store retrieved", "data": store}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_store(payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Create a new store. location must be a {"longitude": x, "latitude": y} object."""
    store = await StoreService.create_store(db, payload)
    return {"success": True, "message": "Store created successfully", "data": store}


@router.put("/{store_id}", status_code=status.HTTP_200_OK)
async def update_store(store_id: str = Path(...), payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Update store details (name, address, logo, settings, etc.)."""
    store = await StoreService.update_store(db, store_id, payload)
    return {"success": True, "message": "Store updated", "data": store}


@router.patch("/{store_id}/toggle-open", status_code=status.HTTP_200_OK)
async def toggle_store_open(store_id: str = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Toggle whether the store is currently open or closed for orders."""
    store = await StoreService.toggle_open(db, store_id)
    return {"success": True, "message": f"Store is now {'open' if store.is_open else 'closed'}", "data": store}


@router.delete("/{store_id}", status_code=status.HTTP_200_OK)
async def delete_store(store_id: str = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(require_role("admin"))):
    """Admin: Soft-delete a store."""
    await StoreService.delete_store(db, store_id)
    return {"success": True, "message": "Store removed", "data": None}
