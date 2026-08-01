from pydantic import Field

from app.core.base_model import CamelModel
from app.core.object_id import PyObjectId


class NewExcelFileRequest(CamelModel):
    filename: str


class BulkSaveRequest(CamelModel):
    """ "Save All" on a documents page - the frontend sends exactly the
    document ids currently rendered on that page (already paginated
    server-side at 30/page), never the user's whole dataset. max_length
    guards the endpoint itself against a manipulated request past the UI."""

    document_ids: list[PyObjectId] = Field(min_length=1, max_length=200)
