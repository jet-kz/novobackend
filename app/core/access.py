"""
Ownership checks shared by store, product, order and inventory endpoints.

A merchant owns the stores whose merchant row has owner_id == their user id.
Admins (admin / super_admin role) pass every check.
"""
import uuid
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select


def is_admin(user: Optional[dict]) -> bool:
    roles = (user or {}).get("roles") or []
    return "admin" in roles or "super_admin" in roles


def is_rider(user: Optional[dict]) -> bool:
    return "rider" in ((user or {}).get("roles") or [])


def to_uuid(value, field: str = "id") -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid {field}")


async def get_owned_merchant(db: AsyncSession, user_id: str):
    from app.modules.merchants.models import Merchant

    res = await db.execute(
        select(Merchant).where(Merchant.owner_id == user_id, Merchant.is_deleted == False)
    )
    return res.scalars().first()


async def get_owned_store_ids(db: AsyncSession, user_id: str) -> list:
    from app.modules.merchants.models import Merchant
    from app.modules.stores.models import Store

    res = await db.execute(
        select(Store.id)
        .join(Merchant, Merchant.id == Store.merchant_id)
        .where(Merchant.owner_id == user_id, Merchant.is_deleted == False, Store.is_deleted == False)
    )
    return list(res.scalars().all())


async def assert_store_access(db: AsyncSession, store_id, user: dict):
    """Return the store if the user owns it (or is admin); 404/403 otherwise."""
    from app.modules.stores.models import Store

    sid = to_uuid(store_id, "store_id")
    res = await db.execute(select(Store).where(Store.id == sid, Store.is_deleted == False))
    store = res.scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found")
    if is_admin(user):
        return store
    if sid not in await get_owned_store_ids(db, user["user_id"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not manage this store")
    return store


async def assert_merchant_access(db: AsyncSession, merchant_id, user: dict):
    from app.modules.merchants.models import Merchant

    mid = to_uuid(merchant_id, "merchant_id")
    res = await db.execute(select(Merchant).where(Merchant.id == mid, Merchant.is_deleted == False))
    merchant = res.scalar_one_or_none()
    if not merchant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Merchant not found")
    if not is_admin(user) and str(merchant.owner_id) != str(user["user_id"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not manage this merchant")
    return merchant
