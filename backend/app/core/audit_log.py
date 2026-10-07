from datetime import UTC, datetime
from typing import Any

from bson import ObjectId

from app.core.database import get_database


async def log_action(user_id: ObjectId, action: str, context: dict[str, Any] | None = None) -> None:
    db = get_database()
    await db.auditlogs.insert_one(
        {
            "userId": user_id,
            "action": action,
            "context": context or {},
            "createdAt": datetime.now(UTC),
            "updatedAt": datetime.now(UTC),
        }
    )


ADMIN_ACCESS_ACTION = "admin_access"


async def log_admin_access(
    admin_id: ObjectId,
    target_user_id: ObjectId | None,
    resource: str,
    action: str,
    resource_id: ObjectId | None = None,
) -> None:
    """Records that an admin opened, listed or downloaded someone else's data
    (documents, images, export rows, workbooks). `target_user_id` is None when
    the view spans all users. Looking at your own data is not logged."""
    if target_user_id is not None and target_user_id == admin_id:
        return
    await log_action(
        admin_id,
        ADMIN_ACCESS_ACTION,
        {
            "adminId": str(admin_id),
            "targetUserId": str(target_user_id) if target_user_id else None,
            "resource": resource,
            "action": action,
            "resourceId": str(resource_id) if resource_id else None,
        },
    )
