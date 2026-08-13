from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException, status
from app.modules.users.models import UserProfile


class UserProfileService:
    @staticmethod
    async def get_profile(db: AsyncSession, user_id: str):
        result = await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
        profile = result.scalar_one_or_none()
        if not profile:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
        return profile

    @staticmethod
    async def get_or_create_profile(db: AsyncSession, user_id: str):
        """Auto-creates a blank profile on first access (called at login time)."""
        result = await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
        profile = result.scalar_one_or_none()
        if not profile:
            profile = UserProfile(user_id=user_id)
            db.add(profile)
            await db.commit()
            await db.refresh(profile)
        return profile

    @staticmethod
    async def update_profile(db: AsyncSession, user_id: str, data: dict):
        result = await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
        profile = result.scalar_one_or_none()
        if not profile:
            # Auto-create on first update
            profile = UserProfile(user_id=user_id)
            db.add(profile)
            await db.flush()

        # Only allow safe fields to be updated
        allowed = {"full_name", "phone", "avatar_url"}
        for k, v in data.items():
            if k in allowed:
                setattr(profile, k, v)

        await db.commit()
        await db.refresh(profile)
        return profile

    @staticmethod
    async def deactivate(db: AsyncSession, user_id: str):
        result = await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
        profile = result.scalar_one_or_none()
        if not profile:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
        profile.is_active = False
        await db.commit()
