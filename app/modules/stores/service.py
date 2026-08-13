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
        loc = data.pop("location", None)
        if loc:
            data["location"] = f"SRID=4326;POINT({loc['longitude']} {loc['latitude']})"
        store = Store(**data)
        db.add(store)
        await db.commit()
        await db.refresh(store)
        return store

    @staticmethod
    async def update_store(db: AsyncSession, store_id: str, data: dict):
        result = await db.execute(select(Store).where(Store.id == store_id, Store.is_deleted == False))
        store = result.scalar_one_or_none()
        if not store:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found")
        loc = data.pop("location", None)
        if loc:
            data["location"] = f"SRID=4326;POINT({loc['longitude']} {loc['latitude']})"
        for k, v in data.items():
            setattr(store, k, v)
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
