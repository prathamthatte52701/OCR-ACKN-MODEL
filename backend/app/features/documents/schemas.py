from typing import Literal

from app.core.base_model import CamelModel


class CorrectRequest(CamelModel):
    field: str
    value: str


class DocumentOut(CamelModel):
    id: str
    user_id: str
    auto_name: str
    original_filename: str
    mime_type: str
    size: int
    upload_status: str
    document_type: str
    tax_invoice_no: str | None = None
    reference_no: str | None = None
    number: str | None = None
    date: str | None = None
    tax_invoice_no_confidence: float | None = None
    reference_no_confidence: float | None = None
    number_confidence: float | None = None
    date_confidence: float | None = None
    edited: bool
    processing_error: str | None = None


class MessageResponse(CamelModel):
    message: str


class ConfirmedDeleteRequest(CamelModel):
    """Shared confirmation gate for irreversible bulk-delete actions:
    re-entering the account password plus a typed confirmation phrase
    (checked against a per-action expected value in the router). There is no
    email/OTP channel anywhere in this app (see CLAUDE.md), so this is the
    whole gate - no separate token/one-time-key mechanism."""

    password: str
    confirmation_phrase: str


class PurgeRangeRequest(ConfirmedDeleteRequest):
    """Exactly one of older_than_months/year must be set - validated in the
    router (single source of truth, shared with the read-only preview
    endpoint's query params)."""

    older_than_months: Literal[3, 6, 9] | None = None
    year: int | None = None
