import asyncio
import io

import cv2
import fitz  # PyMuPDF
import numpy as np
from PIL import Image

from app.features.ocr.row_assembly import assemble_rows

# Crops to the top ~30% of the page (Reference No./Delivery Challan No. + date
# row always lives there on both templates) before OCR - ported from the old
# ocr.js HEADER_CROP_RATIO, so OCR never has to fight the item table/stamps/
# signatures below it.
#
# Raised from 0.28 to 0.30: a live accuracy test found 6/8 and 5/6 digit
# misreads in the Tax Invoice No./Reference No. row on documents whose
# printed header table runs slightly taller than 28% of the page (scan DPI,
# margins, and address-block length vary per document) - the last header row
# was getting its glyphs shaved at the crop boundary, and those two digit
# pairs are exactly the ones most sensitive to a clipped stroke. This is a
# conservative, empirical safety-margin increase, not content-aware boundary
# detection - a two-pass "find the real table start" approach would double
# OCR calls per document and is deliberately out of scope (see the
# module-level scope note below). Capped at 0.30 rather than going higher:
# test_preprocessing.py's test_crop_header_keeps_table_out_for_normal_page
# fixture puts a normally-proportioned invoice's item table at 31.25% of
# page height, so anything past that starts eating into the item
# table/stamps/signatures region this ratio exists to keep out.
HEADER_CROP_RATIO = 0.30

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
    """Returns page-1 text if the PDF has a text layer, else None (scanned).

    Uses per-word bounding boxes (`get_text("words")`) run through the same
    row-reconstruction as the OCR path (row_assembly.assemble_rows), not
    plain `get_text()` - a two-column header table (label column + value/
    date column) has its columns in separate text blocks, so PyMuPDF's own
    default reading order does not reliably interleave a row's label with
    its own value; it can put e.g. every date in the table one after
    another, textually far from any label. That was silently feeding the AI
    extraction prompt structure-free text and is the same class of bug the
    OCR path had (see paddle_runner.py's module docstring) - this path just
    never went through OCR in the first place, since a digital PDF with an
    embedded text layer skips the OCR branch entirely (see
    get_pdf_header_text_or_image below)."""
    with fitz.open(stream=buffer, filetype="pdf") as doc:
        if doc.page_count == 0:
            return None
        words = doc[0].get_text("words")
        if not words:
            return None
        texts = [w[4] for w in words]
        boxes = [[w[0], w[1], w[2], w[3]] for w in words]
        text = "\n".join(assemble_rows(texts, boxes)).strip()
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


# --- Feature 6: quality-gated OCR preprocessing -----------------------------
#
# Runs on the already-cropped header region (the output of crop_header/
# get_pdf_header_text_or_image above), BEFORE those bytes are written to the
# temp file OCR reads from. A fast quality gate decides which (if any) of the
# heavy steps below actually run - an already-good scan is passed through
# byte-for-byte, never degraded. Every branch is independently triggered by
# its own heuristic; there is no single on/off switch.
#
# Scope boundary (deliberate, not an oversight): this pipeline only ever OCRs
# the top-30% header crop (see HEADER_CROP_RATIO), not the full page. So:
#   - "Watermark/stamp/seal suppression" here means adaptive contrast-based
#     text-vs-background separation *within that crop*, not general watermark
#     segmentation - there's no dedicated segmentation model, that would be
#     solving a problem this pipeline mostly doesn't have.
#   - Multi-column layouts / table-dominant pages are effectively out of
#     scope by construction (they live below the header), verified with a
#     synthetic test case in test_preprocessing.py rather than assumed - no
#     PP-Structure layout analysis was needed.
#   - Gross full-page rotation (90/180/270) is only *partially* recoverable
#     here: if the original page itself was rotated before crop_header ran,
#     the "top 28%" crop already grabbed the wrong region, and no amount of
#     preprocessing on that crop recovers the real header. The orientation
#     branch below only helps when the crop itself still contains the right
#     content just rotated in place (e.g. a photographed header rotated at
#     the point of capture, or embedded-orientation image metadata) - see
#     test_preprocessing.py for what this does and doesn't fix.
#
# ponytail: 180-degree rotation is a known false negative of the
# misorientation heuristic below (row/column ink-variance stays
# horizontal-dominant either way up), so it never gets flagged. A real fix
# needs a signal orthogonal to line orientation (text-line direction voting,
# or just always asking PaddleOCR's classifier) - not worth the extra
# always-on cost for a case this pipeline can't fully recover from anyway
# (see the crop-region note above). Upgrade path: PaddleOCR's own
# orientation classifier already handles 0/90/180/270 correctly once told to
# run (see run_ocr's use_doc_orientation_classify) - the gap is only in
# *deciding* to ask for it.

