"""
Create (or update) a platform super admin.

    ADMIN_EMAIL=you@example.com ADMIN_PASSWORD='...' python seed_admin.py

Credentials come from the environment so they never land in the repo. Safe to re-run: an
existing account gets the new password, is marked verified, and gets the admin roles.
"""
import asyncio
import os
import sys

from sqlalchemy import text
from sqlalchemy.future import select

from app.core.database import AsyncSessionLocal
from app.integrations.supabase.client import supabase
from app.modules.auth.models import Role, UserRole
from app.modules.users.models import UserProfile

ROLES = (("role_super_admin", "super_admin"), ("role_admin", "admin"))


async def find_user_id(email: str) -> str | None:
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            text("select id::text from auth.users where lower(email) = lower(:e) and deleted_at is null"), {"e": email}
        )).first()
        return row[0] if row else None


async def seed_admin(email: str, password: str, full_name: str) -> str:
    user_id = await find_user_id(email)
    attrs = {"password": password, "email_confirm": True, "user_metadata": {"full_name": full_name, "role": "super_admin"}}
    if user_id:
        supabase.auth.admin.update_user_by_id(user_id, attrs)
        print(f"Updated existing auth user {user_id}")
    else:
        user_id = supabase.auth.admin.create_user({"email": email, **attrs}).user.id
        print(f"Created auth user {user_id}")

    async with AsyncSessionLocal() as session:
        for role_id, name in ROLES:
            role = (await session.execute(select(Role).where(Role.name == name))).scalar_one_or_none()
            if not role:
                role = Role(id=role_id, name=name)
                session.add(role)
                await session.flush()
            exists = (await session.execute(
                select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role.id)
            )).scalar_one_or_none()
            if not exists:
                session.add(UserRole(user_id=user_id, role_id=role.id))

        profile = (await session.execute(select(UserProfile).where(UserProfile.user_id == user_id))).scalar_one_or_none()
        if not profile:
            session.add(UserProfile(user_id=user_id, full_name=full_name, is_active=True))
        else:
            profile.full_name = profile.full_name or full_name
            profile.is_active = True
        await session.commit()
    return user_id


if __name__ == "__main__":
    email = os.getenv("ADMIN_EMAIL", "").strip()
    password = os.getenv("ADMIN_PASSWORD", "")
    if not email or len(password) < 8:
        sys.exit("Set ADMIN_EMAIL and ADMIN_PASSWORD (8+ characters).")
    uid = asyncio.run(seed_admin(email, password, os.getenv("ADMIN_NAME", "Novo Admin")))
    print(f"Super admin ready: {email} ({uid})")
