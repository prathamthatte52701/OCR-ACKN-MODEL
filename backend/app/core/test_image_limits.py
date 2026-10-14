"""Pixel guard: header-only fixtures, so none of these tests allocate real image memory."""

import io
import os
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path

import fitz
import pytest
from PIL import Image

from app.core.image_limits import (
    MAX_PIXELS,
    PDF_RENDER_SCALE,
    ImageTooLarge,
    check_image_pixels,
    check_pdf_page,
)
from app.features.ocr.preprocessing import PDF_RENDER_SCALE as PREPROCESSING_SCALE


def png_header(width: int, height: int) -> bytes:
    """Valid signature + IHDR + an IDAT chunk header, truncated afterwards (Pillow reads the
    size without decoding, so this is what a ~100-byte decompression bomb looks like)."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", b"x" * 8)


def jpeg_header(width: int, height: int) -> bytes:
    sof = struct.pack(">BHHB", 8, height, width, 1) + bytes([1, 0x11, 0])
    sos = bytes([1, 1, 0, 0, 63, 0])
    return (
        b"\xff\xd8"
        + b"\xff\xc0"
        + struct.pack(">H", len(sof) + 2)
        + sof
        + b"\xff\xda"
        + struct.pack(">H", len(sos) + 2)
        + sos
    )


def raw_pdf(mediabox: str) -> bytes:
    return (
        "%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        "2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        f"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[{mediabox}]>>endobj\n"
        "trailer<</Root 1 0 R>>\n%%EOF"
    ).encode()


def test_render_scale_matches_preprocessing() -> None:
    assert PDF_RENDER_SCALE == PREPROCESSING_SCALE


@pytest.mark.parametrize("maker", [png_header, jpeg_header])
def test_huge_header_rejected(maker) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ImageTooLarge, match="too large .about 1600 megapixels"):
        check_image_pixels(maker(40000, 40000))


def test_boundary_just_under_and_over() -> None:
    check_image_pixels(png_header(10000, 5000))  # exactly MAX_PIXELS: allowed
    check_image_pixels(png_header(7071, 7071))
    with pytest.raises(ImageTooLarge):
        check_image_pixels(png_header(7072, 7072))
    with pytest.raises(ImageTooLarge):
        check_image_pixels(png_header(10000, 5001))
    assert 10000 * 5000 == MAX_PIXELS


def test_thin_strip_rejected() -> None:
    with pytest.raises(ImageTooLarge):
        check_image_pixels(png_header(1, 100_000_000))


def test_normal_12mp_passes() -> None:
    buf = io.BytesIO()
    Image.new("L", (4000, 3000), 200).save(buf, format="PNG")
    check_image_pixels(buf.getvalue())


def test_unreadable_files_pass_through_unchanged() -> None:
    check_image_pixels(b"")
    check_image_pixels(b"\x89PNG\r\n\x1a\ngarbage")
    check_image_pixels(png_header(100, 100)[:20])  # truncated mid-IHDR


def test_zero_size_png_not_a_crash() -> None:
    try:
        check_image_pixels(png_header(0, 0))
    except ImageTooLarge:
        pass


def test_pdf_a4_passes() -> None:
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    check_pdf_page(doc.tobytes())


def test_pdf_largest_page_rejected() -> None:
    doc = fitz.open()
    doc.new_page(width=14400, height=14400)  # fitz's maximum
    with pytest.raises(ImageTooLarge, match="PDF page is too large"):
        check_pdf_page(doc.tobytes())


def test_pdf_any_page_too_large_rejected() -> None:
    doc = fitz.open()
    for _ in range(6):
        doc.new_page(width=595, height=842)
    doc.new_page(width=14400, height=14400)  # page 7
    with pytest.raises(ImageTooLarge, match="PDF page is too large"):
        check_pdf_page(doc.tobytes())


def test_pdf_many_normal_pages_pass_fast() -> None:
    doc = fitz.open()
    for _ in range(200):
        doc.new_page(width=595, height=842)
    data = doc.tobytes()
    start = time.perf_counter()
    check_pdf_page(data)
    assert time.perf_counter() - start < 5


@pytest.mark.parametrize("box", ["0 0 0 0", "0 0 -500 -500", "0 0 99999999999 99999999999"])
def test_pdf_weird_boxes_no_crash(box: str) -> None:
    try:
        check_pdf_page(raw_pdf(box))
    except ImageTooLarge:
        pass  # rejecting is fine; crashing is not


def test_pdf_garbage_and_encrypted_pass_through() -> None:
    check_pdf_page(b"%PDF-not really")
    doc = fitz.open()
    doc.new_page()
    enc = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u", permissions=0)
    check_pdf_page(enc)


_CV2_PROBE = """
import app, io, numpy as np, cv2
from PIL import Image
buf = io.BytesIO()
Image.new('L', (8000, 8000), 7).save(buf, format='PNG')  # 64 MP
try:
    img = cv2.imdecode(np.frombuffer(buf.getvalue(), np.uint8), cv2.IMREAD_COLOR)
    print('REFUSED' if img is None else 'DECODED')
except cv2.error:
    print('REFUSED')
"""


def test_opencv_env_backstop_refuses_oversized_decode() -> None:
    """Proof that OPENCV_IO_MAX_IMAGE_PIXELS (set in app/__init__) is honoured by cv2.imdecode,
    in a fresh process where cv2 is imported only after `import app`."""
    backend = Path(__file__).resolve().parents[2]

    def run(extra_env: dict[str, str]) -> str:
        env = {k: v for k, v in os.environ.items() if k != "OPENCV_IO_MAX_IMAGE_PIXELS"}
        out = subprocess.run(
            [sys.executable, "-c", _CV2_PROBE],
            cwd=backend,
            capture_output=True,
            text=True,
            timeout=120,
            env={**env, **extra_env},
        )
        return out.stdout.strip() + out.stderr

    assert run({}).startswith("REFUSED")
    # control: with a bigger explicit limit the same image decodes, so the env var is the cause
    assert run({"OPENCV_IO_MAX_IMAGE_PIXELS": "1000000000"}).startswith("DECODED")
