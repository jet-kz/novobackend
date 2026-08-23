from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException, status
from app.modules.products.models import Product, ProductCategory
from typing import Optional


import uuid

class ProductService:
    @staticmethod
    async def get_products(db: AsyncSession, store_id: Optional[str] = None, category_id: Optional[str] = None, in_stock: Optional[bool] = None):
        stmt = select(Product).where(Product.is_deleted == False)
        if store_id:
            try:
                target_uuid = uuid.UUID(store_id) if isinstance(store_id, str) else store_id
                stmt = stmt.where(Product.store_id == target_uuid)
            except Exception:
                return []
        if category_id:
            stmt = stmt.where(Product.category_id == category_id)
        if in_stock is not None:
            stmt = stmt.where(Product.in_stock == in_stock)
        result = await db.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def get_categories(db: AsyncSession, store_id: Optional[str] = None):
        stmt = select(ProductCategory).where(ProductCategory.is_deleted == False)
        if store_id:
            try:
                target_uuid = uuid.UUID(store_id) if isinstance(store_id, str) else store_id
                stmt = stmt.where(ProductCategory.store_id == target_uuid)
            except Exception:
                return []
        result = await db.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def get_by_id(db: AsyncSession, product_id: str):
        result = await db.execute(select(Product).where(Product.id == product_id, Product.is_deleted == False))
        product = result.scalar_one_or_none()
        if not product:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
        return product

    @staticmethod
    async def create_product(db: AsyncSession, data: dict):
        if "storeId" in data and "store_id" not in data:
            data["store_id"] = data.pop("storeId")
        if "inStock" in data and "in_stock" not in data:
            data["in_stock"] = data.pop("inStock")
        if "preparationTimeMinutes" in data and "preparation_time_minutes" not in data:
            data["preparation_time_minutes"] = data.pop("preparationTimeMinutes")

        if "currency" not in data or not data["currency"]:
            data["currency"] = "NGN"

        if "store_id" in data and isinstance(data["store_id"], str):
            try:
                data["store_id"] = uuid.UUID(data["store_id"])
            except Exception:
                pass

        # Strip unmapped string category if not a UUID
        cat = data.pop("category", None)
        if cat and "category_id" not in data:
            try:
                data["category_id"] = uuid.UUID(cat)
            except Exception:
                pass

        product = Product(**data)
        db.add(product)
        await db.commit()
        await db.refresh(product)
        return product

    @staticmethod
    async def update_product(db: AsyncSession, product_id: str, data: dict):
        result = await db.execute(select(Product).where(Product.id == product_id, Product.is_deleted == False))
        product = result.scalar_one_or_none()
        if not product:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
        for k, v in data.items():
            setattr(product, k, v)
        await db.commit()
        await db.refresh(product)
        return product

    @staticmethod
    async def toggle_stock(db: AsyncSession, product_id: str):
        result = await db.execute(select(Product).where(Product.id == product_id, Product.is_deleted == False))
        product = result.scalar_one_or_none()
        if not product:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
        product.in_stock = not product.in_stock
        await db.commit()
        await db.refresh(product)
        return product

    @staticmethod
    async def delete_product(db: AsyncSession, product_id: str):
        result = await db.execute(select(Product).where(Product.id == product_id))
        product = result.scalar_one_or_none()
        if not product:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
        product.is_deleted = True
        await db.commit()
