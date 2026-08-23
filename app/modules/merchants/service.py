from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException, status
from app.modules.merchants.models import Merchant
from app.modules.stores.models import Store

class MerchantService:
    @staticmethod
    async def get_all(db: AsyncSession):
        result = await db.execute(select(Merchant).where(Merchant.is_deleted == False))
        return result.scalars().all()

    @staticmethod
    async def get_by_id(db: AsyncSession, merchant_id: str):
        result = await db.execute(select(Merchant).where(Merchant.id == merchant_id, Merchant.is_deleted == False))
        merchant = result.scalar_one_or_none()
        if not merchant:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Merchant not found")
        return merchant

    @staticmethod
    async def get_by_owner_id(db: AsyncSession, owner_id: str):
        result = await db.execute(select(Merchant).where(Merchant.owner_id == owner_id, Merchant.is_deleted == False))
        merchant = result.scalar_one_or_none()
        if not merchant:
            return None
        stores_res = await db.execute(select(Store).where(Store.merchant_id == merchant.id, Store.is_deleted == False))
        stores = stores_res.scalars().all()
        return {
            "merchant": merchant,
            "stores": stores
        }

    @staticmethod
    async def create(db: AsyncSession, owner_id: str, data: dict):
        data["owner_id"] = owner_id
        merchant = Merchant(**data)
        db.add(merchant)
        await db.commit()
        await db.refresh(merchant)
        return merchant

    @staticmethod
    async def update(db: AsyncSession, merchant_id: str, owner_id: str, data: dict):
        result = await db.execute(select(Merchant).where(Merchant.id == merchant_id, Merchant.is_deleted == False))
        merchant = result.scalar_one_or_none()
        if not merchant:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Merchant not found")
        if str(merchant.owner_id) != owner_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to update this merchant")
        for k, v in data.items():
            setattr(merchant, k, v)
        await db.commit()
        await db.refresh(merchant)
        return merchant

    @staticmethod
    async def set_status(db: AsyncSession, merchant_id: str, new_status: str):
        result = await db.execute(select(Merchant).where(Merchant.id == merchant_id))
        merchant = result.scalar_one_or_none()
        if not merchant:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Merchant not found")
        merchant.status = new_status
        await db.commit()
        await db.refresh(merchant)
        return merchant

    @staticmethod
    async def get_stores(db: AsyncSession, merchant_id: str):
        result = await db.execute(select(Store).where(Store.merchant_id == merchant_id, Store.is_deleted == False))
        return result.scalars().all()
