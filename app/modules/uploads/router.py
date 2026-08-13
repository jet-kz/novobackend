import io
import mimetypes
import uuid
from typing import List
from PIL import Image
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status, Query
from app.core.security import get_current_user
from app.integrations.supabase.client import supabase

router = APIRouter()

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

BUCKET_MAP = {
    "avatars": "avatars",
    "store-logos": "store-assets",
    "store-banners": "store-assets",
    "product-images": "product-images",
}


def optimize_image(
    file_bytes: bytes,
    content_type: str,
    max_dimension: int = 1600,
    quality: int = 80
) -> tuple[bytes, str]:
    """
    Resizes and compresses images using Pillow.
    - Scales down proportionally if width/height exceed max_dimension.
    - Applies quality compression for JPEG/WebP.
    - Preserves format and returns optimized bytes and MIME type.
    """
    try:
        image = Image.open(io.BytesIO(file_bytes))
        
        # Check dimensions and resize if necessary
        width, height = image.size
        if width > max_dimension or height > max_dimension:
            ratio = min(max_dimension / width, max_dimension / height)
            new_size = (int(width * ratio), int(height * ratio))
            try:
                resample = Image.Resampling.LANCZOS
            except AttributeError:
                resample = Image.ANTIALIAS
            image = image.resize(new_size, resample=resample)
        
        img_byte_arr = io.BytesIO()
        
        # Format preservation
        if content_type == "image/jpeg":
            image.save(img_byte_arr, format="JPEG", quality=quality, optimize=True)
        elif content_type == "image/webp":
            image.save(img_byte_arr, format="WEBP", quality=quality, method=6)
        elif content_type == "image/png":
            image.save(img_byte_arr, format="PNG", optimize=True)
        elif content_type == "image/gif":
            return file_bytes, content_type
        else:
            if image.mode != "RGB":
                image = image.convert("RGB")
            image.save(img_byte_arr, format="JPEG", quality=quality, optimize=True)
            content_type = "image/jpeg"
            
        return img_byte_arr.getvalue(), content_type
    except Exception:
        # Fallback to original file on failure
        return file_bytes, content_type


async def handle_upload(
    file: UploadFile,
    bucket: str,
    folder: str,
    user_id: str
) -> dict:
    """
    Helper function to process, compress, and upload a single file to Supabase storage.
    """
    content_type = file.content_type or mimetypes.guess_type(file.filename or "")[0] or ""
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported type '{content_type}'. Use JPEG, PNG, WebP, or GIF."
        )

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File exceeds 10MB limit"
        )

    # Process and compress image
    contents, content_type = optimize_image(contents, content_type)

    ext = (file.filename or "file").rsplit(".", 1)[-1] if "." in (file.filename or "") else "jpg"
    if content_type == "image/jpeg" and ext not in ("jpg", "jpeg"):
        ext = "jpg"
    elif content_type == "image/png" and ext != "png":
        ext = "png"
    elif content_type == "image/webp" and ext != "webp":
        ext = "webp"

    # UUID based uniquely identifying filename to avoid naming conflicts
    unique_id = uuid.uuid4().hex
    storage_bucket = BUCKET_MAP[bucket]
    prefix = f"{folder}/" if folder else ""
    file_path = f"{prefix}{bucket}_{unique_id}.{ext}"

    try:
        supabase.storage.from_(storage_bucket).upload(
            path=file_path,
            file=contents,
            file_options={"content-type": content_type, "upsert": "true"}
        )
        public_url = supabase.storage.from_(storage_bucket).get_public_url(file_path)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Storage upload failed for file '{file.filename}': {str(e)}"
        )

    return {
        "url": public_url,
        "bucket": storage_bucket,
        "path": file_path,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_file(
    bucket: str = Query(..., description="One of: avatars | store-logos | store-banners | product-images"),
    folder: str = Query(default="", description="Optional subfolder path e.g. store_id or product_id"),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    """
    Upload a single file with on-the-fly image optimization and UUID naming.
    """
    if bucket not in BUCKET_MAP:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid bucket. Use one of: {', '.join(BUCKET_MAP.keys())}"
        )

    upload_data = await handle_upload(file, bucket, folder, current_user.get("user_id", "anonymous"))

    return {
        "success": True,
        "message": "File uploaded successfully",
        "data": upload_data
    }


@router.post("/bulk", status_code=status.HTTP_201_CREATED)
async def upload_files_bulk(
    bucket: str = Query(..., description="One of: avatars | store-logos | store-banners | product-images"),
    folder: str = Query(default="", description="Optional subfolder path e.g. store_id or product_id"),
    files: List[UploadFile] = File(...),
    current_user: dict = Depends(get_current_user)
):
    """
    Upload multiple files with on-the-fly image optimization and UUID naming.
    """
    if bucket not in BUCKET_MAP:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid bucket. Use one of: {', '.join(BUCKET_MAP.keys())}"
        )

    uploaded_files = []
    for file in files:
        upload_data = await handle_upload(file, bucket, folder, current_user.get("user_id", "anonymous"))
        uploaded_files.append(upload_data)

    return {
        "success": True,
        "message": f"Successfully uploaded {len(uploaded_files)} file(s)",
        "data": uploaded_files
    }


@router.delete("", status_code=status.HTTP_200_OK)
async def delete_file(
    bucket: str = Query(..., description="One of: avatars | store-logos | store-banners | product-images"),
    path: str = Query(..., description="File path relative to the bucket (e.g. folder/filename.ext)"),
    current_user: dict = Depends(get_current_user)
):
    """
    Delete a file from Supabase Storage.
    """
    if bucket not in BUCKET_MAP:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid bucket. Use one of: {', '.join(BUCKET_MAP.keys())}"
        )

    storage_bucket = BUCKET_MAP[bucket]
    try:
        supabase.storage.from_(storage_bucket).remove([path])
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Storage delete failed: {str(e)}"
        )

    return {
        "success": True,
        "message": "File deleted successfully",
        "data": {
            "bucket": storage_bucket,
            "path": path
        }
    }
