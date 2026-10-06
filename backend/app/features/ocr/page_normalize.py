"""Photo-only page normalization: runs BEFORE crop_header on uploaded images.

crop_header keeps a fixed top 30% of the raw image. That works for a scan or
a photo where the paper fills the frame, but a phone photo with a lot of
background around the paper (or a photo taken sideways / upside down) puts
the Tax Invoice / Delivery Challan header table outside that 30% band, so
OCR never sees it (measured on real failures: header table below the cut,
or the "top 30%" of a landscape photo being the item list).

This stage finds the paper in the photo, flattens it to an upright
rectangle, and fixes 90/180/270 degree rotation, so the existing 30% crop
lands on the actual header. It is deliberately conservative - an image that
already looks like a scan (paper fills the frame, upright) is returned as the
original bytes, untouched, so documents that work today keep working.

PDFs never go through here (their pages render flat and upright).
"""

import io
from collections.abc import Callable

import cv2
import numpy as np
from PIL import Image

# Analysis runs on a downscaled copy - paper detection doesn't need full
# resolution and this keeps the stage cheap.
_ANALYSIS_MAX_SIDE = 900
# Paper must cover at least this fraction of the frame to be trusted as "the
# page" (guards against locking onto a stray bright patch).
_MIN_PAPER_FRACTION = 0.25
# At or above this fraction the frame is basically the paper already (a scan
# or a tight photo): skip the crop/warp, only rotation can still apply.
_FULL_BLEED_FRACTION = 0.88
# Contour area / its min-area-rect area: how rectangular the blob is.
_MIN_RECTANGULARITY = 0.85
# Output page gets upscaled to at least this width - small phone photos leave
# header text only a few px high, below what the recognizer reads reliably.
_MIN_OUTPUT_WIDTH = 1400
_MAX_OUTPUT_SIDE = 3200
# The orientation classifier must be at least this sure before we rotate on
# its say-so; a doubtful call leaves the image as it was.
_MIN_ORIENTATION_SCORE = 0.85

ORIENT_ROTATE_STEP = "page_rotate"
ORIENT_PAPER_STEP = "page_crop"


def _decode(image_bytes: bytes) -> np.ndarray | None:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return img


def _encode_png(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise ValueError("png encode failed")
    return bytes(buf.tobytes())


def _order_quad(pts: np.ndarray) -> np.ndarray:
    pts = pts.reshape(4, 2).astype("float32")
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array(
        [pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]],
        dtype="float32",
    )


