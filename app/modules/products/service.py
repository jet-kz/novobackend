from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, update
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, status
from app.modules.products.models import Product, ProductCategory
from app.core.serializers import model_to_dict
from typing import Optional
import re
import uuid

PRODUCT_COLUMNS = set(Product.__table__.columns.keys())


def serialize_product(product: Product) -> dict:
    data = model_to_dict(product)
    category_name = None
    try:
        if product.category:
            category_name = product.category.name
    except Exception:
        category_name = None
    data["store_id"] = str(product.store_id) if product.store_id else None
    data["storeId"] = data["store_id"]
    data["category"] = category_name
    data["inStock"] = bool(product.in_stock)
    data["proteinOptions"] = product.protein_options or []
    data["extrasOptions"] = product.extras_options or []
    data["optionGroups"] = product.option_groups or []
    data["preparationTimeMinutes"] = product.preparation_time_minutes
    return data


PROTECTED_PRODUCT_FIELDS = {"id", "store_id", "is_deleted", "created_at", "rating"}


def _validate_price(payload: dict) -> None:
    if "price" not in payload:
        return
    try:
        price = float(payload["price"])
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Price must be a number")
    if price < 0 or price > 10_000_000:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Price must be between 0 and 10,000,000")
    payload["price"] = round(price, 2)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug or "general"


