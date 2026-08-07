"""Feature 6 test suite: quality-gated OCR preprocessing.

Fast, OCR-free unit tests on assess_and_preprocess() live here as plain
pytest test_* functions (run via `pytest app/features/ocr/test_preprocessing.py`
or `python -m app.features.ocr.test_preprocessing`), matching
test_extraction.py's shape.

Also doubles as the reusable synthetic-fixture generator (no degraded-scan
fixture set exists in this repo) - the GENERATORS dict at the bottom is
imported by the scratch script that drives these images through the real
OCR pipeline (heavier, model-loading, deliberately NOT part of this fast
pytest suite - see backend's CLAUDE.md test conventions)."""

import io

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from app.features.ocr.preprocessing import (
    LARGE_TEXT_DET_LIMIT_STEP,
    ORIENTATION_CHECK_STEP,
    assess_and_preprocess,
)

_FONT_REGULAR = "C:/Windows/Fonts/arial.ttf"
_FONT_BOLD = "C:/Windows/Fonts/arialbd.ttf"
_CANVAS_SIZE = (1600, 450)  # wide-short strip, mimics a real header crop's aspect


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(_FONT_BOLD if bold else _FONT_REGULAR, size)


def _to_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def make_clean_header() -> Image.Image:
    """A clean, realistic-enough Tax Invoice header - white bg, black text,
    the fields the real pipeline actually cares about (invoice no / date)."""
    img = Image.new("RGB", _CANVAS_SIZE, "white")
    draw = ImageDraw.Draw(img)
    draw.text((40, 40), "TAX INVOICE", font=_font(48, bold=True), fill="black")
    draw.text(
        (40, 150),
        "Invoice No: G0027704821          Date: 01/07/2026",
        font=_font(36),
        fill="black",
    )
    draw.text((40, 230), "GSTIN: 27AAAAA0000A1Z5", font=_font(30), fill="black")
    draw.text((40, 300), "Reference No: REF00012345", font=_font(30), fill="black")
    return img


# --- variant generators -----------------------------------------------------


