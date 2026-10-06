import cv2
import numpy as np

from app.features.ocr.page_normalize import (
    ORIENT_PAPER_STEP,
    ORIENT_ROTATE_STEP,
    find_paper,
    normalize_photo,
)


def _page(width: int = 600, height: int = 850) -> np.ndarray:
    page = np.full((height, width, 3), 245, dtype=np.uint8)
    for i in range(12):  # header-ish text rows near the top, body further down
        y = 40 + i * 22
        cv2.putText(
            page,
            f"TAX INVOICE ROW {i} 9800{i}12345",
            (20, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (20, 20, 20),
            1,
        )
    return page


def _on_background(
    page: np.ndarray, canvas: tuple[int, int] = (1000, 1400), offset: tuple[int, int] = (180, 260)
) -> np.ndarray:
    rng = np.random.default_rng(1)
    bg = rng.integers(20, 90, size=(canvas[1], canvas[0], 3), dtype=np.uint8)
    x, y = offset
    bg[y : y + page.shape[0], x : x + page.shape[1]] = page
    return bg


def _png(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return bytes(buf.tobytes())


def _decode(b: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(b, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert img is not None
    return img


def test_full_bleed_scan_is_returned_untouched() -> None:
    data = _png(_page())
    out, steps = normalize_photo(data, lambda _png: (0, 0.99))
    assert steps == []
    assert out is data  # byte-identical: a scan must never be re-encoded or altered


def test_page_with_background_is_cropped_to_the_paper() -> None:
    data = _png(_on_background(_page()))
    found = find_paper(_decode(data))
    assert found is not None and found[1] < 0.88
    out, steps = normalize_photo(data, lambda _png: (0, 0.99))
    assert ORIENT_PAPER_STEP in steps
    page = _decode(out)
    # Portrait page out, and far less dark background than we put in
    assert page.shape[0] > page.shape[1]
    assert page.mean() > 150


def test_sideways_photo_is_rotated_upright_when_classifier_is_sure() -> None:
    sideways = cv2.rotate(_on_background(_page()), cv2.ROTATE_90_CLOCKWISE)
    out, steps = normalize_photo(_png(sideways), lambda _png: (270, 0.95))
    assert any(s.startswith(ORIENT_ROTATE_STEP) for s in steps)
    page = _decode(out)
    assert page.shape[0] > page.shape[1]


def test_low_confidence_orientation_is_ignored() -> None:
    sideways = cv2.rotate(_on_background(_page()), cv2.ROTATE_90_CLOCKWISE)
    _, steps = normalize_photo(_png(sideways), lambda _png: (270, 0.4))
    assert not any(s.startswith(ORIENT_ROTATE_STEP) for s in steps)


def test_upside_down_page_is_flipped() -> None:
    flipped = cv2.rotate(_on_background(_page()), cv2.ROTATE_180)
    _, steps = normalize_photo(_png(flipped), lambda _png: (180, 0.95))
    assert f"{ORIENT_ROTATE_STEP}:180" in steps


def test_sideways_without_a_classifier_falls_back_to_original() -> None:
    sideways = _png(cv2.rotate(_page(), cv2.ROTATE_90_CLOCKWISE))
    out, steps = normalize_photo(sideways, None)
    assert steps == [] and out is sideways


def test_garbage_bytes_fail_open() -> None:
    junk = b"not an image at all"
    out, steps = normalize_photo(junk, lambda _png: (90, 0.99))
    assert out is junk and steps == []


def test_classifier_exception_fails_open() -> None:
    data = _png(_on_background(_page()))

    def boom(_png: bytes) -> tuple[int, float]:
        raise RuntimeError("model down")

    out, steps = normalize_photo(data, boom)
    assert out is data and steps == []