class ProductService:
    @staticmethod
    async def get_products(db: AsyncSession, store_id: Optional[str] = None, category_id: Optional[str] = None, in_stock: Optional[bool] = None):
        stmt = select(Product).options(selectinload(Product.category)).where(Product.is_deleted == False)
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
        return [serialize_product(p) for p in result.scalars().all()]

    @staticmethod
    async def get_categories(db: AsyncSession, store_id: Optional[str] = None):
        stmt = select(ProductCategory).where(ProductCategory.is_deleted == False)
        if store_id:
            try:
                target_uuid = uuid.UUID(store_id) if isinstance(store_id, str) else store_id
                stmt = stmt.where(ProductCategory.store_id == target_uuid)
            except Exception:
                return []
        stmt = stmt.order_by(ProductCategory.display_order, ProductCategory.name)
        result = await db.execute(stmt)
        return [model_to_dict(c) for c in result.scalars().all()]

    @staticmethod
    async def get_or_create_category(db: AsyncSession, store_id, name: str):
        name = name.strip()[:100]
        slug = _slugify(name)
        # (store_id, slug) is unique even for deleted rows, so bring a deleted section back instead.
        existing = await db.execute(
            select(ProductCategory).where(ProductCategory.store_id == store_id, ProductCategory.slug == slug)
        )
        category = existing.scalar_one_or_none()
        if category:
            if category.is_deleted:
                category.is_deleted = False
                category.name = name
            return category
        count = await db.execute(
            select(func.count()).select_from(ProductCategory).where(
                ProductCategory.store_id == store_id, ProductCategory.is_deleted == False
            )
        )
        category = ProductCategory(store_id=store_id, name=name, slug=slug, display_order=int(count.scalar() or 0) + 1)
        db.add(category)
        await db.flush()
        return category

    # ── Menu sections (per-store categories) ─────────────────────────────────

    @staticmethod
    async def _section(db: AsyncSession, section_id: str) -> ProductCategory:
        try:
            sid = uuid.UUID(str(section_id))
        except ValueError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Section not found")
        section = await db.get(ProductCategory, sid)
        if not section or section.is_deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Section not found")
        return section

    @staticmethod
    async def create_section(db: AsyncSession, store_id, name: str) -> dict:
        if not (name or "").strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Section name is required")
        section = await ProductService.get_or_create_category(db, store_id, name)
        await db.commit()
        return model_to_dict(section)

    @staticmethod
    async def rename_section(db: AsyncSession, section: ProductCategory, name: str) -> dict:
        name = (name or "").strip()[:100]
        if not name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Section name is required")
        clash = await db.execute(
            select(ProductCategory).where(
                ProductCategory.store_id == section.store_id,
                ProductCategory.slug == _slugify(name),
                ProductCategory.id != section.id,
            )
        )
        if clash.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You already have a section with that name")
        section.name, section.slug = name, _slugify(name)
        await db.commit()
        return model_to_dict(section)

    @staticmethod
    async def delete_section(db: AsyncSession, section: ProductCategory) -> None:
        """Soft-delete; its items stay on the menu without a section."""
        await db.execute(update(Product).where(Product.category_id == section.id).values(category_id=None))
        section.is_deleted = True
        await db.commit()

    @staticmethod
    async def reorder_sections(db: AsyncSession, store_id, ordered_ids: list) -> list:
        res = await db.execute(
            select(ProductCategory).where(ProductCategory.store_id == store_id, ProductCategory.is_deleted == False)
        )
        by_id = {str(c.id): c for c in res.scalars().all()}
        for position, sid in enumerate(ordered_ids or [], start=1):
            if str(sid) in by_id:
                by_id[str(sid)].display_order = position
        await db.commit()
        return await ProductService.get_categories(db, store_id=str(store_id))

    @staticmethod
    async def get_store_id(db: AsyncSession, product_id: str):
        try:
            pid = uuid.UUID(str(product_id))
        except ValueError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
        res = await db.execute(select(Product.store_id).where(Product.id == pid, Product.is_deleted == False))
        store_id = res.scalar_one_or_none()
        if store_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
        return store_id

    @staticmethod
    async def get_by_id(db: AsyncSession, product_id: str):
        try:
            target_uuid = uuid.UUID(product_id) if isinstance(product_id, str) else product_id
        except Exception:
            target_uuid = product_id
        result = await db.execute(
            select(Product).options(selectinload(Product.category)).where(Product.id == target_uuid, Product.is_deleted == False)
        )
        product = result.scalar_one_or_none()
        if not product:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
        return serialize_product(product)

    @staticmethod
    def _map_product_payload(data: dict) -> dict:
        payload = dict(data or {})
        mapping = {
            "storeId": "store_id",
            "inStock": "in_stock",
            "preparationTimeMinutes": "preparation_time_minutes",
            "proteinOptions": "protein_options",
            "extrasOptions": "extras_options",
            "optionGroups": "option_groups",
        }
        for camel, snake in mapping.items():
            if camel in payload and snake not in payload:
                payload[snake] = payload.pop(camel)
            else:
                payload.pop(camel, None)
        return payload

    @staticmethod
    async def create_product(db: AsyncSession, data: dict):
        payload = ProductService._map_product_payload(data)
        if not payload.get("currency"):
            payload["currency"] = "NGN"

        if payload.get("store_id") and isinstance(payload["store_id"], str):
            try:
                payload["store_id"] = uuid.UUID(payload["store_id"])
            except Exception:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid store_id")

        cat = payload.pop("category", None)
        if cat and "category_id" not in payload and payload.get("store_id"):
            try:
                payload["category_id"] = uuid.UUID(str(cat))
            except Exception:
                category = await ProductService.get_or_create_category(db, payload["store_id"], str(cat))
                payload["category_id"] = category.id

        pid = payload.get("id")
        if pid and isinstance(pid, str):
            try:
                payload["id"] = uuid.UUID(pid)
            except Exception:
                payload.pop("id", None)

        for key in list(payload.keys()):
            if key not in PRODUCT_COLUMNS:
                payload.pop(key, None)

        if not payload.get("store_id"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="store_id is required")
        if not payload.get("name"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Product name is required")
        if payload.get("price") is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Product price is required")
        _validate_price(payload)
        payload.pop("is_deleted", None)
        payload.pop("rating", None)

        product = Product(**payload)
        db.add(product)
        await db.commit()
        result = await db.execute(
            select(Product).options(selectinload(Product.category)).where(Product.id == product.id)
        )
        return serialize_product(result.scalar_one())

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

        payload = ProductService._map_product_payload(data)
        cat = payload.pop("category", None)
        if cat and product.store_id:
            try:
                payload["category_id"] = uuid.UUID(str(cat))
            except Exception:
                category = await ProductService.get_or_create_category(db, product.store_id, str(cat))
                payload["category_id"] = category.id

        _validate_price(payload)
        if "name" in payload and not str(payload["name"] or "").strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Product name cannot be empty")
        for k, v in payload.items():
            if k in PRODUCT_COLUMNS and k not in PROTECTED_PRODUCT_FIELDS:
                setattr(product, k, v)

        await db.commit()
        result = await db.execute(
            select(Product).options(selectinload(Product.category)).where(Product.id == product.id)
        )
        return serialize_product(result.scalar_one())

    @staticmethod
    async def toggle_stock(db: AsyncSession, product_id: str):
        try:
            target_uuid = uuid.UUID(product_id) if isinstance(product_id, str) else product_id
        except Exception:
            target_uuid = product_id
        result = await db.execute(select(Product).where(Product.id == target_uuid, Product.is_deleted == False))
        product = result.scalar_one_or_none()
        if not product:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
        product.in_stock = not product.in_stock
        await db.commit()
        result = await db.execute(
            select(Product).options(selectinload(Product.category)).where(Product.id == product.id)
        )
        return serialize_product(result.scalar_one())

    @staticmethod
    async def delete_product(db: AsyncSession, product_id: str):
        try:
            target_uuid = uuid.UUID(product_id) if isinstance(product_id, str) else product_id
        except Exception:
            target_uuid = product_id
        result = await db.execute(select(Product).where(Product.id == target_uuid))
        product = result.scalar_one_or_none()
        if not product:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
        product.is_deleted = True
        await db.commit()
