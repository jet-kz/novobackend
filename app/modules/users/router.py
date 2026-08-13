import uuid
import mimetypes
from fastapi import APIRouter, Depends, status, Path, Body, UploadFile, File, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import get_current_user
from app.modules.users.service import UserProfileService
from app.integrations.supabase.client import supabase

router = APIRouter()

# ─── Supabase Storage bucket name ────────────────────────────────────────────
AVATARS_BUCKET = "avatars"


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
    """
    Upload a new profile avatar image to Supabase Storage.
    Accepted: image/jpeg, image/png, image/webp. Max recommended: 5MB.
    Returns the public URL of the uploaded avatar.
    """
    ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
    content_type = file.content_type or mimetypes.guess_type(file.filename or "")[0] or ""
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported file type: {content_type}. Use JPEG, PNG, or WebP.")

    ext = file.filename.rsplit(".", 1)[-1] if file.filename and "." in file.filename else "jpg"
    file_path = f"{current_user['user_id']}/avatar.{ext}"

    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024:  # 5 MB limit
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File exceeds 5MB limit")

    # Upload to Supabase Storage (upsert = replace existing)
    try:
        supabase.storage.from_(AVATARS_BUCKET).upload(
            path=file_path,
            file=contents,
            file_options={"content-type": content_type, "upsert": "true"}
        )
        public_url = supabase.storage.from_(AVATARS_BUCKET).get_public_url(file_path)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Upload failed: {str(e)}")

    # Save URL back to profile
    profile = await UserProfileService.update_profile(db, current_user["user_id"], {"avatar_url": public_url})
    return {"success": True, "message": "Avatar uploaded successfully", "data": {"avatar_url": public_url}}


@router.delete("/me", status_code=status.HTTP_200_OK)
async def deactivate_account(db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Deactivate the current user's account. Reversible by admin."""
    await UserProfileService.deactivate(db, current_user["user_id"])
    return {"success": True, "message": "Account deactivated", "data": None}
