from datetime import UTC, datetime

from bson import ObjectId

from app.core.database import get_database


async def record_orphaned_file(
    grid_fs_file_id: ObjectId,
    document_id: ObjectId | None,
    user_id: ObjectId | None,
    context: str,
    exc: Exception,
) -> None:
    """Called wherever a GridFS delete_file() call fails, instead of a bare
    except-pass - the surrounding document/user-facing delete action still
    proceeds and succeeds as before (this never raises), but the failure is
    now tracked instead of silently discarded. Upserts keyed by
    gridFsFileId (unique index, see database.py) so a repeated failure on
    the SAME file (e.g. a retry that fails again) updates the existing
    record in place rather than creating a duplicate."""
    db = get_database()
    now = datetime.now(UTC)
    await db.orphanedfiles.update_one(
        {"gridFsFileId": grid_fs_file_id},
        {
            "$set": {
                "documentId": document_id,
                "userId": user_id,
                "context": context,
                "errorType": type(exc).__name__,
                "errorMessage": str(exc),
                "updatedAt": now,
            },
            "$setOnInsert": {"createdAt": now},
            "$inc": {"attemptCount": 1},
        },
        upsert=True,
    )
