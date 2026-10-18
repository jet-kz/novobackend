import logging
from fastapi import APIRouter, Depends, status, Path, Body, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from app.core.database import get_db
from app.core.access import assert_store_access, get_owned_merchant, is_admin, to_uuid
from app.core.security import get_current_user, get_optional_user, require_role
from app.modules.stores.service import StoreService

router = APIRouter()
logger = logging.getLogger(__name__)


def serialize_store(s) -> dict:
    settings = s.settings if isinstance(s.settings, dict) else {}
    return {
        "id": str(s.id),
        "merchant_id": str(s.merchant_id) if s.merchant_id else None,
        "name": s.name,
        "slug": s.slug,
        "store_type": s.store_type,
        "logo": s.logo,
        "banner": s.banner,
        "address": s.address,
        "phone": s.phone,
        "location": s.location if isinstance(s.location, dict) else None,
        "is_open": bool(s.is_open),
        "is_verified": bool(s.is_verified),
        "rating": getattr(s, "rating", None) or 5.0,
        "settings": settings,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


@router.get("", status_code=status.HTTP_200_OK)
async def list_stores(
    store_type: Optional[str] = Query(None, description="Filter by type: restaurant, pharmacy, grocery"),
    is_open: Optional[bool] = Query(None, description="Filter by open status"),
    db: AsyncSession = Depends(get_db),
    user: Optional[dict] = Depends(get_optional_user),
):
    """Approved stores of active merchants (admins see every store). Optional filters by type and open status."""
    from app.core.access import is_admin

    stores = await StoreService.get_all_stores(db, store_type=store_type, is_open=is_open, public=not is_admin(user))
    return {"success": True, "message": "Stores retrieved successfully", "data": [serialize_store(s) for s in stores]}


@router.get("/{store_id}", status_code=status.HTTP_200_OK)
async def get_store(store_id: str = Path(...), db: AsyncSession = Depends(get_db)):
    """Get a single store by ID."""
    store = await StoreService.get_by_id(db, store_id)
    return {"success": True, "message": "Store retrieved", "data": serialize_store(store)}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_store(payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Create a store under the caller's merchant account. Admins may pass merchant_id to create for any merchant.
    location may be a {"longitude": x, "latitude": y} object.
    """
    if is_admin(current_user) and payload.get("merchant_id"):
        merchant_id = to_uuid(payload["merchant_id"], "merchant_id")
    else:
        merchant = await get_owned_merchant(db, current_user["user_id"])
        if not merchant:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Register a merchant account before creating a store")
        merchant_id = merchant.id
    payload.pop("merchant_id", None)
    store = await StoreService.create_store(db, payload, merchant_id)
    return {"success": True, "message": "Store created successfully", "data": serialize_store(store)}


@router.put("/{store_id}", status_code=status.HTTP_200_OK)
async def update_store(store_id: str = Path(...), payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Owner/admin: update store details (name, address, logo, settings, etc.)."""
    store = await assert_store_access(db, store_id, current_user)
    store = await StoreService.update_store(db, store, payload)
    return {"success": True, "message": "Store updated", "data": serialize_store(store)}


@router.patch("/{store_id}/toggle-open", status_code=status.HTTP_200_OK)
async def toggle_store_open(store_id: str = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Owner/admin: toggle whether the store is accepting orders."""
    store = await assert_store_access(db, store_id, current_user)
    store = await StoreService.toggle_open(db, store)
    return {"success": True, "message": f"Store is now {'open' if store.is_open else 'closed'}", "data": serialize_store(store)}


@router.patch("/{store_id}/verify", status_code=status.HTTP_200_OK)
async def verify_store(store_id: str = Path(...), payload: Optional[dict] = Body(default=None), db: AsyncSession = Depends(get_db), current_user: dict = Depends(require_role("admin"))):
    """Admin: approve (or revoke approval of) a store."""
    store = await assert_store_access(db, store_id, current_user)
    verified = (payload or {}).get("is_verified", True)
    store = await StoreService.set_verified(db, store, bool(verified))
    from app.core.audit import record

    record(db, current_user, "store.approve" if store.is_verified else "store.unapprove", "store", store.id, {"name": store.name})
    await db.commit()
    return {"success": True, "message": "Store approved" if store.is_verified else "Store approval revoked", "data": serialize_store(store)}


@router.delete("/{store_id}", status_code=status.HTTP_200_OK)
async def delete_store(store_id: str = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(require_role("admin"))):
    """Admin: Soft-delete a store."""
    store = await assert_store_access(db, store_id, current_user)
    await StoreService.delete_store(db, store)
    return {"success": True, "message": "Store removed", "data": None}