# Laplacian variance below this on the grayscale crop = blurry enough to be
# worth a mild sharpen. ~100 is the common rule-of-thumb threshold for this
# metric (OpenCV/pyimagesearch's "variance of Laplacian" blur detector).
_BLUR_VARIANCE_THRESHOLD = 100.0
# Foreground-vs-background mean-intensity gap (0-255) below this = low
# contrast/faded, worth a CLAHE pass. Deliberately NOT plain grayscale
# stddev: a header crop is mostly background by area (a few thin lines of
# text on a lot of white), so overall stddev stays low even for a perfectly
# crisp scan - it's the ink-vs-paper gap that actually signals "faded", not
# how much of the frame the ink covers.
_LOW_CONTRAST_DELTA_THRESHOLD = 80.0
# Skew angles smaller than this are noise (not a real tilt worth correcting);
# angles larger than this are treated as gross rotation, not a deskew case -
# handled (best-effort) by the orientation branch instead.
_MIN_DESKEW_ANGLE_DEG = 0.5
_MAX_DESKEW_ANGLE_DEG = 30.0
# Max-vs-min brightness delta across quadrants above this (0-255 scale) =
# shadow/uneven lighting worth normalizing.
_SHADOW_BRIGHTNESS_DELTA = 25.0
# Column/row ink-variance ratio above this = likely rotated 90/270 (see the
# ponytail note above for why 180 isn't covered by this signal).
_ORIENTATION_VARIANCE_RATIO = 1.8
# Fraction of mid-gray (60-200) pixels above this = probably a faint
# watermark/stamp bleeding into the header crop, worth adaptive-threshold
# suppression. A clean header crop is close to bimodal (near-white
# background, near-black text), so a high mid-gray fraction is unusual.
_WATERMARK_MIDTONE_FRACTION = 0.05
# Median ink-blob height as a fraction of crop height above this = unusually
# large glyphs (not just bold - genuinely oversized), worth bumping the
# detector's input-size cap. Calibrated empirically (see
# test_preprocessing.py's variant_huge_text/variant_colored_bold): a normal
# header crop's title line tops out around 0.08, a synthetic huge-text crop
# measured ~0.13. Tiny text was checked too and did NOT need a fix - default
# text_det_limit_side_len=960 already reads it fine, so there's no matching
# "too small" branch here (nothing to add, per the task's own "adjust
# per-call if [testing] shows [it] so" instruction - it didn't).
_LARGE_TEXT_HEIGHT_RATIO = 0.10
# Bumped text_det_limit_side_len for the large-text case above. Verified
# empirically: a synthetic huge-text crop dropped the last digit of an
# 11-char invoice number at the default 960 ("G002770482") and read it
# correctly at 1600 ("G0027704821") - see test_preprocessing.py.
LARGE_TEXT_DET_LIMIT = 1600

# Marker tokens embedded in assess_and_preprocess's returned step list so
# pipeline.py can thread the flags that can't be expressed as image bytes
# (they affect the OCR call itself, not the image) - kept as constants here
# rather than duplicated magic strings in both files.
ORIENTATION_CHECK_STEP = "orientation_check:paddle_classifier"
LARGE_TEXT_DET_LIMIT_STEP = "large_text:text_det_limit_bump"


