"""What a manual correction of one extracted field writes - ONE helper used by the user route
(PATCH /documents/{id}/correct) and the admin route, so the two cannot drift apart."""

from datetime import datetime

AUTO_CORRECTED_FIELDS = ("taxInvoiceNo", "number", "date")
NEEDS_REVIEW_FIELDS = ("taxInvoiceNo", "referenceNo", "number")


def correction_set_fields(field: str, value: str, now: datetime) -> dict:
    set_fields: dict = {
        field: value,
        "edited": True,
        # A correction changes what would be written to Excel - the previous
        # export (if any) no longer reflects this document's current values.
        "exported": False,
        "updatedAt": now,
    }
    if field in AUTO_CORRECTED_FIELDS:
        # Manual entry supersedes the auto-correction pass - no longer
        # something the OCR correction layer touched.
        set_fields[f"{field}AutoCorrected"] = False
    if field in NEEDS_REVIEW_FIELDS:
        # The person typed this value - the "looks incomplete" flag no longer applies.
        set_fields[f"{field}NeedsReview"] = False
    return set_fields
