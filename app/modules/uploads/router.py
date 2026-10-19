import asyncio
import uuid
from typing import List

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import assert_store_access, get_owned_store_ids, is_admin
from app.core.database import get_db
from app.core.images import process_image
from app.core.security import get_current_user
from app.integrations.supabase.client import supabase

router = APIRouter()

BUCKET_MAP = {
    "avatars": "avatars",
    "store-logos": "store-assets",
    "store-banners": "store-assets",
    "product-images": "product-images",
    "rider-documents": "rider-documents",
    "promo-banners": "store-assets",
}
# Platform-wide artwork only admins may upload.
ADMIN_BUCKETS = {"promo-banners"}
STORE_BUCKETS = {"store-logos", "store-banners", "product-images"}
# Not publicly readable; served through short-lived signed links (see signed_url).
PRIVATE_BUCKETS = {"rider-documents"}
SIGNED_URL_SECONDS = 3600
MAX_BULK_FILES = 10


def _check_bucket(bucket: str) -> None:
    if bucket not in BUCKET_MAP:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid bucket. Use one of: {', '.join(BUCKET_MAP.keys())}",
        )


async def _resolve_folder(db: AsyncSession, bucket: str, folder: str, user: dict) -> str:
    """Store images live under the store's id (owner or admin only); everything else under the user's id."""
    folder = (folder or "").strip().strip("/")
    if bucket in STORE_BUCKETS and folder:
        await assert_store_access(db, folder, user)
        return folder
    return str(user["user_id"])


def _store(storage_bucket: str, path: str, data: bytes, content_type: str) -> str:
    bucket = supabase.storage.from_(storage_bucket)
    bucket.upload(
        path=path,
        file=data,
        file_options={"content-type": content_type, "upsert": "true", "cache-control": "31536000"},
    )
    if storage_bucket in PRIVATE_BUCKETS:
        return signed_url(storage_bucket, path) or ""
    return bucket.get_public_url(path)


def signed_url(storage_bucket: str, path: str | None) -> str | None:
    """Temporary link to a private file (e.g. a rider's ID for the admin reviewing it)."""
    if not path:
        return None
    try:
        return supabase.storage.from_(storage_bucket).create_signed_url(path, SIGNED_URL_SECONDS).get("signedURL")
    except Exception:
        return None


async def handle_upload(file: UploadFile, bucket: str, folder: str) -> dict:
    """Normalise one image (orientation, size, WebP) and put it in Supabase Storage."""
    raw = await file.read()
    data, content_type, ext = await asyncio.to_thread(process_image, raw, bucket)

    storage_bucket = BUCKET_MAP[bucket]
    file_path = f"{folder}/{bucket}_{uuid.uuid4().hex}.{ext}"
    try:
        public_url = await asyncio.to_thread(_store, storage_bucket, file_path, data, content_type)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Couldn't save '{file.filename}' to storage. Please try again. ({e})",
        )
    return {"url": public_url, "bucket": storage_bucket, "path": file_path, "size": len(data)}


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_file(
    bucket: str = Query(..., description="One of: avatars | store-logos | store-banners | product-images"),
    folder: str = Query(default="", description="Store id for store images; ignored for avatars"),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Upload one image. It is rotated upright, resized for its use and saved as WebP."""
    _check_bucket(bucket)
    if bucket in ADMIN_BUCKETS and not is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can upload banners")
    target = "banners" if bucket in ADMIN_BUCKETS else await _resolve_folder(db, bucket, folder, current_user)
    upload_data = await handle_upload(file, bucket, target)
    return {"success": True, "message": "File uploaded successfully", "data": upload_data}


@router.post("/bulk", status_code=status.HTTP_201_CREATED)
async def upload_files_bulk(
    bucket: str = Query(..., description="One of: avatars | store-logos | store-banners | product-images"),
    folder: str = Query(default="", description="Store id for store images; ignored for avatars"),
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Upload up to 10 images with the same processing as the single upload."""
    _check_bucket(bucket)
    if bucket in ADMIN_BUCKETS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Upload banners one at a time")
    if len(files) > MAX_BULK_FILES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Upload at most {MAX_BULK_FILES} images at once")
    target = await _resolve_folder(db, bucket, folder, current_user)
    uploaded_files = [await handle_upload(f, bucket, target) for f in files]
    return {
        "success": True,
        "message": f"Successfully uploaded {len(uploaded_files)} file(s)",
        "data": uploaded_files,
    }


@router.delete("", status_code=status.HTTP_200_OK)
async def delete_file(
    bucket: str = Query(..., description="One of: avatars | store-logos | store-banners | product-images"),
    path: str = Query(..., description="File path relative to the bucket (e.g. folder/filename.ext)"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Delete an image. Allowed for admins, or for files under your own user id or a store you own."""
    _check_bucket(bucket)
    owner_folder = path.strip("/").split("/", 1)[0]
    if ".." in path or not owner_folder:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid path")
    if not is_admin(current_user) and owner_folder != str(current_user["user_id"]):
        owned = {str(sid) for sid in await get_owned_store_ids(db, current_user["user_id"])}
        if owner_folder not in owned:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can't delete this file")

    storage_bucket = BUCKET_MAP[bucket]
    try:
        await asyncio.to_thread(supabase.storage.from_(storage_bucket).remove, [path])
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Storage delete failed: {e}")
    return {"success": True, "message": "File deleted successfully", "data": {"bucket": storage_bucket, "path": path}}


def ensure_buckets() -> None:
    """Create the public image buckets if they don't exist yet (idempotent; runs at startup)."""
    existing = {b.name for b in supabase.storage.list_buckets()}
    for name in sorted(set(BUCKET_MAP.values()) - existing):
        supabase.storage.create_bucket(
            name,
            options={
                "public": name not in PRIVATE_BUCKETS,
                "file_size_limit": 5 * 1024 * 1024,  # processed images are far smaller than this
                "allowed_mime_types": ["image/webp", "image/gif", "image/jpeg", "image/png"],
            },
        )
