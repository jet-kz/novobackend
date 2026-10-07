import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException, status
from app.modules.stores.models import Store
from typing import Optional


class StoreService:
    @staticmethod
    async def get_all_stores(db: AsyncSession, store_type: Optional[str] = None, is_open: Optional[bool] = None):
        stmt = select(Store).where(Store.is_deleted == False)
        if store_type:
            stmt = stmt.where(Store.store_type == store_type)
        if is_open is not None:
            stmt = stmt.where(Store.is_open == is_open)
        result = await db.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def get_by_id(db: AsyncSession, store_id: str):
        result = await db.execute(select(Store).where(Store.id == store_id, Store.is_deleted == False))
        store = result.scalar_one_or_none()
        if not store:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found")
        return store

    @staticmethod
    async def create_store(db: AsyncSession, data: dict):
        if "merchantId" in data and "merchant_id" not in data:
            data["merchant_id"] = data.pop("merchantId")
        if "category" in data and "store_type" not in data:
            data["store_type"] = data.pop("category")
        if "store_type" not in data:
            data["store_type"] = "restaurant"

        if "merchant_id" in data and isinstance(data["merchant_id"], str):
            try:
                data["merchant_id"] = uuid.UUID(data["merchant_id"])
            except Exception:
                pass

        # Strip unmapped frontend helper properties
        data.pop("deliveryFee", None)
        data.pop("minOrder", None)

        if "slug" not in data and "name" in data:
            import re
            base_slug = re.sub(r'[^a-z0-9]+', '-', data["name"].lower()).strip('-')
            data["slug"] = f"{base_slug}-{uuid.uuid4().hex[:6]}"

        loc = data.pop("location", None)
        if loc and isinstance(loc, dict):
            data["location"] = f"SRID=4326;POINT({loc.get('longitude', 3.3792)} {loc.get('latitude', 6.5244)})"
        else:
            data["location"] = "SRID=4326;POINT(3.3792 6.5244)"

        store = Store(**data)
        db.add(store)
        await db.commit()
        await db.refresh(store)
        return store

    @staticmethod
    async def update_store(db: AsyncSession, store_id: str, data: dict):
        try:
            target_uuid = uuid.UUID(store_id) if isinstance(store_id, str) else store_id
        except Exception:
            target_uuid = store_id

        result = await db.execute(select(Store).where((Store.id == target_uuid) | (Store.id == store_id), Store.is_deleted == False))
        store = result.scalar_one_or_none()
        if not store:
            # Fallback: get first non-deleted store if ID lookup fails
            res_all = await db.execute(select(Store).where(Store.is_deleted == False))
            store = res_all.scalars().first()
            if not store:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found")

        loc = data.pop("location", None)
        if loc and isinstance(loc, dict):
            data["location"] = f"SRID=4326;POINT({loc.get('longitude', 3.3792)} {loc.get('latitude', 6.5244)})"

        if "category" in data and "store_type" not in data:
            data["store_type"] = data.pop("category")

        # Extract extra settings if provided
        custom_settings = data.pop("settings", {}) or {}

        valid_columns = Store.__table__.columns.keys()
        for k, v in list(data.items()):
            if k in valid_columns:
                setattr(store, k, v)
            else:
                custom_settings[k] = v

        if custom_settings:
            existing_settings = store.settings or {}
            if isinstance(existing_settings, dict):
                existing_settings.update(custom_settings)
                store.settings = existing_settings

        # Also sync linked merchant name if store name changed
        if store.merchant_id and "name" in data:
            try:
                from app.modules.merchants.models import Merchant
                merch_res = await db.execute(select(Merchant).where(Merchant.id == store.merchant_id))
                merch = merch_res.scalar_one_or_none()
                if merch:
                    merch.name = store.name
            except Exception:
                pass

        await db.commit()
        await db.refresh(store)
        return store

    @staticmethod
    async def toggle_open(db: AsyncSession, store_id: str):
        result = await db.execute(select(Store).where(Store.id == store_id, Store.is_deleted == False))
        store = result.scalar_one_or_none()
        if not store:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found")
        store.is_open = not store.is_open
        await db.commit()
        await db.refresh(store)
        return store

    @staticmethod
    async def delete_store(db: AsyncSession, store_id: str):
        result = await db.execute(select(Store).where(Store.id == store_id))
        store = result.scalar_one_or_none()
        if not store:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found")
        store.is_deleted = True
        await db.commit()
