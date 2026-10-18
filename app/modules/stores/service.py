import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException, status
from app.modules.stores.models import Store
from typing import Optional
from app.modules.notifications import service as notify


class StoreService:
    @staticmethod
    async def get_all_stores(db: AsyncSession, store_type: Optional[str] = None, is_open: Optional[bool] = None, public: bool = True):
        stmt = select(Store).where(Store.is_deleted == False)
        if public:
            # Customers only see approved stores whose merchant is active.
            from app.modules.merchants.models import Merchant

            stmt = stmt.join(Merchant, Merchant.id == Store.merchant_id).where(
                Store.is_verified == True, Merchant.status == "active", Merchant.is_deleted == False
            )
        if store_type:
            stmt = stmt.where(Store.store_type == store_type)
        if is_open is not None:
            stmt = stmt.where(Store.is_open == is_open)
        result = await db.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def get_by_id(db: AsyncSession, store_id: str):
        try:
            sid = uuid.UUID(str(store_id))
        except ValueError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found")
        result = await db.execute(select(Store).where(Store.id == sid, Store.is_deleted == False))
        store = result.scalar_one_or_none()
        if not store:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found")
        return store

    @staticmethod
    async def create_store(db: AsyncSession, data: dict, merchant_id):
        data = dict(data or {})
        data.pop("merchantId", None)
        for protected in ("id", "is_verified", "isVerified", "is_deleted", "status"):
            data.pop(protected, None)
        data["merchant_id"] = merchant_id
        if not str(data.get("name") or "").strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Store name is required")
        if "category" in data and "store_type" not in data:
            data["store_type"] = data.pop("category")
        if "store_type" not in data:
            data["store_type"] = "restaurant"

        settings = dict(data.pop("settings", None) or {})
        for camel, snake in {"deliveryFee": "delivery_fee", "minOrder": "min_order", "deliveryTime": "delivery_time"}.items():
            if camel in data:
                settings[snake] = data.pop(camel)

        if "slug" not in data and "name" in data:
            import re
            base_slug = re.sub(r'[^a-z0-9]+', '-', data["name"].lower()).strip('-')
            data["slug"] = f"{base_slug}-{uuid.uuid4().hex[:6]}"

        loc = data.pop("location", None)
        if loc and isinstance(loc, dict):
            data["location"] = f"SRID=4326;POINT({loc.get('longitude', 3.3792)} {loc.get('latitude', 6.5244)})"
        else:
            data["location"] = "SRID=4326;POINT(3.3792 6.5244)"

        columns = set(Store.__table__.columns.keys())
        for k in list(data.keys()):
            if k not in columns:
                value = data.pop(k)
                if isinstance(k, str) and len(k) <= 50:
                    settings[k] = value
        data["settings"] = settings or None
        store = Store(**data)
        db.add(store)
        await db.commit()
        await db.refresh(store)
        return store

    @staticmethod
    async def update_store(db: AsyncSession, store: Store, data: dict):
        """Apply an owner/admin edit. Protected fields (owner, verification, deletion) are ignored here."""
        data = dict(data or {})
        for protected in ("id", "merchant_id", "merchantId", "is_verified", "isVerified", "is_deleted", "slug", "created_at", "status"):
            data.pop(protected, None)

        loc = data.pop("location", None)
        if loc and isinstance(loc, dict):
            try:
                data["location"] = f"SRID=4326;POINT({float(loc['longitude'])} {float(loc['latitude'])})"
            except (KeyError, TypeError, ValueError):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="location needs numeric longitude and latitude")

        if "category" in data and "store_type" not in data:
            data["store_type"] = data.pop("category")
        if "isOpening" in data and "is_open" not in data:
            data["is_open"] = bool(data.pop("isOpening"))

        custom_settings = data.pop("settings", {}) or {}
        camel_settings = {"deliveryFee": "delivery_fee", "minOrder": "min_order", "deliveryTime": "delivery_time"}
        for camel, snake in camel_settings.items():
            if camel in data:
                custom_settings[snake] = data.pop(camel)

        valid_columns = Store.__table__.columns.keys()
        for k, v in list(data.items()):
            if k in valid_columns:
                setattr(store, k, v)
            elif isinstance(k, str) and len(k) <= 50:
                custom_settings[k] = v

        if custom_settings:
            merged = dict(store.settings or {}) if isinstance(store.settings, dict) else {}
            merged.update(custom_settings)
            store.settings = merged

        if "name" in data and store.merchant_id:
            from app.modules.merchants.models import Merchant
            merch = await db.get(Merchant, store.merchant_id)
            if merch:
                merch.name = store.name

        await db.commit()
        await db.refresh(store)
        return store

    @staticmethod
    async def toggle_open(db: AsyncSession, store: Store):
        store.is_open = not store.is_open
        await db.commit()
        await db.refresh(store)
        return store

    @staticmethod
    async def delete_store(db: AsyncSession, store: Store):
        store.is_deleted = True
        await db.commit()

    @staticmethod
    async def set_verified(db: AsyncSession, store: Store, verified: bool):
        changed = bool(store.is_verified) != bool(verified)
        store.is_verified = bool(verified)
        await db.commit()
        await db.refresh(store)
        if changed:
            notify.store_verification_changed(store.id, bool(verified))
        return store
