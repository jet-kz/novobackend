"""Upload image normalisation: orientation, sizing, format, rejection of non-images."""
import io
import unittest

from fastapi import HTTPException
from PIL import Image

from app.core.images import process_image


def _jpeg(width, height, orientation=None) -> bytes:
    img = Image.new("RGB", (width, height), (200, 80, 40))
    buf = io.BytesIO()
    if orientation:
        exif = Image.Exif()
        exif[0x0112] = orientation
        img.save(buf, format="JPEG", exif=exif)
    else:
        img.save(buf, format="JPEG")
    return buf.getvalue()


def _open(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


class ProcessImageTests(unittest.TestCase):
    def test_large_photo_is_capped_and_webp(self):
        data, ctype, ext = process_image(_jpeg(4000, 3000), "product-images")
        self.assertEqual((ctype, ext), ("image/webp", "webp"))
        self.assertEqual(_open(data).size, (1000, 750))

    def test_logo_is_cropped_square(self):
        data, _, _ = process_image(_jpeg(1200, 800), "store-logos")
        self.assertEqual(_open(data).size, (512, 512))

    def test_exif_rotation_applied(self):
        # Orientation 6 = rotate 90°: a 400x300 sensor image should come out portrait.
        data, _, _ = process_image(_jpeg(400, 300, orientation=6), "product-images")
        self.assertEqual(_open(data).size, (300, 400))

    def test_small_image_not_upscaled(self):
        data, _, _ = process_image(_jpeg(300, 200), "store-banners")
        self.assertEqual(_open(data).size, (300, 200))

    def test_png_transparency_kept(self):
        buf = io.BytesIO()
        Image.new("RGBA", (64, 64), (0, 0, 0, 0)).save(buf, format="PNG")
        data, _, _ = process_image(buf.getvalue(), "store-logos")
        self.assertIn(_open(data).mode, ("RGBA", "LA"))

    def test_non_image_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            process_image(b"%PDF-1.4 not an image", "product-images")
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
