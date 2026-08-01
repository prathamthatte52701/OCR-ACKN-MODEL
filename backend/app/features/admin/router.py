from datetime import UTC, datetime, timedelta

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse

from app.core.audit_log import log_action
from app.core.database import get_database
from app.core.object_id import PyObjectId
from app.core.orphaned_files import record_orphaned_file
from app.core.rate_limit import limiter, user_or_ip_key
from app.core.validators import (
    normalize_email,
    normalize_username,
    validate_email,
    validate_username,
)
from app.features.admin import purge_service
from app.features.admin.schemas import (
    AdminAgeRangeRequest,
    AdminMonthsRequest,
    AdminUpdateUserRequest,
)
from app.features.auth.dependencies import CurrentUser, require_admin
from app.features.documents.gridfs_service import delete_file
from app.features.documents.schemas import CorrectRequest
from app.features.excel import service as excel_service
from app.features.ocr.extraction import normalize_date_to_ddmmyyyy

router = APIRouter()

# Every nuke-delete variant (per-user age-based, global age-based, global
# year+month) shares ONE 5-attempts/24h budget per admin account, not 5
# separate budgets per mode - slowapi's plain @limiter.limit gives each
# decorated endpoint its own independent bucket even with an identical limit
# string, so this requires shared_limit() with an explicit shared `scope`
# (see slowapi/extension.py - the storage key is (key_func result, scope),
# and scope defaults to the endpoint's own function name unless given).
NUKE_RATE_LIMIT = "5/24hour"
NUKE_RATE_SCOPE = "admin_nuke"

EDITABLE_FIELDS = {"taxInvoiceNo", "referenceNo", "number", "date"}
FIELDS_BY_DOCUMENT_TYPE = {
    "Tax Invoice": {"taxInvoiceNo", "referenceNo", "date"},
    "Delivery Challan": {"number", "date"},
}


def _physical_workbook_filename(user_id: ObjectId, filename: str) -> str:
    return f"{user_id}_{filename}"


def _pagination(
    page: int | None, limit: int | None, default_limit: int = 30
) -> tuple[int, int, int]:
    limit = max(1, limit or default_limit)
    page = max(1, page or 1)
    return limit, page, (page - 1) * limit


def _serialize_user(user: dict) -> dict:
    return {
        "id": str(user["_id"]),
        "username": user["username"],
        "email": user["email"],
        "role": user["role"],
        "tokenVersion": user["tokenVersion"],
        "authProvider": user.get("authProvider", "local"),
        "createdAt": user.get("createdAt"),
        "updatedAt": user.get("updatedAt"),
    }


def _serialize_document(doc: dict, owner: dict | None = None) -> dict:
    out = {k: v for k, v in doc.items() if k != "ocrTextHidden"}
    out["_id"] = str(out["_id"])
    out["userId"] = str(out["userId"])
    if out.get("gridFsFileId"):
        out["gridFsFileId"] = str(out["gridFsFileId"])
    if owner:
        out["owner"] = {
            "id": str(owner["_id"]),
            "username": owner["username"],
            "email": owner["email"],
        }
    return out


@router.get("/ping")
async def ping(current_user: CurrentUser = Depends(require_admin)) -> dict:
    return {"ok": True, "admin": True}


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


