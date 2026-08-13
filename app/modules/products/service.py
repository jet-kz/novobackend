from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException, status
from app.modules.products.models import Product, ProductCategory
from typing import Optional


class ProductService:
    @staticmethod
    async def get_products(db: AsyncSession, store_id: Optional[str] = None, category_id: Optional[str] = None, in_stock: Optional[bool] = None):
        stmt = select(Product).where(Product.is_deleted == False)
        if store_id:
            stmt = stmt.where(Product.store_id == store_id)
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
            stmt = stmt.where(ProductCategory.store_id == store_id)
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
