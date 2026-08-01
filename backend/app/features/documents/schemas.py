from pydantic import Field

from app.core.base_model import CamelModel
from app.core.object_id import PyObjectId


class CorrectRequest(CamelModel):
    field: str
    value: str


class DownloadAllRequest(CamelModel):
    """ "Download All" on a documents page - same page-scoping contract as
    BulkSaveRequest (excel/schemas.py): the frontend sends exactly the
    document ids currently rendered on that page, never the user's whole
    dataset. max_length guards the endpoint itself against a manipulated
    request past the UI."""

    document_ids: list[PyObjectId] = Field(min_length=1, max_length=200)


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


class PurgeFileResponse(MessageResponse):
    """gridFsCleanupFailed lets the frontend distinguish a fully-clean purge
    from one where the document's metadata was purged successfully but the
    underlying GridFS binary couldn't be removed (tracked in orphanedfiles,
    see app.core.orphaned_files) - the action itself still succeeded from
    the user's perspective, this is purely an extra signal for the UI to
    show a softer "flagged for admin review" message instead of the normal
    success toast."""

    grid_fs_cleanup_failed: bool = False