@router.get("/users")
async def list_users(
    page: int | None = Query(default=None),
    limit: int | None = Query(default=None),
    current_user: CurrentUser = Depends(require_admin),
) -> dict:
    db = get_database()
    lim, pg, skip = _pagination(page, limit)
    total_users = await db.users.count_documents({})
    cursor = db.users.find({}, {"passwordHash": 0}).sort("createdAt", -1).skip(skip).limit(lim)
    users = [_serialize_user(u) async for u in cursor]
    return {
        "users": users,
        "totalUsers": total_users,
        "totalPages": max(1, -(-total_users // lim)),
        "currentPage": pg,
    }


@router.get("/users/{user_id}")
async def get_user(user_id: PyObjectId, current_user: CurrentUser = Depends(require_admin)) -> dict:
    db = get_database()
    user = await db.users.find_one({"_id": user_id}, {"passwordHash": 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return {"user": _serialize_user(user)}


@router.patch("/users/{user_id}")
async def update_user(
    user_id: PyObjectId,
    body: AdminUpdateUserRequest,
    current_user: CurrentUser = Depends(require_admin),
) -> dict:
    db = get_database()
    user = await db.users.find_one({"_id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    updates: dict = {}
    if body.username is not None:
        username = normalize_username(body.username)
        if err := validate_username(username):
            raise HTTPException(status_code=400, detail=err)
        updates["username"] = username

    if body.email is not None:
        email = normalize_email(body.email)
        if err := validate_email(email):
            raise HTTPException(status_code=400, detail=err)
        if email != user["email"]:
            existing = await db.users.find_one({"email": email})
            if existing:
                raise HTTPException(status_code=400, detail="That email is already in use.")
            updates["email"] = email

    if body.role is not None:
        updates["role"] = body.role

    if updates:
        updates["updatedAt"] = datetime.now(UTC)
        await db.users.update_one({"_id": user_id}, {"$set": updates})
        await log_action(
            current_user.id,
            "user_updated",
            {"targetUserId": str(user_id), "fields": list(updates.keys())},
        )
        refreshed = await db.users.find_one({"_id": user_id})
        assert refreshed is not None
        user = refreshed

    return {"user": _serialize_user(user)}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: PyObjectId, current_user: CurrentUser = Depends(require_admin)
) -> dict:
    """Cascade delete: every document (+ its GridFS file, corrections), every
    workbook (+ its .xlsx file on disk), every exported-row record, and the
    excel-state settings row - a clean removal rather than an orphaned trail,
    ported 1:1 from the old admin.js DELETE /users/:id."""
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account.")

    db = get_database()
    user = await db.users.find_one({"_id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    docs_cursor = db.documents.find({"userId": user_id}, {"_id": 1, "gridFsFileId": 1})
    docs = await docs_cursor.to_list(length=None)
    doc_ids = [d["_id"] for d in docs]

    for doc in docs:
        if doc.get("gridFsFileId"):
            try:
                await delete_file(doc["gridFsFileId"])
            except Exception as exc:  # noqa: BLE001
                await record_orphaned_file(
                    doc["gridFsFileId"], doc["_id"], user_id, "admin_cascade_delete", exc
                )

    await db.corrections.delete_many({"documentId": {"$in": doc_ids}})
    await db.documents.delete_many({"userId": user_id})
    await db.exportedrows.delete_many({"userId": user_id})

    workbooks_cursor = db.workbooks.find({"userId": user_id}, {"_id": 1, "filename": 1})
    workbooks = await workbooks_cursor.to_list(length=None)
    for wb in workbooks:
        target = excel_service.file_path(_physical_workbook_filename(user_id, wb["filename"]))
        if target.exists():
            try:
                target.unlink()
            except OSError:
                pass
    await db.workbooks.delete_many({"userId": user_id})
    await db.settings.delete_many({"userId": user_id})

    deleted_email = user["email"]
    await db.users.delete_one({"_id": user_id})

    await log_action(
        current_user.id,
        "user_deleted",
        {
            "targetUserId": str(user_id),
            "targetEmail": deleted_email,
            "documentsDeleted": len(doc_ids),
            "workbooksDeleted": len(workbooks),
        },
    )
    return {"message": "User and all associated data deleted successfully."}


async def _execute_purge(filter_query: dict) -> tuple[int, int, list[str]]:
    """Shared execution tail for every nuke variant below, once the filter is
    built and the confirmation gate has passed: delete each matched
    document's GridFS file, surgically remove its exported Excel rows (or
    the whole workbook if that empties it), then hard-delete the document
    and exportedrows records themselves. Returns
    (documentsDeleted, rowsRemoved, workbooksFullyDeleted)."""
    db = get_database()
    docs = await db.documents.find(filter_query).to_list(None)
    doc_ids = [d["_id"] for d in docs]

    for doc in docs:
        if doc.get("gridFsFileId"):
            try:
                await delete_file(doc["gridFsFileId"])
            except Exception as exc:  # noqa: BLE001
                await record_orphaned_file(
                    doc["gridFsFileId"], doc["_id"], doc.get("userId"), "admin_nuke_purge", exc
                )

    rows_removed = 0
    workbooks_fully_deleted: list[str] = []
    if doc_ids:
        exported_rows = await db.exportedrows.find({"documentId": {"$in": doc_ids}}).to_list(None)
        rows_removed, workbooks_fully_deleted = (
            await purge_service.remove_exported_rows_from_workbooks(exported_rows)
        )
        await db.documents.delete_many({"_id": {"$in": doc_ids}})
        await db.exportedrows.delete_many({"documentId": {"$in": doc_ids}})

    return len(doc_ids), rows_removed, workbooks_fully_deleted


@router.delete("/users/{user_id}/purge-range")
@limiter.shared_limit(NUKE_RATE_LIMIT, scope=NUKE_RATE_SCOPE, key_func=user_or_ip_key)
async def admin_purge_user_range(
    request: Request,
    user_id: PyObjectId,
    body: AdminAgeRangeRequest,
    current_user: CurrentUser = Depends(require_admin),
) -> dict:
    """ "Nuke This User" - age-based only (1/2/3/6/9 months, oldest-first),
    scoped strictly to this one user's data. Reuses the exact same
    confirmation gate, surgical row-removal mechanism, and rate limit as the
    two global variants below - only the filter's userId scope differs."""
    db = get_database()
    target = await db.users.find_one({"_id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="User not found.")

    filter_query, range_end = purge_service.build_age_filter(user_id, body.older_than_months)

    await log_action(
        current_user.id,
        "admin_nuke_user_range_attempted",
        {
            "mode": "age_range",
            "scope": "user",
            "targetUserId": str(user_id),
            "olderThanMonths": body.older_than_months,
        },
    )
    await purge_service.verify_delete_confirmation(
        current_user, body, "NUKE USER", "admin_nuke_user_range_blocked"
    )

    documents_deleted, rows_removed, workbooks_fully_deleted = await _execute_purge(filter_query)

    await log_action(
        current_user.id,
        "admin_nuke_user_range_data",
        {
            "mode": "age_range",
            "scope": "user",
            "targetUserId": str(user_id),
            "olderThanMonths": body.older_than_months,
            "dateRangeEnd": range_end,
            "documentsDeleted": documents_deleted,
            "rowsRemoved": rows_removed,
            "workbooksFullyDeleted": workbooks_fully_deleted,
        },
    )
    return {
        "message": f"{documents_deleted} document(s) permanently deleted for this user.",
        "documentsDeleted": documents_deleted,
        "workbooksFullyDeleted": workbooks_fully_deleted,
        "rowsRemoved": rows_removed,
    }


@router.delete("/users/{user_id}/purge-months")
@limiter.shared_limit(NUKE_RATE_LIMIT, scope=NUKE_RATE_SCOPE, key_func=user_or_ip_key)
async def admin_purge_user_months(
    request: Request,
    user_id: PyObjectId,
    body: AdminMonthsRequest,
    current_user: CurrentUser = Depends(require_admin),
) -> dict:
    """ "Nuke This User" - Year+Month mode: admin picks an exact year and one
    or more specific months; ONLY this one user's data in exactly those
    month(s) is deleted, everything else (other months/years of this user,
    every other user entirely) is untouched. Reuses the exact same
    confirmation gate, surgical row-removal mechanism, and rate limit as the
    global year+month variant below - only the filter's userId scope
    differs."""
    db = get_database()
    target = await db.users.find_one({"_id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="User not found.")

    filter_query = purge_service.build_months_filter(body.year, body.months, user_id)

    await log_action(
        current_user.id,
        "admin_nuke_user_months_attempted",
        {
            "mode": "year_months",
            "scope": "user",
            "targetUserId": str(user_id),
            "year": body.year,
            "months": body.months,
        },
    )
    await purge_service.verify_delete_confirmation(
        current_user, body, "NUKE USER MONTHS", "admin_nuke_user_months_blocked"
    )

    documents_deleted, rows_removed, workbooks_fully_deleted = await _execute_purge(filter_query)

    await log_action(
        current_user.id,
        "admin_nuke_user_months_data",
        {
            "mode": "year_months",
            "scope": "user",
            "targetUserId": str(user_id),
            "year": body.year,
            "months": body.months,
            "documentsDeleted": documents_deleted,
            "rowsRemoved": rows_removed,
            "workbooksFullyDeleted": workbooks_fully_deleted,
        },
    )
    return {
        "message": f"{documents_deleted} document(s) permanently deleted for this user.",
        "documentsDeleted": documents_deleted,
        "workbooksFullyDeleted": workbooks_fully_deleted,
        "rowsRemoved": rows_removed,
    }


@router.delete("/purge-range")
@limiter.shared_limit(NUKE_RATE_LIMIT, scope=NUKE_RATE_SCOPE, key_func=user_or_ip_key)
async def admin_purge_global_range(
    request: Request,
    body: AdminAgeRangeRequest,
    current_user: CurrentUser = Depends(require_admin),
) -> dict:
    """ "Global Nuke" - age-based mode: 1/2/3/6/9 months, oldest-first,
    applied across EVERY user's data simultaneously. Same body shape as the
    per-user variant above (build_age_filter(user_id=None, ...) is what
    turns this global instead of scoped)."""
    filter_query, range_end = purge_service.build_age_filter(None, body.older_than_months)

    await log_action(
        current_user.id,
        "admin_nuke_global_range_attempted",
        {"mode": "age_range", "scope": "global", "olderThanMonths": body.older_than_months},
    )
    await purge_service.verify_delete_confirmation(
        current_user, body, "NUKE ALL RANGE", "admin_nuke_global_range_blocked"
    )

    documents_deleted, rows_removed, workbooks_fully_deleted = await _execute_purge(filter_query)

    await log_action(
        current_user.id,
        "admin_nuke_global_range_data",
        {
            "mode": "age_range",
            "scope": "global",
            "olderThanMonths": body.older_than_months,
            "dateRangeEnd": range_end,
            "documentsDeleted": documents_deleted,
            "rowsRemoved": rows_removed,
            "workbooksFullyDeleted": workbooks_fully_deleted,
        },
    )
    return {
        "message": f"{documents_deleted} document(s) permanently deleted across all users.",
        "documentsDeleted": documents_deleted,
        "workbooksFullyDeleted": workbooks_fully_deleted,
        "rowsRemoved": rows_removed,
    }


@router.delete("/purge-months")
@limiter.shared_limit(NUKE_RATE_LIMIT, scope=NUKE_RATE_SCOPE, key_func=user_or_ip_key)
async def admin_purge_global_months(
    request: Request,
    body: AdminMonthsRequest,
    current_user: CurrentUser = Depends(require_admin),
) -> dict:
    """ "Global Nuke" - Year+Month mode: admin picks an exact year and one or
    more specific months; ALL users' data in exactly those month(s) is
    deleted, everything else (other months of the same year, every other
    user's data outside the range) is untouched. Always global - there is no
    per-user version of this mode."""
    filter_query = purge_service.build_months_filter(body.year, body.months)

    await log_action(
        current_user.id,
        "admin_nuke_global_months_attempted",
        {"mode": "year_months", "scope": "global", "year": body.year, "months": body.months},
    )
    await purge_service.verify_delete_confirmation(
        current_user, body, "NUKE ALL MONTHS", "admin_nuke_global_months_blocked"
    )

    documents_deleted, rows_removed, workbooks_fully_deleted = await _execute_purge(filter_query)

    await log_action(
        current_user.id,
        "admin_nuke_global_months_data",
        {
            "mode": "year_months",
            "scope": "global",
            "year": body.year,
            "months": body.months,
            "documentsDeleted": documents_deleted,
            "rowsRemoved": rows_removed,
            "workbooksFullyDeleted": workbooks_fully_deleted,
        },
    )
    return {
        "message": f"{documents_deleted} document(s) permanently deleted across all users.",
        "documentsDeleted": documents_deleted,
        "workbooksFullyDeleted": workbooks_fully_deleted,
        "rowsRemoved": rows_removed,
    }


# ---------------------------------------------------------------------------
# Documents (cross-user)
# ---------------------------------------------------------------------------


@router.get("/documents")
async def list_documents(
    user_id: str | None = Query(default=None, alias="userId"),
    page: int | None = Query(default=None),
    limit: int | None = Query(default=None),
    current_user: CurrentUser = Depends(require_admin),
) -> dict:
    db = get_database()
    lim, pg, skip = _pagination(page, limit)
    filt: dict = {"isDeleted": {"$ne": True}}
    if user_id:
        try:
            filt["userId"] = ObjectId(user_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid userId.") from None

    total_documents = await db.documents.count_documents(filt)
    cursor = db.documents.find(filt).sort("createdAt", -1).skip(skip).limit(lim)
    docs = await cursor.to_list(length=None)
    owner_ids = {d["userId"] for d in docs}
    owners = {
        o["_id"]: o
        async for o in db.users.find({"_id": {"$in": list(owner_ids)}}, {"username": 1, "email": 1})
    }
    documents = [_serialize_document(d, owners.get(d["userId"])) for d in docs]
    return {
        "documents": documents,
        "totalDocuments": total_documents,
        "totalPages": max(1, -(-total_documents // lim)),
        "currentPage": pg,
    }


@router.patch("/documents/{doc_id}")
async def correct_document_as_admin(
    doc_id: PyObjectId, body: CorrectRequest, current_user: CurrentUser = Depends(require_admin)
) -> dict:
    field = body.field
    value = body.value
    if field not in EDITABLE_FIELDS:
        raise HTTPException(status_code=400, detail="That field cannot be edited.")
    if not value or not value.strip():
        raise HTTPException(status_code=400, detail="Please enter a value before saving.")

    db = get_database()
    doc = await db.documents.find_one({"_id": doc_id, "isDeleted": {"$ne": True}})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    if field not in FIELDS_BY_DOCUMENT_TYPE[doc["documentType"]]:
        raise HTTPException(
            status_code=400,
            detail=f"That field cannot be edited on a {doc['documentType']} document.",
        )

    value = value.strip()
    if field == "date":
        normalized = normalize_date_to_ddmmyyyy(value)
        if not normalized:
            raise HTTPException(status_code=400, detail="Date must be in DD/MM/YYYY format.")
        value = normalized

    old_value = doc.get(field)
    now = datetime.now(UTC)
    await db.documents.update_one(
        {"_id": doc_id},
        {"$set": {field: value, "edited": True, f"{field}Confidence": 100, "updatedAt": now}},
    )
    await db.corrections.insert_one(
        {
            "documentId": doc_id,
            "fieldLabel": field,
            "fieldKey": field,
            "oldValue": old_value,
            "newValue": value,
            "correctedAt": now,
            "createdAt": now,
            "updatedAt": now,
        }
    )
    await log_action(
        current_user.id,
        "document_corrected",
        {"documentId": str(doc_id), "field": field, "byAdmin": True},
    )

    updated = await db.documents.find_one({"_id": doc_id})
    assert updated is not None
    return {"message": "Field corrected successfully.", "document": _serialize_document(updated)}


@router.delete("/documents/{doc_id}")
async def delete_document_as_admin(
    doc_id: PyObjectId, current_user: CurrentUser = Depends(require_admin)
) -> dict:
    """Admin equivalent of the user-scoped "Delete" action - full, permanent
    delete of both the GridFS file and the Document record (cross-user),
    same contract as documents/router.py::delete_document. No soft-delete/
    hidden state is ever set. ExportedRow/export-history entries are
    deliberately left untouched, same as the user-scoped route."""
    db = get_database()
    doc = await db.documents.find_one({"_id": doc_id, "isDeleted": {"$ne": True}})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    cleanup_failed = False
    if doc.get("gridFsFileId"):
        try:
            await delete_file(doc["gridFsFileId"])
        except Exception as exc:  # noqa: BLE001
            await record_orphaned_file(
                doc["gridFsFileId"], doc["_id"], doc["userId"], "admin_document_deleted", exc
            )
            cleanup_failed = True

    await db.documents.delete_one({"_id": doc_id})
    await log_action(
        current_user.id,
        "document_deleted",
        {"documentId": str(doc_id), "ownerUserId": str(doc["userId"]), "byAdmin": True},
    )
    message = (
        "Document permanently deleted."
        if not cleanup_failed
        else (
            "Document permanently deleted, but the original file could not be fully cleaned "
            "up from storage. Flagged in Orphaned Files for follow-up."
        )
    )
    return {"message": message, "gridFsCleanupFailed": cleanup_failed}


@router.post("/documents/{doc_id}/purge-file")
async def purge_document_file_as_admin(
    doc_id: PyObjectId, current_user: CurrentUser = Depends(require_admin)
) -> dict:
    """Admin equivalent of the user-scoped "File Delete" action - permanently
    removes the stored original file from GridFS, cross-user, leaving the
    Document record's extracted metadata untouched. A GridFS failure does
    NOT block the admin's action (filePurged is still set) - it's tracked
    in orphanedfiles and surfaced via gridFsCleanupFailed, same contract as
    the user-scoped purge-file endpoint."""
    db = get_database()
    doc = await db.documents.find_one({"_id": doc_id, "isDeleted": {"$ne": True}})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    if doc.get("filePurged"):
        raise HTTPException(
            status_code=400, detail="This document's original file has already been removed."
        )
    if not doc.get("gridFsFileId"):
        raise HTTPException(status_code=400, detail="No original file is stored for this document.")

    cleanup_failed = False
    try:
        await delete_file(doc["gridFsFileId"])
    except Exception as exc:  # noqa: BLE001
        await record_orphaned_file(
            doc["gridFsFileId"], doc["_id"], doc["userId"], "admin_purge_file", exc
        )
        cleanup_failed = True

    now = datetime.now(UTC)
    await db.documents.update_one(
        {"_id": doc_id}, {"$set": {"filePurged": True, "filePurgedAt": now, "updatedAt": now}}
    )
    await log_action(
        current_user.id,
        "document_file_purged",
        {"documentId": str(doc_id), "ownerUserId": str(doc["userId"]), "byAdmin": True},
    )
    message = (
        "Original file permanently removed. Extracted data remains fully accessible."
        if not cleanup_failed
        else (
            "Document data was removed, but the original file could not be fully cleaned up "
            "from storage. Flagged in Orphaned Files for follow-up."
        )
    )
    return {"message": message, "gridFsCleanupFailed": cleanup_failed}


# ---------------------------------------------------------------------------
# Orphaned files (GridFS deletions that failed and were tracked instead of
# silently swallowed - see app.core.orphaned_files.record_orphaned_file)
# ---------------------------------------------------------------------------


def _serialize_orphaned_file(record: dict, owner: dict | None) -> dict:
    return {
        "id": str(record["_id"]),
        "gridFsFileId": str(record["gridFsFileId"]),
        "documentId": str(record["documentId"]) if record.get("documentId") else None,
        "userId": str(record["userId"]) if record.get("userId") else None,
        "context": record.get("context"),
        "errorType": record.get("errorType"),
        "errorMessage": record.get("errorMessage"),
        "attemptCount": record.get("attemptCount", 1),
        "createdAt": record.get("createdAt"),
        "updatedAt": record.get("updatedAt"),
        "owner": (
            {"id": str(owner["_id"]), "username": owner["username"], "email": owner["email"]}
            if owner
            else None
        ),
    }


@router.get("/orphaned-files")
async def list_orphaned_files(
    page: int | None = Query(default=None),
    limit: int | None = Query(default=None),
    current_user: CurrentUser = Depends(require_admin),
) -> dict:
    db = get_database()
    lim, pg, skip = _pagination(page, limit)
    total = await db.orphanedfiles.count_documents({})
    cursor = db.orphanedfiles.find({}).sort("createdAt", -1).skip(skip).limit(lim)
    records = await cursor.to_list(length=None)
    owner_ids = {r["userId"] for r in records if r.get("userId")}
    owners = {
        o["_id"]: o
        async for o in db.users.find({"_id": {"$in": list(owner_ids)}}, {"username": 1, "email": 1})
    }
    return {
        "orphanedFiles": [
            _serialize_orphaned_file(r, owners.get(r.get("userId"))) for r in records
        ],
        "totalOrphanedFiles": total,
        "totalPages": max(1, -(-total // lim)),
        "currentPage": pg,
    }


@router.post("/orphaned-files/{orphan_id}/retry")
async def retry_orphaned_file(
    orphan_id: PyObjectId, current_user: CurrentUser = Depends(require_admin)
) -> dict:
    """Re-attempts the GridFS delete. Success removes the tracking record
    entirely; failure updates it in place (record_orphaned_file upserts by
    gridFsFileId) with the new error/timestamp rather than duplicating it."""
    db = get_database()
    record = await db.orphanedfiles.find_one({"_id": orphan_id})
    if not record:
        raise HTTPException(status_code=404, detail="Orphaned file record not found.")

    try:
        await delete_file(record["gridFsFileId"])
    except Exception as exc:  # noqa: BLE001
        await record_orphaned_file(
            record["gridFsFileId"],
            record.get("documentId"),
            record.get("userId"),
            record.get("context") or "retry",
            exc,
        )
        await log_action(
            current_user.id, "orphaned_file_retry_failed", {"orphanId": str(orphan_id)}
        )
        return {"success": False, "message": "Retry failed - this file still could not be deleted."}

    await db.orphanedfiles.delete_one({"_id": orphan_id})
    await log_action(current_user.id, "orphaned_file_retry_succeeded", {"orphanId": str(orphan_id)})
    return {"success": True, "message": "File deleted successfully. Removed from Orphaned Files."}


@router.delete("/orphaned-files/{orphan_id}")
async def dismiss_orphaned_file(
    orphan_id: PyObjectId, current_user: CurrentUser = Depends(require_admin)
) -> dict:
    """Removes the tracking record without attempting another delete - for
    when an admin has verified/handled the file some other way."""
    db = get_database()
    result = await db.orphanedfiles.delete_one({"_id": orphan_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Orphaned file record not found.")
    await log_action(current_user.id, "orphaned_file_dismissed", {"orphanId": str(orphan_id)})
    return {"message": "Orphaned file record dismissed."}


# ---------------------------------------------------------------------------
# Workbooks (cross-user)
# ---------------------------------------------------------------------------


@router.get("/workbooks")
async def list_workbooks_admin(current_user: CurrentUser = Depends(require_admin)) -> dict:
    db = get_database()
    cursor = db.workbooks.find({}).sort([("year", -1), ("createdAt", -1)])
    workbooks = await cursor.to_list(length=None)
    owner_ids = {wb["userId"] for wb in workbooks}
    owners = {
        o["_id"]: o
        async for o in db.users.find({"_id": {"$in": list(owner_ids)}}, {"username": 1, "email": 1})
    }
    out = []
    for wb in workbooks:
        owner = owners.get(wb["userId"])
        out.append(
            {
                "id": str(wb["_id"]),
                "userId": str(wb["userId"]),
                "year": wb["year"],
                "filename": wb["filename"],
                "isActive": wb["isActive"],
                "archivedAt": wb.get("archivedAt"),
                "owner": (
                    {
                        "id": str(owner["_id"]),
                        "username": owner["username"],
                        "email": owner["email"],
                    }
                    if owner
                    else None
                ),
            }
        )
    return {"workbooks": out}


@router.get("/workbooks/{workbook_id}/download")
async def download_workbook_admin(
    workbook_id: PyObjectId, current_user: CurrentUser = Depends(require_admin)
) -> FileResponse:
    db = get_database()
    wb = await db.workbooks.find_one({"_id": workbook_id})
    if not wb:
        raise HTTPException(status_code=404, detail="Workbook not found.")

    target = excel_service.file_path(_physical_workbook_filename(wb["userId"], wb["filename"]))
    if not target.exists():
        raise HTTPException(status_code=404, detail="Workbook file not found on the server.")

    download_name = wb["filename"] if wb["filename"].endswith(".xlsx") else f"{wb['filename']}.xlsx"
    return FileResponse(
        path=target,
        filename=download_name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ---------------------------------------------------------------------------
# Exports (cross-user)
# ---------------------------------------------------------------------------


@router.get("/exports")
async def list_exports_admin(
    user_id: str | None = Query(default=None, alias="userId"),
    page: int | None = Query(default=None),
    limit: int | None = Query(default=None),
    current_user: CurrentUser = Depends(require_admin),
) -> dict:
    db = get_database()
    lim, pg, skip = _pagination(page, limit)
    filt: dict = {}
    if user_id:
        try:
            filt["userId"] = ObjectId(user_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid userId.") from None

    total_exports = await db.exportedrows.count_documents(filt)
    cursor = db.exportedrows.find(filt).sort("exportedAt", -1).skip(skip).limit(lim)
    rows = await cursor.to_list(length=None)
    workbook_ids = {r["workbookId"] for r in rows if r.get("workbookId")}
    workbooks = {
        w["_id"]: w
        async for w in db.workbooks.find(
            {"_id": {"$in": list(workbook_ids)}}, {"filename": 1, "year": 1}
        )
    }
    out = []
    for r in rows:
        wb = workbooks.get(r.get("workbookId"))
        out.append(
            {
                "id": str(r["_id"]),
                "documentId": str(r["documentId"]),
                "userId": str(r["userId"]),
                "workbook": {"filename": wb["filename"], "year": wb["year"]} if wb else None,
                "documentType": r["documentType"],
                "taxInvoiceNo": r.get("taxInvoiceNo"),
                "referenceNo": r.get("referenceNo"),
                "number": r.get("number"),
                "date": r.get("date"),
                "exportedAt": r["exportedAt"],
            }
        )
    return {
        "exports": out,
        "totalExports": total_exports,
        "totalPages": max(1, -(-total_exports // lim)),
        "currentPage": pg,
    }


# ---------------------------------------------------------------------------
# Audit logs
# ---------------------------------------------------------------------------


@router.get("/logs")
async def list_logs(
    action: str | None = Query(default=None),
    user_id: str | None = Query(default=None, alias="userId"),
    page: int | None = Query(default=None),
    limit: int | None = Query(default=None),
    current_user: CurrentUser = Depends(require_admin),
) -> dict:
    db = get_database()
    lim, pg, skip = _pagination(page, limit)
    filt: dict = {}
    if action:
        filt["action"] = action
    if user_id:
        try:
            filt["userId"] = ObjectId(user_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid userId.") from None

    total_logs = await db.auditlogs.count_documents(filt)
    cursor = db.auditlogs.find(filt).sort("createdAt", -1).skip(skip).limit(lim)
    logs = await cursor.to_list(length=None)
    owner_ids = {log_["userId"] for log_ in logs}
    owners = {
        o["_id"]: o
        async for o in db.users.find({"_id": {"$in": list(owner_ids)}}, {"username": 1, "email": 1})
    }
    out = []
    for log_ in logs:
        owner = owners.get(log_["userId"])
        out.append(
            {
                "id": str(log_["_id"]),
                "action": log_["action"],
                "context": log_.get("context", {}),
                "createdAt": log_.get("createdAt"),
                "user": (
                    {
                        "id": str(owner["_id"]),
                        "username": owner["username"],
                        "email": owner["email"],
                    }
                    if owner
                    else None
                ),
            }
        )
    return {
        "logs": out,
        "totalLogs": total_logs,
        "totalPages": max(1, -(-total_logs // lim)),
        "currentPage": pg,
    }


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------


@router.get("/telemetry")
async def telemetry(current_user: CurrentUser = Depends(require_admin)) -> dict:
    db = get_database()
    now = datetime.now(UTC)
    day_ago = now - timedelta(hours=24)
    week_ago = now - timedelta(days=7)

    total_users = await db.users.count_documents({})
    docs = await db.documents.find(
        {"isDeleted": {"$ne": True}}, {"uploadStatus": 1, "documentType": 1}
    ).to_list(length=None)
    total_exports = await db.exportedrows.count_documents({})
    activity_24h = await db.auditlogs.count_documents({"createdAt": {"$gte": day_ago}})
    activity_7d = await db.auditlogs.count_documents({"createdAt": {"$gte": week_ago}})

    by_status = {"uploaded": 0, "processed": 0, "failed": 0}
    by_type = {"Tax Invoice": 0, "Delivery Challan": 0}
    for d in docs:
        if d["uploadStatus"] in by_status:
            by_status[d["uploadStatus"]] += 1
        if d["documentType"] in by_type:
            by_type[d["documentType"]] += 1

    finished = by_status["processed"] + by_status["failed"]
    ocr_failure_rate = round((by_status["failed"] / finished) * 1000) / 10 if finished > 0 else 0

    return {
        "totalUsers": total_users,
        "totalDocuments": len(docs),
        "totalExports": total_exports,
        "documentsByStatus": by_status,
        "documentsByType": by_type,
        "ocrFailureRate": ocr_failure_rate,
        "recentActivity": {"last24h": activity_24h, "last7d": activity_7d},
    }
