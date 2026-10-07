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
        if "proteinOptions" in data and "protein_options" not in data:
            data["protein_options"] = data.pop("proteinOptions")
        if "extrasOptions" in data and "extras_options" not in data:
            data["extras_options"] = data.pop("extrasOptions")
        if "optionGroups" in data and "option_groups" not in data:
            data["option_groups"] = data.pop("optionGroups")

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

        # If id is provided and is string, convert or strip if empty
        pid = data.get("id")
        if pid and isinstance(pid, str):
            try:
                data["id"] = uuid.UUID(pid)
            except Exception:
                data.pop("id", None)

        product = Product(**data)
        db.add(product)
        await db.commit()
        await db.refresh(product)
        return product

    @staticmethod
    async def update_product(db: AsyncSession, product_id: str, data: dict):
        try:
            target_uuid = uuid.UUID(product_id) if isinstance(product_id, str) else product_id
        except Exception:
            target_uuid = product_id

        result = await db.execute(select(Product).where(Product.id == target_uuid, Product.is_deleted == False))
        product = result.scalar_one_or_none()
        if not product:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

        # Map camelCase to snake_case
        field_mapping = {
            "storeId": "store_id",
            "inStock": "in_stock",
            "preparationTimeMinutes": "preparation_time_minutes",
            "proteinOptions": "protein_options",
            "extrasOptions": "extras_options",
            "optionGroups": "option_groups",
        }
        for camel, snake in field_mapping.items():
            if camel in data:
                data[snake] = data.pop(camel)

        valid_columns = Product.__table__.columns.keys()
        for k, v in data.items():
            if k in valid_columns:
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
