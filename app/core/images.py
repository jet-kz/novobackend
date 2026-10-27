"""
Image normalisation for uploads.

Every upload is decoded with Pillow (so non-images are rejected), rotated upright from its
EXIF orientation, converted to sRGB from its own colour profile (phones shoot in Display P3;
dropping the profile makes food look dull), sized for what it's used for, stripped of other
metadata (including GPS) and re-encoded once as high-quality WebP. Graphics with transparency
(logos) are stored losslessly.

Sizes allow for 2–3x screens: a banner shown full width on a laptop needs ~2400 px to stay sharp.
"""
import io
from dataclasses import dataclass

from fastapi import HTTPException, status
from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError

# Refuse decompression bombs (~50 megapixels is plenty for any phone photo).
Image.MAX_IMAGE_PIXELS = 50_000_000

MAX_UPLOAD_BYTES = 15 * 1024 * 1024


@dataclass(frozen=True)
class Preset:
    max_width: int
    max_height: int
    square: bool = False  # center-crop to 1:1 (logos, avatars)
    quality: int = 90


PRESETS = {
    "avatars": Preset(640, 640, square=True),
    "store-logos": Preset(800, 800, square=True),
    "store-banners": Preset(2400, 1600),
    "promo-banners": Preset(2400, 1600),
    "product-images": Preset(1600, 1600),
    # Rider ID documents: keep the whole card legible, never crop.
    "rider-documents": Preset(2000, 2000, quality=92),
}

_SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
_SRGB_BYTES = _SRGB.tobytes()


def _to_srgb(image: Image.Image) -> Image.Image:
    """Convert from the photo's embedded colour profile (e.g. Display P3) to sRGB."""
    icc = image.info.get("icc_profile")
    if not icc:
        return image
    try:
        src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        mode = "RGBA" if image.mode in ("RGBA", "LA", "PA") else "RGB"
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert(mode)
        return ImageCms.profileToProfile(image, src, _SRGB, outputMode=mode, renderingIntent=ImageCms.Intent.PERCEPTUAL)
    except Exception:
        # Broken or unusual profile: keep the pixels as they are rather than failing the upload.
        return image


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
    has_alpha = image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info)
    image = _to_srgb(image)
    image = image.convert("RGBA" if has_alpha else "RGB")

    if preset.square:
        side = min(image.size)
        image = ImageOps.fit(image, (side, side), method=Image.Resampling.LANCZOS)
    # Only ever shrinks; small images are kept at their own size, never stretched.
    image.thumbnail((preset.max_width, preset.max_height), Image.Resampling.LANCZOS)

    out = io.BytesIO()
    if has_alpha:
        # Logos / graphics: lossless keeps text and edges crisp.
        image.save(out, format="WEBP", lossless=True, quality=100, method=6, icc_profile=_SRGB_BYTES)
    else:
        image.save(out, format="WEBP", quality=preset.quality, method=6, icc_profile=_SRGB_BYTES)
    return out.getvalue(), "image/webp", "webp"
