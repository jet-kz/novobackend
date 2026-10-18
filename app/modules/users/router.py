import asyncio
import uuid
from fastapi import APIRouter, Depends, status, Path, Body, UploadFile, File, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from sqlalchemy.future import select
from app.core.security import get_current_user, require_role, primary_role
from app.modules.users.service import UserProfileService
from app.modules.auth.models import Role, UserRole
from app.core.images import process_image
from app.modules.uploads.router import _store

router = APIRouter()

# ─── Supabase Storage bucket name ────────────────────────────────────────────
AVATARS_BUCKET = "avatars"


@router.get("", status_code=status.HTTP_200_OK)
async def list_users(db: AsyncSession = Depends(get_db), current_user: dict = Depends(require_role("admin"))):
    """Admin: list application user profiles and roles."""
    profiles = await UserProfileService.list_profiles(db)
    roles_res = await db.execute(select(UserRole, Role).join(Role, Role.id == UserRole.role_id))
    role_map: dict[str, list[str]] = {}
    for user_role, role in roles_res.all():
        role_map.setdefault(user_role.user_id, []).append(role.name)

    data = []
    for profile in profiles:
        roles = role_map.get(profile.user_id) or ["customer"]
        data.append({
            "id": profile.user_id,
            "name": profile.full_name or "",
            "email": "",
            "phone": profile.phone or "",
            "role": primary_role(roles),
            "createdAt": profile.created_at.isoformat() if profile.created_at else None,
            "is_active": profile.is_active,
        })
    return {"success": True, "message": "Users retrieved", "data": data}


@router.get("/me", status_code=status.HTTP_200_OK)
async def get_my_profile(db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get the current authenticated user's profile."""
    profile = await UserProfileService.get_or_create_profile(db, current_user["user_id"])
    return {
        "success": True,
        "message": "Profile retrieved",
        "data": {
            "user_id": profile.user_id,
            "email": current_user.get("email"),        # From JWT
            "full_name": profile.full_name,
            "phone": profile.phone,
            "avatar_url": profile.avatar_url,
            "is_active": profile.is_active,
            "roles": current_user.get("roles", []),
        }
    }


@router.put("/me", status_code=status.HTTP_200_OK)
async def update_my_profile(
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Update profile details: full_name, phone.
    avatar_url is set automatically by the upload endpoint.
    """
    profile = await UserProfileService.update_profile(db, current_user["user_id"], payload)
    return {"success": True, "message": "Profile updated", "data": profile}


@router.post("/me/avatar", status_code=status.HTTP_200_OK)
async def upload_avatar(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Upload a profile photo. It is rotated upright, cropped square, resized and saved as WebP."""
    contents = await file.read()
    data, content_type, ext = await asyncio.to_thread(process_image, contents, "avatars")
    # New name per upload so browsers and the CDN don't keep showing the old photo.
    file_path = f"{current_user['user_id']}/avatar_{uuid.uuid4().hex[:8]}.{ext}"
    try:
        public_url = await asyncio.to_thread(_store, AVATARS_BUCKET, file_path, data, content_type)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Upload failed: {str(e)}")

    # Save URL back to profile
    profile = await UserProfileService.update_profile(db, current_user["user_id"], {"avatar_url": public_url})
    return {"success": True, "message": "Avatar uploaded successfully", "data": {"avatar_url": public_url}}


@router.delete("/me", status_code=status.HTTP_200_OK)
async def deactivate_account(db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Deactivate the current user's account. Reversible by admin."""
    await UserProfileService.deactivate(db, current_user["user_id"])
    return {"success": True, "message": "Account deactivated", "data": None}
