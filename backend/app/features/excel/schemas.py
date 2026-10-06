import re

from pydantic import Field, field_validator

from app.core.base_model import CamelModel
from app.core.object_id import PyObjectId

# Path-steering and Windows-invalid characters (plus control characters).
_BAD_WORKBOOK_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


class NewExcelFileRequest(CamelModel):
    filename: str

    @field_validator("filename")
    @classmethod
    def _valid_workbook_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("filename is required.")
        if len(name) > 100:
            raise ValueError("Workbook name must be 100 characters or fewer.")
        if ".." in name or _BAD_WORKBOOK_NAME.search(name) or name.endswith("."):
            raise ValueError(
                'Workbook name cannot contain / \\ : * ? " < > | or "..", or end with a dot.'
            )
        return name


class BulkSaveRequest(CamelModel):
    """ "Save All" on a documents page - the frontend sends exactly the
    document ids currently rendered on that page (already paginated
    server-side at 30/page), never the user's whole dataset. max_length
    guards the endpoint itself against a manipulated request past the UI."""

    document_ids: list[PyObjectId] = Field(min_length=1, max_length=200)
