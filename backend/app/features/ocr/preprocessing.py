import asyncio
import io

import fitz  # PyMuPDF
from PIL import Image

# Crops to the top ~28% of the page (Reference No./Delivery Challan No. + date
# row always lives there on both templates) before OCR - ported from the old
# ocr.js HEADER_CROP_RATIO, so OCR never has to fight the item table/stamps/
# signatures below it.
HEADER_CROP_RATIO = 0.28

# Wraps in-process PDF parsing (PyMuPDF) in a timeout - a malformed/hostile
# PDF must never be able to hang the whole server, mirrors the old app's
# withTimeout() around pdf-parse/pdfjs-dist calls.
PDF_PARSE_TIMEOUT_SECONDS = 60

# Native render scale before OCR - the old pdf-render-worker.js used 2.5 here
# (its own upscale pipeline applied further tuning after that, specific to
# Tesseract; PaddleOCR does its own internal preprocessing so this scale is
# kept as the baseline render quality only).
PDF_RENDER_SCALE = 2.5


def crop_header(image_bytes: bytes) -> bytes:
    with Image.open(io.BytesIO(image_bytes)) as img:
        width, height = img.size
        crop_height = max(1, round(height * HEADER_CROP_RATIO))
        cropped = img.crop((0, 0, width, crop_height))
        buf = io.BytesIO()
        cropped.convert("RGB").save(buf, format="PNG")
        return buf.getvalue()


def _pdf_page_count_sync(buffer: bytes) -> int | None:
    try:
        with fitz.open(stream=buffer, filetype="pdf") as doc:
            return doc.page_count
    except Exception:  # noqa: BLE001
        return None


def _pdf_extract_text_sync(buffer: bytes) -> str | None:
    """Returns page-1 text if the PDF has a text layer, else None (scanned)."""
    with fitz.open(stream=buffer, filetype="pdf") as doc:
        if doc.page_count == 0:
            return None
        text = doc[0].get_text().strip()
        return text if len(text) > 20 else None


def _pdf_render_page_to_png_sync(buffer: bytes) -> bytes:
    with fitz.open(stream=buffer, filetype="pdf") as doc:
        page = doc[0]
        matrix = fitz.Matrix(PDF_RENDER_SCALE, PDF_RENDER_SCALE)
        pix = page.get_pixmap(matrix=matrix)
        return pix.tobytes("png")


async def get_pdf_page_count(buffer: bytes) -> int | None:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_pdf_page_count_sync, buffer), timeout=PDF_PARSE_TIMEOUT_SECONDS
        )
    except TimeoutError:
        return None


async def get_pdf_header_text_or_image(buffer: bytes) -> tuple[str | None, bytes | None]:
    """Returns (text, None) if the PDF has a digital text layer, or
    (None, cropped_header_png) if it's scanned and needs OCR."""
    try:
        text = await asyncio.wait_for(
            asyncio.to_thread(_pdf_extract_text_sync, buffer), timeout=PDF_PARSE_TIMEOUT_SECONDS
        )
    except TimeoutError:
        raise TimeoutError("PDF text extraction timed out") from None

    if text:
        return text, None

    png_bytes = await asyncio.wait_for(
        asyncio.to_thread(_pdf_render_page_to_png_sync, buffer), timeout=PDF_PARSE_TIMEOUT_SECONDS
    )
    return None, crop_header(png_bytes)
