"""Smoke test for row_assembly's row-grouping text assembly (assemble_rows)
- shared by paddle_runner.py (OCR path) and preprocessing.py (PDF text-layer
path), both of which previously flattened every text fragment onto its own
line with no row/column structure. Pure geometry, no model load, no image
I/O, no PyMuPDF. Run directly: python -m app.features.ocr.test_row_assembly"""

from app.features.ocr.row_assembly import assemble_rows as _assemble_rows


def test_same_row_boxes_grouped_left_to_right() -> None:
    # Label, date, and value boxes at ~the same y (small baseline jitter)
    # but scattered x - exactly the "Reference No." row shape from the
    # diagnosed bug.
    texts = ["Reference No.", "02.05.2026", "9800532362"]
    boxes: list[list[float]] = [
        [50, 100, 200, 130],
        [500, 102, 650, 128],
        [300, 98, 450, 132],
    ]
    rows = _assemble_rows(texts, boxes)
    assert rows == ["Reference No.  9800532362  02.05.2026"]


def test_different_rows_kept_separate() -> None:
    texts = ["TAX INVOICE", "Reference No."]
    boxes: list[list[float]] = [
        [50, 50, 200, 80],
        [50, 300, 200, 330],
    ]
    rows = _assemble_rows(texts, boxes)
    assert rows == ["TAX INVOICE", "Reference No."]


def test_mismatched_lengths_falls_back_to_one_box_per_line() -> None:
    # Defensive fallback for missing/misaligned geometry (e.g. "seal" text
    # type returns an empty rec_boxes) - old flattened behavior, not a crash.
    rows = _assemble_rows(["a", "b"], [])
    assert rows == ["a", "b"]


def test_empty_input_returns_no_rows() -> None:
    assert _assemble_rows([], []) == []


def test_blank_text_boxes_are_dropped() -> None:
    texts = ["Reference No.", "   ", ""]
    boxes: list[list[float]] = [[50, 100, 200, 130], [300, 100, 350, 130], [400, 100, 450, 130]]
    rows = _assemble_rows(texts, boxes)
    assert rows == ["Reference No."]


def demo() -> None:
    test_same_row_boxes_grouped_left_to_right()
    test_different_rows_kept_separate()
    test_mismatched_lengths_falls_back_to_one_box_per_line()
    test_empty_input_returns_no_rows()
    test_blank_text_boxes_are_dropped()
    print("All row-assembly self-checks passed.")


if __name__ == "__main__":
    demo()
