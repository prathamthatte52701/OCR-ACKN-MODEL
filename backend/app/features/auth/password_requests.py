"""Admin-handled password reset: the open-request upsert used by the public route."""

import re
from datetime import UTC, datetime

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from app.core.audit_log import log_action
from app.features.auth.dependencies import STATUS_APPROVED

GENERIC_RESET_MESSAGE = "If this account exists, the admin has been told."
COLLECTION = "passwordresetrequests"
# Control chars, C1 controls, zero-width/bidi marks, U+2028/2029, bidi overrides/isolates, BOM:
# none of them may disguise or reflow what the admin reads.
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2060-\u206f\ufeff]")


def sanitize_note(note: str | None) -> str:
    return _CONTROL_RE.sub("", note or "").strip()[:200]


def can_request_reset(user: dict | None) -> bool:
    """Approved, non-admin, has a real password (so not Google-only). Missing status = approved."""
    return bool(
        user
        and user.get("role") != "admin"
        and user.get("passwordHash")
        and user.get("status", STATUS_APPROVED) == STATUS_APPROVED
    )


async def _upsert_open(db: AsyncIOMotorDatabase, user: dict, note: str) -> None:
    now = datetime.now(UTC)
    flt = {"userId": user["_id"], "status": "open"}
    update = {
        "$set": {
            "email": user["email"],
            "username": user["username"],
            "note": note,
            "updatedAt": now,
        },
        "$setOnInsert": {
            "createdAt": now,
            "resolution": None,
            "resolvedAt": None,
            "resolvedBy": None,
        },
    }
    try:
        await db[COLLECTION].find_one_and_update(flt, update, upsert=True)
    except DuplicateKeyError:
        # Lost the race against a concurrent first request: the row exists now, update it.
        await db[COLLECTION].find_one_and_update(flt, update, upsert=True)


async def handle_reset_request(
    db: AsyncIOMotorDatabase, user: dict | None, note: str, eligible: bool
) -> None:
    """Same number of awaits whether or not anything is created (no timing/existence oracle)."""
    if eligible and user is not None:
        await _upsert_open(db, user, note)
        await log_action(user["_id"], "PASSWORD_RESET_REQUESTED", {})
    else:
        await db[COLLECTION].update_one({"_id": ObjectId()}, {"$set": {"updatedAt": 0}})
        await db[COLLECTION].update_one({"_id": ObjectId()}, {"$set": {"updatedAt": 0}})
