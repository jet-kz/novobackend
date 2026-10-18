"""
Image normalisation for uploads.

Every upload is decoded with Pillow (so non-images are rejected), rotated upright from its
EXIF orientation, sized for what it's used for, stripped of metadata (including GPS) and
re-encoded as WebP. A 4 MB phone photo typically ends up at 60-250 KB.
"""
import io
from dataclasses import dataclass

from fastapi import HTTPException, status
from PIL import Image, ImageOps, UnidentifiedImageError

# Refuse decompression bombs (~40 megapixels is plenty for any phone photo).
Image.MAX_IMAGE_PIXELS = 40_000_000

MAX_UPLOAD_BYTES = 15 * 1024 * 1024


@dataclass(frozen=True)
class Preset:
    max_width: int
    max_height: int
    square: bool = False  # center-crop to 1:1 (logos, avatars)
    quality: int = 80


PRESETS = {
    "avatars": Preset(512, 512, square=True),
    "store-logos": Preset(512, 512, square=True),
    "store-banners": Preset(1600, 1000, quality=78),
    "product-images": Preset(1000, 1000),
    # Rider ID documents: keep the whole card legible, never crop.
    "rider-documents": Preset(1600, 1600, quality=85),
}


def process_image(data: bytes, kind: str) -> tuple[bytes, str, str]:
    """Return (bytes, content_type, extension). Raises HTTP 400/413 on bad input."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Image is larger than 15 MB")
    preset = PRESETS.get(kind, PRESETS["product-images"])

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="That file isn't a supported image. Use a JPG, PNG or WebP photo.")

    # Keep animated GIFs as they are (re-encoding would drop the animation).
    if image.format == "GIF" and getattr(image, "is_animated", False):
        return data, "image/gif", "gif"

    image = ImageOps.exif_transpose(image)
    has_alpha = image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info)
    image = image.convert("RGBA" if has_alpha else "RGB")

    if preset.square:
        side = min(image.size)
        image = ImageOps.fit(image, (side, side), method=Image.Resampling.LANCZOS)
    image.thumbnail((preset.max_width, preset.max_height), Image.Resampling.LANCZOS)

    out = io.BytesIO()
    image.save(out, format="WEBP", quality=preset.quality, method=6)
    return out.getvalue(), "image/webp", "webp"
