"""Shared core for every admin nuke-delete variant (user-scoped age-based,
global age-based, global year+month). Lifted out of the old user-facing
purge routes (documents/router.py) unchanged in behavior - only the caller
changed (admin instead of the account owner) and the scope became
parameterizable (a single user vs every user)."""

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Protocol

from bson import ObjectId
from fastapi import HTTPException

from app.core.audit_log import log_action
from app.core.database import get_database
from app.core.security import verify_password
from app.features.auth.dependencies import CurrentUser
from app.features.excel import service as excel_service


class ConfirmedDeleteBody(Protocol):
    password: str
    confirm_password: str
    confirmation_phrase: str


async def verify_delete_confirmation(
    current_user: CurrentUser,
    body: ConfirmedDeleteBody,
    expected_phrase: str,
    blocked_action: str,
) -> None:
    """Re-fetches the ADMIN performing the action (never trusts anything off
    the JWT) and requires the admin's own password twice (must match) plus an
    exact typed phrase - there's no email/OTP channel anywhere in this app
    (see CLAUDE.md). Every blocked attempt is audit-logged before raising;
    the caller logs the success case itself once the delete completes. 400,
    not 401, for password failures - a 401 outside /auth/* force-clears the
    admin's token and bounces to login mid-dialog (see client.js/admin api.js
    interceptors)."""
    if body.password != body.confirm_password:
        await log_action(current_user.id, blocked_action, {"reason": "password_mismatch"})
        raise HTTPException(status_code=400, detail="Passwords do not match.")

    db = get_database()
    user = await db.users.find_one({"_id": current_user.id})
    if not user or "passwordHash" not in user:
        await log_action(current_user.id, blocked_action, {"reason": "no_password"})
        raise HTTPException(
            status_code=400,
            detail="This account uses Google Sign-In - there's no password to confirm with.",
        )
    if not verify_password(body.password, user["passwordHash"]):
        await log_action(current_user.id, blocked_action, {"reason": "wrong_password"})
        raise HTTPException(status_code=400, detail="Incorrect password.")
    if body.confirmation_phrase != expected_phrase:
        await log_action(current_user.id, blocked_action, {"reason": "wrong_phrase"})
        raise HTTPException(
            status_code=400, detail=f'Confirmation phrase must be exactly "{expected_phrase}".'
        )


def build_age_filter(user_id: ObjectId | None, older_than_months: int) -> tuple[dict, datetime]:
    """Oldest-first age-bucket filter, on createdAt (upload time) - same
    convention the prior user-facing purge-range used. `user_id=None` means
    every user (the admin-dashboard global mode); a real ObjectId scopes to
    exactly that one user (the per-user admin mode) - same underlying filter
    shape either way, just with or without the userId key, matching this
    codebase's existing idiom for admin cross-user queries (see
    admin/router.py's list_documents/list_exports/list_logs)."""
    if older_than_months not in (1, 2, 3, 6, 9):
        raise HTTPException(status_code=400, detail="olderThanMonths must be 1, 2, 3, 6, or 9.")
    filter_query: dict = {"isDeleted": {"$ne": True}}
    if user_id is not None:
        filter_query["userId"] = user_id
    range_end = datetime.now(UTC) - timedelta(days=older_than_months * 30)
    filter_query["createdAt"] = {"$lt": range_end}
    return filter_query, range_end


def build_months_filter(year: int, months: Sequence[int]) -> dict:
    """Precise calendar-range filter: exact year + one or more specific
    months, ANDed together via $or of per-month [start, end) windows on the
    same createdAt field build_age_filter uses. Always global (no userId key)
    - this mode has no per-user variant, by design."""
    if not months:
        raise HTTPException(status_code=400, detail="Select at least one month.")
    ranges = []
    for month in sorted(set(months)):
        start = datetime(year, month, 1, tzinfo=UTC)
        end = (
            datetime(year + 1, 1, 1, tzinfo=UTC)
            if month == 12
            else datetime(year, month + 1, 1, tzinfo=UTC)
        )
        ranges.append({"createdAt": {"$gte": start, "$lt": end}})
    return {"isDeleted": {"$ne": True}, "$or": ranges}


async def remove_exported_rows_from_workbooks(
    exported_rows: list[dict],
) -> tuple[int, list[str]]:
    """Groups the exported-row records being purged by workbookId, surgically
    removes just those rows from each workbook's physical .xlsx (matching by
    (documentType, formatted-number, date) - rows have no stable ID, same
    convention as excel/service.py's append path), and reports which
    workbooks ended up with zero data rows left across every sheet (deleted
    from disk entirely rather than left as an empty shell). Already
    user-agnostic - workbookId alone determines which physical file a row
    belongs to, so this works unchanged whether the purged rows span one
    user or every user."""
    by_workbook: dict[ObjectId, list[dict]] = defaultdict(list)
    for row in exported_rows:
        if row.get("workbookId"):
            by_workbook[row["workbookId"]].append(row)

    db = get_database()
    total_removed = 0
    fully_deleted_filenames: list[str] = []
    now = datetime.now(UTC)
    for workbook_id, rows in by_workbook.items():
        wb = await db.workbooks.find_one({"_id": workbook_id})
        if not wb:
            continue
        physical_filename = f"{wb['userId']}_{wb['filename']}"
        removed, fully_empty = await excel_service.remove_rows(physical_filename, rows)
        total_removed += removed
        if fully_empty:
            fully_deleted_filenames.append(wb["filename"])
            await db.workbooks.update_one(
                {"_id": workbook_id},
                {"$set": {"isActive": False, "archivedAt": now, "updatedAt": now}},
            )
    return total_removed, fully_deleted_filenames
