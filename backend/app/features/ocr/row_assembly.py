"""Shared row-reconstruction logic for both OCR (paddle_runner.py) and PDF
text-layer (preprocessing.py) extraction paths.

Deliberately dependency-light (stdlib only) so importing it never triggers
paddle_runner.py's heavy paddle/numpy import machinery - preprocessing.py
needs this for PDFs with a digital text layer, which never touch PaddleOCR
at all, and must stay cheap to import for that path.
"""

# Boxes whose vertical centers land within this fraction of the median box
# height of each other are treated as the same table row. 0.5 was picked
# empirically: label/value pairs on the same printed row commonly differ by
# a few px in y (font baseline, digit vs. letter glyph height) but stay well
# under half a text line's height apart, while genuinely different rows in
# these header tables are spaced close to a full line height or more.
ROW_HEIGHT_CLUSTER_RATIO = 0.5

# Y-clustering alone isn't column-aware: the letterhead/address block (left)
# and the header table (right) sit side by side, and on a rotated/skewed
# photo their rows can drift into the same Y-band purely by coincidence,
# producing e.g. "AVTEC LIMITED  Reference No.  9800601391  10.07.2026" as
# one merged line - confirmed on real failing documents (T-27, 14-T), not
# a hypothetical. Fix: within a Y-cluster, split into separate output lines
# wherever a horizontal gap between adjacent x-sorted items is a clear
# outlier next to the OTHER gaps in that same row - relative to the row's
# own spacing, not a fixed pixel/height multiple, since that doesn't
# generalize across image resolutions/DPI (a real image's ~900px cross-
# column gap and a small synthetic test PDF's ~150px column gap are the
# same *relative* jump, just different absolute scales). A row's genuine
# label->value->date gaps stay close to each other in size; a real column
# boundary sits several times larger than its neighbors.
ROW_GAP_OUTLIER_RATIO = 3.0
# Fallback for a row with only two items (a single gap, nothing to compare
# it against) - falls back to an absolute multiple of median box height.
MAX_ROW_GAP_RATIO = 6.0


def assemble_rows(texts: list[str], boxes: list[list[float]]) -> list[str]:
    """Groups text fragments into table rows by vertical (y-axis) proximity,
    then joins each row's fragments left-to-right by x, so a label and its
    same-row value/date land on one logical line (e.g. "Reference No.
    9800532362  02.05.2026") instead of flattening every fragment onto its
    own line with no row/column structure - the root cause of the AI
    grabbing a date from a structurally-adjacent-but-wrong row.

    boxes are [left, top, right, bottom] per text fragment - PaddleOCR's
    `rec_boxes` (paddlex's `convert_points_to_boxes` format) or PyMuPDF's
    per-word boxes from `page.get_text("words")` are both this shape."""
    if len(boxes) != len(texts):
        # Defensive fallback - geometry missing/mismatched. Keep the old
        # one-fragment-per-line behavior rather than crash or misalign rows.
        return [t.strip() for t in texts if t and t.strip()]

    items = [(t, b) for t, b in zip(texts, boxes, strict=True) if t and t.strip()]
    if not items:
        return []

    def y_center(item: tuple[str, list[float]]) -> float:
        return (item[1][1] + item[1][3]) / 2

    heights = [max(box[3] - box[1], 1.0) for _, box in items]
    median_height = sorted(heights)[len(heights) // 2]
    threshold = median_height * ROW_HEIGHT_CLUSTER_RATIO

    ordered = sorted(items, key=y_center)
    rows: list[list[tuple[str, list[float]]]] = [[ordered[0]]]
    row_y_sum = y_center(ordered[0])
    row_y_count = 1
    for item in ordered[1:]:
        y = y_center(item)
        if abs(y - row_y_sum / row_y_count) <= threshold:
            rows[-1].append(item)
            row_y_sum += y
            row_y_count += 1
        else:
            rows.append([item])
            row_y_sum = y
            row_y_count = 1

    fallback_gap_threshold = median_height * MAX_ROW_GAP_RATIO
    output_lines: list[str] = []
    for row in rows:
        row_sorted = sorted(row, key=lambda item: item[1][0])
        gaps = [
            row_sorted[i + 1][1][0] - row_sorted[i][1][2] for i in range(len(row_sorted) - 1)
        ]
        if len(gaps) >= 2:
            sorted_gaps = sorted(gaps)
            median_gap = sorted_gaps[len(sorted_gaps) // 2]
            # A tiny/zero median (touching or overlapping boxes) would make
            # any real gap look like an outlier by ratio alone - fall back
            # to the absolute per-height threshold in that case.
            row_gap_threshold = (
                median_gap * ROW_GAP_OUTLIER_RATIO if median_gap > 1.0 else fallback_gap_threshold
            )
        else:
            row_gap_threshold = fallback_gap_threshold

        segment: list[tuple[str, list[float]]] = [row_sorted[0]]
        for item, gap in zip(row_sorted[1:], gaps, strict=True):
            if gap > row_gap_threshold:
                output_lines.append("  ".join(t for t, _ in segment))
                segment = [item]
            else:
                segment.append(item)
        output_lines.append("  ".join(t for t, _ in segment))

    return output_lines