def _decode(image_bytes: bytes) -> np.ndarray:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode image for preprocessing")
    return img


def _encode(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise ValueError("Could not re-encode image after preprocessing")
    return buf.tobytes()


def _laplacian_variance(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _sharpen(img: np.ndarray) -> np.ndarray:
    # Unsharp mask - cheap, standard, no dedicated dependency needed.
    blurred = cv2.GaussianBlur(img, (0, 0), sigmaX=3)
    return cv2.addWeighted(img, 1.5, blurred, -0.5, 0)


def _ink_mask(gray: np.ndarray) -> np.ndarray:
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    return thresh


def _deskew(img: np.ndarray, gray: np.ndarray) -> tuple[np.ndarray, float]:
    coords = cv2.findNonZero(_ink_mask(gray))
    if coords is None or len(coords) < 20:
        return img, 0.0
    (rect_w, rect_h), rect_angle = cv2.minAreaRect(coords)[1:]
    # cv2.minAreaRect's angle is relative to whichever side it labels "w" -
    # which flips depending on box orientation, not on the actual text tilt.
    # Normalizing against which side is longer (text lines are always wider
    # than tall) gives a stable signed rotation-from-horizontal. Verified
    # empirically against a known ~10-degree synthetic tilt in
    # test_preprocessing.py (residual angle after correction: 0.0).
    angle = rect_angle + 90 if rect_w < rect_h else rect_angle
    if abs(angle) < _MIN_DESKEW_ANGLE_DEG or abs(angle) > _MAX_DESKEW_ANGLE_DEG:
        return img, angle
    height, width = img.shape[:2]
    center = (width // 2, height // 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(
        img, matrix, (width, height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )
    return rotated, angle


def _clahe(img: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    lightness, a_chan, b_chan = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    lightness = clahe.apply(lightness)
    return cv2.cvtColor(cv2.merge((lightness, a_chan, b_chan)), cv2.COLOR_LAB2BGR)


def _quadrant_brightness_delta(gray: np.ndarray) -> float:
    height, width = gray.shape[:2]
    mid_h, mid_w = height // 2, width // 2
    quadrants = (
        gray[0:mid_h, 0:mid_w],
        gray[0:mid_h, mid_w:width],
        gray[mid_h:height, 0:mid_w],
        gray[mid_h:height, mid_w:width],
    )
    means = [float(q.mean()) for q in quadrants if q.size]
    return (max(means) - min(means)) if means else 0.0


def _normalize_illumination(img: np.ndarray, gray: np.ndarray) -> np.ndarray:
    # "Background division": a heavily-blurred copy of the image approximates
    # the slow-varying shadow/lighting gradient; dividing it out cancels the
    # gradient while preserving local (text) detail. Cheaper than a
    # morphological top-hat pass and gives an equivalent result here.
    background = cv2.GaussianBlur(gray, (0, 0), sigmaX=31)
    normalized = cv2.divide(gray, background, scale=255)
    return cv2.cvtColor(normalized, cv2.COLOR_GRAY2BGR)


def _foreground_background_contrast(gray: np.ndarray) -> float:
    mask = _ink_mask(gray)
    ink = gray[mask == 255]
    background = gray[mask == 0]
    if ink.size == 0 or background.size == 0:
        return 255.0  # nothing to separate - don't flag as low-contrast
    return float(background.mean()) - float(ink.mean())


def _midtone_fraction(gray: np.ndarray) -> float:
    midtone = (gray > 60) & (gray < 200)
    return float(midtone.mean())


def _suppress_watermark_noise(gray: np.ndarray) -> np.ndarray:
    # Adaptive threshold isolates strong dark strokes (header text) from
    # fainter overlaid noise (watermark/stamp bleed) - a pragmatic
    # text-vs-background separation, not general watermark segmentation (see
    # the module-level scope note above).
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 35, 15
    )
    return cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)


def _likely_misoriented(gray: np.ndarray) -> bool:
    # Header crops are short, wide strips of horizontal text lines, so
    # ink-density variance across ROWS (line vs. gap) should dominate over
    # variance across COLUMNS. A 90/270 rotation turns lines into columns,
    # flipping which axis has the higher variance. Coarse signal, not
    # OCR-verified - see the 180-degree false-negative note above.
    mask = _ink_mask(gray)
    row_profile = mask.sum(axis=1).astype(np.float64)
    col_profile = mask.sum(axis=0).astype(np.float64)
    row_var = row_profile.var()
    if row_var < 1e-6:
        return False
    return bool((col_profile.var() / row_var) > _ORIENTATION_VARIANCE_RATIO)


def _median_ink_height_ratio(gray: np.ndarray) -> float:
    contours, _ = cv2.findContours(_ink_mask(gray), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    heights = sorted(
        h for (_, _, w, h) in (cv2.boundingRect(c) for c in contours) if w > 3 and h > 3
    )
    if not heights:
        return 0.0
    return heights[len(heights) // 2] / gray.shape[0]


def assess_and_preprocess(image_bytes: bytes) -> tuple[bytes, list[str]]:
    """Fast quality gate + conditional preprocessing for a header-crop image.

    Never degrades an already-good crop: each heavy step below only runs when
    its own heuristic actually trips. Returns the (possibly unmodified) image
    bytes plus the list of steps that ran, for pipeline.py to log and to
    decide whether to ask PaddleOCR's orientation classifier to run / bump
    its detector's input-size cap for this one call (see
    ORIENTATION_CHECK_STEP / LARGE_TEXT_DET_LIMIT_STEP)."""
    try:
        img = _decode(image_bytes)
    except ValueError:
        # Not a decodable image (shouldn't happen - crop_header always
        # produces a PNG) - fail open, let OCR see the original bytes.
        return image_bytes, []

    steps: list[str] = []
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    if _laplacian_variance(gray) < _BLUR_VARIANCE_THRESHOLD:
        img = _sharpen(img)
        steps.append("sharpen_blur")
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    img, angle = _deskew(img, gray)
    if abs(angle) >= _MIN_DESKEW_ANGLE_DEG:
        steps.append(f"deskew:{angle:.1f}deg")
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Illumination normalization runs before the watermark/contrast checks
    # below on purpose: an uneven-lighting gradient is itself a field of
    # midtone pixels and would otherwise false-positive the watermark
    # heuristic (a shadow isn't a watermark - fix the more fundamental issue
    # first, then re-assess on the corrected image).
    if _quadrant_brightness_delta(gray) > _SHADOW_BRIGHTNESS_DELTA:
        img = _normalize_illumination(img, gray)
        steps.append("illumination_normalize")
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    if _midtone_fraction(gray) > _WATERMARK_MIDTONE_FRACTION:
        img = _suppress_watermark_noise(gray)
        steps.append("adaptive_watermark_suppress")
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    if _foreground_background_contrast(gray) < _LOW_CONTRAST_DELTA_THRESHOLD:
        img = _clahe(img)
        steps.append("clahe_contrast")
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    if _likely_misoriented(gray):
        steps.append(ORIENTATION_CHECK_STEP)

    if _median_ink_height_ratio(gray) > _LARGE_TEXT_HEIGHT_RATIO:
        steps.append(LARGE_TEXT_DET_LIMIT_STEP)

    # ORIENTATION_CHECK_STEP/LARGE_TEXT_DET_LIMIT_STEP are marker-only (they
    # tell pipeline.py how to call run_ocr, they don't touch pixels) - only
    # re-encode when a step actually modified img, so a crop that only trips
    # one of those two still comes back byte-identical rather than paying
    # for a pointless (pixel-identical) re-compression.
    _marker_only_steps = {ORIENTATION_CHECK_STEP, LARGE_TEXT_DET_LIMIT_STEP}
    if not any(step not in _marker_only_steps for step in steps):
        return image_bytes, steps
    return _encode(img), steps