def variant_blur() -> Image.Image:
    img = make_clean_header()
    arr = np.array(img)
    # motion-blur kernel, not just Gaussian - closer to a real handheld-photo blur
    kernel_size = 25
    kernel = np.zeros((kernel_size, kernel_size))
    kernel[kernel_size // 2, :] = np.ones(kernel_size)
    kernel /= kernel_size
    blurred = cv2.filter2D(arr, -1, kernel)
    blurred = cv2.GaussianBlur(blurred, (9, 9), sigmaX=3)
    return Image.fromarray(blurred)


def variant_tilt() -> Image.Image:
    img = make_clean_header()
    return img.rotate(10, expand=True, fillcolor="white")


def variant_rotate_90() -> Image.Image:
    return make_clean_header().rotate(90, expand=True, fillcolor="white")


def variant_rotate_180() -> Image.Image:
    return make_clean_header().rotate(180, expand=True, fillcolor="white")


def variant_rotate_270() -> Image.Image:
    return make_clean_header().rotate(270, expand=True, fillcolor="white")


def variant_watermark() -> Image.Image:
    img = make_clean_header().convert("RGBA")
    overlay = Image.new("RGBA", img.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    # tiled, not a single stamp - a real watermark covers most of the page,
    # not one corner, so the midtone-fraction heuristic has something to see
    for y in range(-100, img.height + 100, 90):
        for x in range(-200, img.width + 200, 260):
            draw.text((x, y), "DUPLICATE", font=_font(60, bold=True), fill=(140, 140, 140, 130))
    overlay = overlay.rotate(30, center=(img.width // 2, img.height // 2))
    combined = Image.alpha_composite(img, overlay)
    return combined.convert("RGB")


def variant_faded_low_contrast() -> Image.Image:
    img = make_clean_header()
    img = ImageEnhance.Contrast(img).enhance(0.25)
    img = ImageEnhance.Brightness(img).enhance(1.35)
    return img


def variant_shadow() -> Image.Image:
    img = make_clean_header().convert("RGB")
    arr = np.array(img).astype(np.float64)
    width = arr.shape[1]
    gradient = np.linspace(1.0, 0.35, width)  # left bright -> right dark
    arr *= gradient[np.newaxis, :, np.newaxis]
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8))


def variant_tiny_text() -> Image.Image:
    img = Image.new("RGB", _CANVAS_SIZE, "white")
    draw = ImageDraw.Draw(img)
    draw.text((40, 40), "TAX INVOICE", font=_font(10, bold=True), fill="black")
    draw.text((40, 60), "Invoice No: G0027704821   Date: 01/07/2026", font=_font(9), fill="black")
    draw.text((40, 78), "GSTIN: 27AAAAA0000A1Z5", font=_font(9), fill="black")
    return img


def variant_huge_text() -> Image.Image:
    img = Image.new("RGB", (2200, 900), "white")
    draw = ImageDraw.Draw(img)
    draw.text((40, 20), "G0027704821", font=_font(160, bold=True), fill="black")
    draw.text((40, 220), "01/07/2026", font=_font(160), fill="black")
    return img


def variant_colored_bold() -> Image.Image:
    img = Image.new("RGB", _CANVAS_SIZE, "white")
    draw = ImageDraw.Draw(img)
    draw.text((40, 40), "TAX INVOICE", font=_font(48, bold=True), fill=(180, 0, 0))
    draw.text(
        (40, 150),
        "Invoice No: G0027704821          Date: 01/07/2026",
        font=_font(36, bold=True),
        fill=(0, 0, 160),
    )
    return img


def variant_stamp_seal() -> Image.Image:
    img = make_clean_header()
    draw = ImageDraw.Draw(img)
    cx, cy, r = 1350, 150, 110
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(180, 0, 0), width=6)
    draw.text((cx - 70, cy - 15), "APPROVED", font=_font(20, bold=True), fill=(180, 0, 0))
    return img


def full_page_with_table(table_dominant: bool = False) -> Image.Image:
    """Full page (not a pre-cropped header) - header text in the top strip,
    a block of buyer/tax filler fields (realistic invoice content between
    the header and the item table - the thing a *minimal* synthetic header
    would otherwise skip, understating the real gap), then a large
    grid/table filling the rest. Used to verify crop_header's HEADER_CROP_RATIO
    actually keeps the table out rather than assuming it. table_start_y is
    fixed regardless of page height (the header+filler block is a fixed
    layout, real documents don't stretch their header proportionally to
    however many item rows the table below happens to have)."""
    page_w = 1600
    table_start_y = 750
    page_h = 4200 if table_dominant else 2400
    img = Image.new("RGB", (page_w, page_h), "white")
    draw = ImageDraw.Draw(img)
    draw.text((40, 40), "TAX INVOICE", font=_font(48, bold=True), fill="black")
    draw.text(
        (40, 150),
        "Invoice No: G0027704821          Date: 01/07/2026",
        font=_font(36),
        fill="black",
    )
    draw.text((40, 230), "GSTIN: 27AAAAA0000A1Z5", font=_font(30), fill="black")
    for i, label in enumerate(
        ["Buyer: ACME Corp", "Address: 123 Industrial Rd", "PO No: PO-99812", "Tax: CGST+SGST"]
    ):
        draw.text((40, 320 + i * 90), label, font=_font(26), fill="black")
    rows, cols = (60, 6) if table_dominant else (20, 4)
    row_h = (page_h - table_start_y - 30) // rows
    col_w = page_w // cols
    for r in range(rows + 1):
        y = table_start_y + r * row_h
        draw.line((0, y, page_w, y), fill="black", width=2)
    for c in range(cols + 1):
        x = c * col_w
        draw.line((x, table_start_y, x, page_h - 20), fill="black", width=2)
    for r in range(rows):
        for c in range(cols):
            draw.text(
                (c * col_w + 10, table_start_y + r * row_h + 10),
                f"{r * cols + c:04d}",
                font=_font(16),
                fill="black",
            )
    return img


GENERATORS = {
    "clean": make_clean_header,
    "blur": variant_blur,
    "tilt": variant_tilt,
    "rotate_90": variant_rotate_90,
    "rotate_180": variant_rotate_180,
    "rotate_270": variant_rotate_270,
    "watermark": variant_watermark,
    "faded_low_contrast": variant_faded_low_contrast,
    "shadow": variant_shadow,
    "tiny_text": variant_tiny_text,
    "huge_text": variant_huge_text,
    "colored_bold": variant_colored_bold,
    "stamp_seal": variant_stamp_seal,
}


# --- fast, OCR-free unit tests on assess_and_preprocess --------------------


def test_control_set_triggers_nothing_and_is_byte_identical() -> None:
    clean_bytes = _to_png_bytes(make_clean_header())
    out_bytes, steps = assess_and_preprocess(clean_bytes)
    assert steps == [], f"clean image should trigger no preprocessing steps, got {steps}"
    assert out_bytes == clean_bytes, "unmodified crop must be returned byte-identical"


def test_blur_triggers_sharpen() -> None:
    _, steps = assess_and_preprocess(_to_png_bytes(variant_blur()))
    assert "sharpen_blur" in steps


def test_tilt_triggers_deskew() -> None:
    _, steps = assess_and_preprocess(_to_png_bytes(variant_tilt()))
    assert any(s.startswith("deskew:") for s in steps), steps


def test_faded_triggers_contrast_fix() -> None:
    _, steps = assess_and_preprocess(_to_png_bytes(variant_faded_low_contrast()))
    assert "clahe_contrast" in steps


def test_shadow_triggers_illumination_normalize() -> None:
    _, steps = assess_and_preprocess(_to_png_bytes(variant_shadow()))
    assert "illumination_normalize" in steps


def test_watermark_triggers_adaptive_suppress() -> None:
    _, steps = assess_and_preprocess(_to_png_bytes(variant_watermark()))
    assert "adaptive_watermark_suppress" in steps


def test_huge_text_flags_det_limit_bump() -> None:
    # Empirically motivated (see preprocessing.py's calibration comment): a
    # synthetic huge-text crop actually dropped a trailing digit at the
    # default text_det_limit_side_len=960 and read correctly at 1600.
    _, steps = assess_and_preprocess(_to_png_bytes(variant_huge_text()))
    assert LARGE_TEXT_DET_LIMIT_STEP in steps


def test_tiny_text_does_not_flag_det_limit_bump() -> None:
    # Also empirically checked: tiny text already reads fine at the default
    # 960 limit, so there's deliberately no "too small" branch to trigger.
    _, steps = assess_and_preprocess(_to_png_bytes(variant_tiny_text()))
    assert LARGE_TEXT_DET_LIMIT_STEP not in steps


def test_rotate_90_flags_orientation_check() -> None:
    _, steps = assess_and_preprocess(_to_png_bytes(variant_rotate_90()))
    assert ORIENTATION_CHECK_STEP in steps


def test_rotate_270_flags_orientation_check() -> None:
    _, steps = assess_and_preprocess(_to_png_bytes(variant_rotate_270()))
    assert ORIENTATION_CHECK_STEP in steps


def test_rotate_180_is_a_known_false_negative() -> None:
    # Documented limitation (see preprocessing.py's ponytail note): row/col
    # ink-variance looks the same right-side-up or upside-down, so this
    # heuristic can't catch 180-degree rotation. Locking this in as an
    # explicit assertion so a future "fix" of the heuristic is a deliberate,
    # visible change here - not a silent behavior flip.
    _, steps = assess_and_preprocess(_to_png_bytes(variant_rotate_180()))
    assert ORIENTATION_CHECK_STEP not in steps


def test_crop_header_keeps_table_out_for_normal_page() -> None:
    from app.features.ocr.preprocessing import HEADER_CROP_RATIO, crop_header

    page = full_page_with_table(table_dominant=False)
    crop_bytes = crop_header(_to_png_bytes(page))
    cropped = Image.open(io.BytesIO(crop_bytes))
    expected_h = round(page.height * HEADER_CROP_RATIO)
    assert cropped.height == expected_h
    # table body starts at y=750 in the generator, well past HEADER_CROP_RATIO
    # of a normally-proportioned page (720px here at 0.30) - confirms the
    # "header cropping already avoids the table" assumption for realistic
    # layouts.
    assert expected_h < 750, "header crop unexpectedly reaches into the table body"


def test_crop_header_can_leak_into_table_for_table_dominant_page() -> None:
    # Documented, deliberately-not-"fixed" finding (see preprocessing.py's
    # scope note): an unusually tall, table-dominant page inflates the
    # HEADER_CROP_RATIO cutoff point past where the (fixed-position) table
    # starts, because the ratio is of TOTAL page height, not of header
    # content height. Pinned
    # here as an explicit assertion of current behavior rather than "PP-Structure
    # layout analysis wasn't needed" being an unverified assumption - it WAS
    # verified, and it only holds for normally-proportioned pages.
    from app.features.ocr.preprocessing import HEADER_CROP_RATIO, crop_header

    page = full_page_with_table(table_dominant=True)
    crop_bytes = crop_header(_to_png_bytes(page))
    cropped = Image.open(io.BytesIO(crop_bytes))
    expected_h = round(page.height * HEADER_CROP_RATIO)
    assert cropped.height == expected_h


def test_pdf_text_layer_groups_label_with_its_own_row_not_reading_order() -> None:
    # Regression test for the bug diagnosed in a live accuracy run:
    # _pdf_extract_text_sync used to call PyMuPDF's plain get_text(), which
    # returns text in block/reading order - for a two-column header table
    # (label column, value/date column) that does NOT put a row's label next
    # to its own value; it can group e.g. every date in the table together,
    # far from any label. Build a PDF with exactly that shape - a "Reference
    # No." row and a "Payment Due Date" row where the SECOND row's y sits
    # right below the first (same layout as the real Tax Invoice template) -
    # and assert the fixed word-bbox + assemble_rows path keeps each label
    # on the same line as its own value, not the other row's.
    import fitz

    from app.features.ocr.preprocessing import _pdf_extract_text_sync

    doc = fitz.open()
    page = doc.new_page(width=600, height=200)
    page.insert_text((50, 40), "Reference No.", fontsize=11)
    page.insert_text((250, 40), "9800532362", fontsize=11)
    page.insert_text((450, 40), "02.05.2026", fontsize=11)
    page.insert_text((50, 70), "Payment Due Date:", fontsize=11)
    page.insert_text((250, 70), "31.05.2026", fontsize=11)
    buffer = doc.tobytes()
    doc.close()

    text = _pdf_extract_text_sync(buffer)
    assert text is not None
    lines = text.split("\n")
    reference_line = next(line for line in lines if "Reference" in line)
    assert "9800532362" in reference_line
    assert "02.05.2026" in reference_line
    assert "31.05.2026" not in reference_line


def demo() -> None:
    test_control_set_triggers_nothing_and_is_byte_identical()
    test_blur_triggers_sharpen()
    test_tilt_triggers_deskew()
    test_faded_triggers_contrast_fix()
    test_shadow_triggers_illumination_normalize()
    test_watermark_triggers_adaptive_suppress()
    test_huge_text_flags_det_limit_bump()
    test_tiny_text_does_not_flag_det_limit_bump()
    test_rotate_90_flags_orientation_check()
    test_rotate_270_flags_orientation_check()
    test_rotate_180_is_a_known_false_negative()
    test_crop_header_keeps_table_out_for_normal_page()
    test_crop_header_can_leak_into_table_for_table_dominant_page()
    test_pdf_text_layer_groups_label_with_its_own_row_not_reading_order()
    print("All preprocessing quality-gate self-checks passed.")


if __name__ == "__main__":
    demo()
