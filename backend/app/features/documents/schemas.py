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


class PurgeFileResponse(MessageResponse):
    """gridFsCleanupFailed lets the frontend distinguish a fully-clean purge
    from one where the document's metadata was purged successfully but the
    underlying GridFS binary couldn't be removed (tracked in orphanedfiles,
    see app.core.orphaned_files) - the action itself still succeeded from
    the user's perspective, this is purely an extra signal for the UI to
    show a softer "flagged for admin review" message instead of the normal
    success toast."""

    grid_fs_cleanup_failed: bool = False
