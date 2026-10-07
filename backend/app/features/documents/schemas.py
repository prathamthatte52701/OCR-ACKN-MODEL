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


class DeleteResponse(MessageResponse):
    """Same gridFsCleanupFailed contract as PurgeFileResponse - "Delete" now
    permanently removes both the GridFS file and the Document record, and a
    GridFS failure doesn't block that (the record is still removed either
    way), it's just flagged for the frontend to show a softer message."""

    grid_fs_cleanup_failed: bool = False
