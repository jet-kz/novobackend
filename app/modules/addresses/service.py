from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException, status
from app.modules.addresses.models import Address
from app.core.access import to_uuid

DEFAULT_LOCATION = {"longitude": 3.3792, "latitude": 6.5244}  # Lagos, used when the client sends no coordinates


def serialize_address(a: Address) -> dict:
    loc = a.location if isinstance(a.location, dict) else None
    return {
        "id": str(a.id),
        "label": a.label,
        "title": a.label,
        "address_text": a.address_text,
        "address": a.address_text,
        "location": loc,
        "delivery_instructions": a.delivery_instructions,
        "is_default": bool(a.is_default),
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def _point(loc) -> str:
    try:
        return f"SRID=4326;POINT({float(loc['longitude'])} {float(loc['latitude'])})"
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="location needs numeric longitude and latitude")


def _map_fields(data: dict) -> dict:
    """Accept both the API names (label, address_text) and the frontend names (title, address, city, state)."""
    data = data or {}
    out = {}
    label = data.get("label") or data.get("title")
    if label is not None:
        out["label"] = str(label).strip()[:50] or "Home"
    text = data.get("address_text") or data.get("address")
    if text is not None:
        full = str(text).strip()
        for key in ("city", "state"):
            extra = str(data.get(key) or "").strip()
            if extra and extra.lower() not in full.lower():
                full = f"{full}, {extra}"
        out["address_text"] = full[:255]
    if "delivery_instructions" in data:
        out["delivery_instructions"] = data.get("delivery_instructions")
    if data.get("location"):
        out["location"] = _point(data["location"])
    return out


class AddressService:
    @staticmethod
    async def get_user_addresses(db: AsyncSession, user_id: str):
        result = await db.execute(
            select(Address)
            .where(Address.user_id == user_id, Address.is_deleted == False)
            .order_by(Address.is_default.desc(), Address.created_at.desc())
        )
        return [serialize_address(a) for a in result.scalars().all()]

    @staticmethod
    async def _clear_defaults(db: AsyncSession, user_id: str):
        res = await db.execute(select(Address).where(Address.user_id == user_id, Address.is_deleted == False))
        for addr in res.scalars().all():
            addr.is_default = False

    @staticmethod
    async def create_address(db: AsyncSession, user_id: str, data: dict):
        fields = _map_fields(data)
        if len(fields.get("address_text") or "") < 5:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Please enter a full street address")
        fields.setdefault("label", "Home")
        fields.setdefault("location", _point(DEFAULT_LOCATION))

        existing = await db.execute(select(Address.id).where(Address.user_id == user_id, Address.is_deleted == False))
        make_default = bool((data or {}).get("is_default")) or existing.first() is None
        if make_default:
            await AddressService._clear_defaults(db, user_id)

        address = Address(user_id=user_id, is_default=make_default, **fields)
        db.add(address)
        await db.commit()
        await db.refresh(address)
        return serialize_address(address)

    @staticmethod
    async def _owned(db: AsyncSession, address_id: str, user_id: str) -> Address:
        result = await db.execute(
            select(Address).where(
                Address.id == to_uuid(address_id, "address_id"),
                Address.user_id == user_id,
                Address.is_deleted == False,
            )
        )
        address = result.scalar_one_or_none()
        if not address:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Address not found")
        return address

    @staticmethod
    async def update_address(db: AsyncSession, address_id: str, user_id: str, data: dict):
        address = await AddressService._owned(db, address_id, user_id)
        for k, v in _map_fields(data).items():
            setattr(address, k, v)
        if (data or {}).get("is_default"):
            await AddressService._clear_defaults(db, user_id)
            address.is_default = True
        await db.commit()
        await db.refresh(address)
        return serialize_address(address)

    @staticmethod
    async def set_default(db: AsyncSession, address_id: str, user_id: str):
        address = await AddressService._owned(db, address_id, user_id)
        await AddressService._clear_defaults(db, user_id)
        address.is_default = True
        await db.commit()
        await db.refresh(address)
        return serialize_address(address)

    @staticmethod
    async def delete_address(db: AsyncSession, address_id: str, user_id: str):
        address = await AddressService._owned(db, address_id, user_id)
        address.is_deleted = True
        address.is_default = False
        await db.commit()