def _longest_run(flags: np.ndarray) -> tuple[int, int] | None:
    best: tuple[int, int] | None = None
    start: int | None = None
    for i, f in enumerate(list(flags) + [False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            if best is None or i - start > best[1] - best[0]:
                best = (start, i)
            start = None
    return best


def _central_band_box(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    """Axis-aligned page extent from the mask's central band: rows where the
    middle 30% of columns are mostly paper (0.6, so a dark QR block can not split the run), columns where the middle
    30% of rows are. Robust to bright background merged onto the page's
    edges, but assumes the page is roughly upright in the frame."""
    h, w = mask.shape[:2]
    col_band = mask[:, int(w * 0.35) : int(w * 0.65)] > 0
    row_band = mask[int(h * 0.35) : int(h * 0.65), :] > 0
    rows = _longest_run(col_band.mean(axis=1) > 0.6)
    cols = _longest_run(row_band.mean(axis=0) > 0.6)
    if rows is None or cols is None:
        return None
    return cols[0], rows[0], cols[1], rows[1]


def find_paper(img: np.ndarray) -> tuple[np.ndarray, float] | None:
    """Returns (4 corner points in ORIGINAL image coordinates, ordered tl/tr/
    br/bl; fraction of the frame the paper covers) or None if no convincing
    page-shaped bright region exists."""
    h, w = img.shape[:2]
    scale = _ANALYSIS_MAX_SIDE / max(h, w)
    small = cv2.resize(img, (int(w * scale), int(h * scale))) if scale < 1 else img.copy()
    sh, sw = small.shape[:2]
    # Paper is the bright, low-saturation blob; background in these photos is
    # patterned bedsheet/table, sometimes with bright stripes - the stripes
    # are thin, so a big morphological opening removes them while the page
    # (a huge solid area) survives.
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (7, 7), 0)
    _, bright = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    low_sat = (hsv[:, :, 1] < 70).astype(np.uint8) * 255
    mask = cv2.bitwise_and(bright, low_sat)
    k = max(15, int(min(sh, sw) * 0.04))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    cnt = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(cnt)
    fraction = area / float(sh * sw)
    if fraction < _MIN_PAPER_FRACTION:
        return None
    rect = cv2.minAreaRect(cnt)
    rect_area = rect[1][0] * rect[1][1]
    if rect_area <= 0 or area / rect_area < _MIN_RECTANGULARITY:
        # Not page-shaped as one blob: typically the page has merged with a
        # bright patch of background (a white bedsheet stripe/pillow).
        # Fall back to the page's extent along its central band, which a
        # side patch can't reach (see _central_band_box).
        box = _central_band_box(mask)
        if box is None:
            return None
        x0, y0, x1, y1 = box
        fraction = (x1 - x0) * (y1 - y0) / float(sh * sw)
        if fraction < _MIN_PAPER_FRACTION:
            return None
        quad = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype="float32") / scale
        return quad, float(fraction)
    # Prefer the true 4-corner polygon (handles perspective/keystone); fall
    # back to the min-area rectangle.
    peri = cv2.arcLength(cnt, True)
    approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
    quad = approx.reshape(4, 2) if len(approx) == 4 else cv2.boxPoints(rect)
    quad = _order_quad(np.asarray(quad)) / scale
    return quad, float(fraction)


def _warp_to_page(img: np.ndarray, quad: np.ndarray) -> np.ndarray:
    tl, tr, br, bl = quad
    width = int(round(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl))))
    height = int(round(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl))))
    dst = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], "float32")
    m = cv2.getPerspectiveTransform(quad, dst)
    return cv2.warpPerspective(img, m, (width, height), flags=cv2.INTER_CUBIC)


def _rotate(img: np.ndarray, angle: int) -> np.ndarray:
    """Rotates clockwise by `angle` degrees (0/90/180/270)."""
    if angle == 90:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if angle == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    if angle == 270:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return img


def normalize_photo(
    image_bytes: bytes,
    classify_orientation: Callable[[bytes], tuple[int, float]] | None = None,
) -> tuple[bytes, list[str]]:
    """Returns (page image bytes, steps taken). Never raises: on any doubt it
    hands back the ORIGINAL bytes and an empty step list.

    classify_orientation takes PNG bytes of the page and returns
    (clockwise_degrees_needed_to_make_it_upright, confidence). It is only
    consulted when the photo looks sideways or has real background around the
    paper - an image that already looks like a scan never reaches it.
    """
    try:
        img = _decode(image_bytes)
        if img is None:
            return image_bytes, []
        h, w = img.shape[:2]
        steps: list[str] = []

        paper = find_paper(img)
        page = img
        has_margin = False
        if paper is not None:
            quad, fraction = paper
            if fraction < _FULL_BLEED_FRACTION:
                page = _warp_to_page(img, quad)
                steps.append(ORIENT_PAPER_STEP)
                has_margin = True
        sideways = page.shape[1] > page.shape[0]

        if (sideways or has_margin) and classify_orientation is not None:
            angle, score = classify_orientation(_encode_png(page))
            if angle and score >= _MIN_ORIENTATION_SCORE:
                page = _rotate(page, angle)
                steps.append(f"{ORIENT_ROTATE_STEP}:{angle}")
        elif sideways and classify_orientation is None:
            return image_bytes, []

        if not steps:
            return image_bytes, []

        ph, pw = page.shape[:2]
        if pw < _MIN_OUTPUT_WIDTH:
            f = min(_MIN_OUTPUT_WIDTH / pw, _MAX_OUTPUT_SIDE / max(ph, pw))
            page = cv2.resize(page, (int(pw * f), int(ph * f)), interpolation=cv2.INTER_CUBIC)
        return _encode_png(page), steps
    except Exception:  # noqa: BLE001
        return image_bytes, []


def png_size(png_bytes: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(png_bytes)) as im:
        return im.size
