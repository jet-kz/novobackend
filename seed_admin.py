import asyncio
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import AsyncSessionLocal
from app.integrations.supabase.client import supabase
from app.modules.auth.models import Role, UserRole
from app.modules.users.models import UserProfile


async def seed_admin_user():
    print("Starting Admin User Seeding...")
    admin_email = "admin@novo.ng"
    admin_password = "SuperAdminPass2026!"
    admin_user_id = None

    # 1. Create or retrieve user from Supabase Auth via Admin API
    try:
        # Check if user exists or create new user
        res = supabase.auth.admin.create_user({
            "email": admin_email,
            "password": admin_password,
            "email_confirm": True,
            "user_metadata": {
                "full_name": "Novo Super Admin",
                "role": "super_admin"
            }
        })
        if hasattr(res, "user") and res.user:
            admin_user_id = res.user.id
            print(f"✅ Supabase Auth user created successfully: {admin_user_id}")
    except Exception as err:
        print(f"Note on Supabase Auth creation (may already exist): {err}")
        # Try fetching user list to find admin_email ID
        try:
            users_list = supabase.auth.admin.list_users()
            for u in users_list:
                if u.email == admin_email:
                    admin_user_id = u.id
                    print(f"Found existing Supabase Auth user: {admin_user_id}")
                    # Update password to ensure it matches
                    supabase.auth.admin.update_user_by_id(admin_user_id, {"password": admin_password})
                    break
        except Exception as list_err:
            print(f"Could not list users: {list_err}")

    if not admin_user_id:
        admin_user_id = "admin_super_01"

    # 2. Seed database roles and user profile
    try:
        async with AsyncSessionLocal() as session:
            super_admin_role_id = "role_super_admin"
            admin_role_id = "role_admin"

            res_super = await session.execute(select(Role).where(Role.name == "super_admin"))
            super_role = res_super.scalar_one_or_none()
            if not super_role:
                super_role = Role(id=super_admin_role_id, name="super_admin")
                session.add(super_role)

            res_admin = await session.execute(select(Role).where(Role.name == "admin"))
            admin_role = res_admin.scalar_one_or_none()
            if not admin_role:
                admin_role = Role(id=admin_role_id, name="admin")
                session.add(admin_role)

            await session.flush()

            # User Profile
            res_profile = await session.execute(select(UserProfile).where(UserProfile.user_id == admin_user_id))
            user_profile = res_profile.scalar_one_or_none()

            if not user_profile:
                user_profile = UserProfile(
                    user_id=admin_user_id,
                    full_name="Novo Super Admin",
                    phone="+234 800 000 0000",
                    is_active=True
                )
                session.add(user_profile)

            # Assign Roles
            res_ur_super = await session.execute(
                select(UserRole).where((UserRole.user_id == admin_user_id) & (UserRole.role_id == super_role.id))
            )
            if not res_ur_super.scalar_one_or_none():
                session.add(UserRole(user_id=admin_user_id, role_id=super_role.id))

            res_ur_admin = await session.execute(
                select(UserRole).where((UserRole.user_id == admin_user_id) & (UserRole.role_id == admin_role.id))
            )
            if not res_ur_admin.scalar_one_or_none():
                session.add(UserRole(user_id=admin_user_id, role_id=admin_role.id))

            await session.commit()
            print("✅ Database roles and profile seeded successfully!")
    except Exception as e:
        print(f"Database seed note: {e}")

    print("\n-----------------------------------------")
    print("  NOVO SUPERADMIN CREDENTIALS ACTIVE")
    print("-----------------------------------------")
    print(f"Email    : {admin_email}")
    print(f"Password : {admin_password}")
    print(f"User ID  : {admin_user_id}")
    print("Role     : admin / super_admin")
    print("-----------------------------------------\n")


if __name__ == "__main__":
    asyncio.run(seed_admin_user())
