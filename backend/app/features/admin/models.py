from typing import Any

from app.core.base_model import MongoBaseModel
from app.core.object_id import PyObjectId


class AuditLog(MongoBaseModel):
    """Append-only trail hooked into auth + key document actions. Not
    backfilled - no history exists from before this model existed."""

    user_id: PyObjectId
    action: str
    context: dict[str, Any] = {}
