from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException, status
from app.modules.addresses.models import Address
import uuid

class AddressService:
    @staticmethod
    async def get_user_addresses(db: AsyncSession, user_id: str):
        result = await db.execute(
            select(Address).where(Address.user_id == user_id, Address.is_deleted == False)
        )
        return result.scalars().all()

    @staticmethod
    async def create_address(db: AsyncSession, user_id: str, data: dict):
        data["user_id"] = user_id
        # location must be passed as {"longitude": x, "latitude": y}
        loc = data.pop("location", None)
        if loc:
            data["location"] = f"SRID=4326;POINT({loc['longitude']} {loc['latitude']})"
        address = Address(**data)
        db.add(address)
        await db.commit()
        await db.refresh(address)
        return address

    @staticmethod
    async def update_address(db: AsyncSession, address_id: str, user_id: str, data: dict):
        result = await db.execute(
            select(Address).where(Address.id == address_id, Address.user_id == user_id, Address.is_deleted == False)
        )
        address = result.scalar_one_or_none()
        if not address:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Address not found")
        loc = data.pop("location", None)
        if loc:
            data["location"] = f"SRID=4326;POINT({loc['longitude']} {loc['latitude']})"
        for k, v in data.items():
            setattr(address, k, v)
        await db.commit()
        await db.refresh(address)
        return address

    @staticmethod
    async def set_default(db: AsyncSession, address_id: str, user_id: str):
        # First reset all defaults for user
        all_result = await db.execute(select(Address).where(Address.user_id == user_id, Address.is_deleted == False))
        for addr in all_result.scalars().all():
            addr.is_default = (str(addr.id) == address_id)
        await db.commit()
        result = await db.execute(select(Address).where(Address.id == address_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def delete_address(db: AsyncSession, address_id: str, user_id: str):
        result = await db.execute(
            select(Address).where(Address.id == address_id, Address.user_id == user_id)
        )
        address = result.scalar_one_or_none()
        if not address:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Address not found")
        address.is_deleted = True
        await db.commit()
