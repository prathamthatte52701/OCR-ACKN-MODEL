"""The ONE set of rules for a manual field correction, shared by the user route
(documents/router.py) and the admin route (admin/router.py) so they cannot drift."""

import re
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException

from app.features.documents.correction import correction_set_fields
from app.features.ocr.extraction import normalize_date_to_ddmmyyyy

CORRECTABLE_NUMBER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ./_-]{0,39}$")
EDITABLE_FIELDS = {"taxInvoiceNo", "referenceNo", "number", "date"}
FIELDS_BY_DOCUMENT_TYPE = {
    "Tax Invoice": {"taxInvoiceNo", "referenceNo", "date"},
    "Delivery Challan": {"number", "date"},
}
CHANGED_MSG = "This document changed while you were editing. Please reload and try again."


def check_request(field: str, value: str | None) -> None:
    """Checks that need no document (run before the lookup, so they win over a 404)."""
    if field not in EDITABLE_FIELDS:
        raise HTTPException(status_code=400, detail="That field cannot be edited.")
    if not value or not value.strip():
        raise HTTPException(status_code=400, detail="Please enter a value before saving.")


def validate_correction(doc: dict, field: str, raw_value: str) -> str:
    """Returns the cleaned value to store, or raises 409 / 400."""
    # A document still mid-OCR can flip to 'processed' right after it is read and silently
    # overwrite a correction made in that window - block until processing has finished.
    if doc["uploadStatus"] not in ("processed", "failed"):
        raise HTTPException(
            status_code=409,
            detail=(
                "This document is still being processed. "
                "Please wait for it to finish before editing."
            ),
        )
    if field not in FIELDS_BY_DOCUMENT_TYPE[doc["documentType"]]:
        raise HTTPException(
            status_code=400,
            detail=f"That field cannot be edited on a {doc['documentType']} document.",
        )
    value = raw_value.strip()
    if field == "date":
        normalized = normalize_date_to_ddmmyyyy(value)
        if not normalized:
            raise HTTPException(
                status_code=400, detail="Enter a real date in DD/MM/YYYY format (year 2000-2100)."
            )
        return normalized
    if not CORRECTABLE_NUMBER_RE.match(value):
        # Letters/digits (plus - / . _ and spaces), 1-40 chars: blocks huge strings, <script>,
        # control characters (500 on Excel save) and "=HYPERLINK(...)" formulas.
        raise HTTPException(
            status_code=400,
            detail=(
                "Number can only contain letters, digits, spaces and - / . _ "
                "(max 40 characters)."
            ),
        )
    return value


async def apply_correction(db: Any, doc: dict, field: str, value: str) -> bool:
    """Write the value ONLY if the document is still exactly as it was read (same
    processingRunId, finished). False = it changed (e.g. Reprocess started): nothing was
    written, so the caller must not audit. The corrections row is added only after the
    document write matched."""
    now = datetime.now(UTC)
    # None matches both a missing and a null processingRunId.
    result = await db.documents.update_one(
        {
            "_id": doc["_id"],
            "processingRunId": doc.get("processingRunId"),
            "uploadStatus": {"$in": ["processed", "failed"]},
        },
        {"$set": correction_set_fields(field, value, now)},
    )
    if result.matched_count == 0:
        return False
    await db.corrections.insert_one(
        {
            "documentId": doc["_id"],
            "fieldLabel": field,
            "fieldKey": field,
            "oldValue": doc.get(field),
            "newValue": value,
            "correctedAt": now,
            "createdAt": now,
            "updatedAt": now,
        }
    )
    return True
