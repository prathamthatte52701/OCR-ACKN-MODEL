"""Pixel-size guard for uploads. Reads headers only - never decodes pixels.

A 14000x14000 plain PNG is ~0.2 MB on disk but ~900 MB decoded, so the 5 MB
byte limit alone cannot protect memory. One MAX_PIXELS is used everywhere.
"""

import asyncio
import io
import math
import re
import warnings

import fitz  # PyMuPDF
from PIL import Image

MAX_PIXELS = 50_000_000
# Must match preprocessing.PDF_RENDER_SCALE (asserted in test_image_limits.py);
# duplicated here so core/ does not import from features/.
PDF_RENDER_SCALE = 2.5
_PDF_GUARD_TIMEOUT_SECONDS = 60
_MAX_PAGES_CHECKED = 100

# Backup inside Pillow: refuses to open anything past the limit (warns at 1x, errors at 2x).
Image.MAX_IMAGE_PIXELS = MAX_PIXELS

IMAGE_TOO_LARGE_TEMPLATE = (
    "This image is too large (about {mp} megapixels). The limit is 50 megapixels. "
    "Please scan at a lower resolution or resize the photo."
)
PDF_TOO_LARGE_MESSAGE = (
    "This PDF page is too large to read. Please use a normal page size, for example A4."
)
_BOMB_PIXELS_RE = re.compile(r"\(([\d,]+) pixels\)")


class ImageTooLarge(Exception):
    """Upload would need more memory to decode than we allow. str(exc) is user-facing."""


def _too_large_image(pixels: int) -> ImageTooLarge:
    return ImageTooLarge(IMAGE_TOO_LARGE_TEMPLATE.format(mp=max(1, math.ceil(pixels / 1_000_000))))


def check_image_pixels(buffer: bytes) -> None:
    """Raises ImageTooLarge. Unreadable/corrupt files pass through untouched - the
    existing pipeline reports those as before."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(buffer)) as img:  # lazy: header only
                width, height = img.size
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        match = _BOMB_PIXELS_RE.search(str(exc))
        pixels = int(match.group(1).replace(",", "")) if match else MAX_PIXELS + 1
        raise _too_large_image(pixels) from None
    except Exception:  # noqa: BLE001
        return
    if width <= 0 or height <= 0:
        raise ImageTooLarge("This image has an invalid size. Please upload a different file.")
    if width * height > MAX_PIXELS:
        raise _too_large_image(width * height)


def check_pdf_page(buffer: bytes) -> None:
    """Raises ImageTooLarge when ANY page (up to _MAX_PAGES_CHECKED) would render past
    MAX_PIXELS or has an invalid size. Page rects only - nothing is rendered.
    Encrypted/broken PDFs pass through (handled as before)."""
    try:
        with fitz.open(stream=buffer, filetype="pdf") as doc:
            if doc.needs_pass or doc.page_count == 0:
                return
            # ponytail: pages past the cap are unchecked; uploads allow 4 pages, raise if that grows
            for i in range(min(doc.page_count, _MAX_PAGES_CHECKED)):
                rect = doc.load_page(i).rect
                width, height = rect.width * PDF_RENDER_SCALE, rect.height * PDF_RENDER_SCALE
                if not (math.isfinite(width) and math.isfinite(height)):
                    raise ImageTooLarge(PDF_TOO_LARGE_MESSAGE)
                if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
                    raise ImageTooLarge(PDF_TOO_LARGE_MESSAGE)
    except ImageTooLarge:
        raise
    except Exception:  # noqa: BLE001
        return


async def check_upload(buffer: bytes, mime_type: str) -> None:
    """Async entry for routes/pipeline. Raises ImageTooLarge."""
    if mime_type == "application/pdf":
        try:
            await asyncio.wait_for(
                asyncio.to_thread(check_pdf_page, buffer), timeout=_PDF_GUARD_TIMEOUT_SECONDS
            )
        except TimeoutError:
            return  # the page-count/parse code already treats a hang as unreadable
    else:
        await asyncio.to_thread(check_image_pixels, buffer)
