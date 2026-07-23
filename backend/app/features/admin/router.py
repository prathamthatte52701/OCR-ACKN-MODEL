from datetime import UTC, datetime, timedelta

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.core.audit_log import log_action
from app.core.database import get_database
from app.core.object_id import PyObjectId
from app.core.validators import (
    normalize_email,
    normalize_username,
    validate_email,
    validate_username,
)
from app.features.admin.schemas import AdminUpdateUserRequest
from app.features.auth.dependencies import CurrentUser, require_admin
from app.features.documents.gridfs_service import delete_file
from app.features.documents.schemas import CorrectRequest
from app.features.excel import service as excel_service
from app.features.ocr.extraction import normalize_date_to_ddmmyyyy

router = APIRouter()

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
            except Exception:  # noqa: BLE001
                pass

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
    db = get_database()
    doc = await db.documents.find_one({"_id": doc_id, "isDeleted": {"$ne": True}})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    await db.documents.update_one(
        {"_id": doc_id}, {"$set": {"isDeleted": True, "deletedAt": datetime.now(UTC)}}
    )
    if doc.get("gridFsFileId"):
        try:
            await delete_file(doc["gridFsFileId"])
        except Exception:  # noqa: BLE001
            pass
    await log_action(
        current_user.id,
        "document_deleted",
        {"documentId": str(doc_id), "ownerUserId": str(doc["userId"]), "byAdmin": True},
    )
    return {"message": "Document deleted successfully."}


@router.post("/documents/{doc_id}/purge-file")
async def purge_document_file_as_admin(
    doc_id: PyObjectId, current_user: CurrentUser = Depends(require_admin)
) -> dict:
    """Admin equivalent of the user-scoped purge-file action - permanently
    removes the stored original file from GridFS, cross-user, leaving the
    Document record's extracted metadata untouched."""
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

    await delete_file(doc["gridFsFileId"])

    now = datetime.now(UTC)
    await db.documents.update_one(
        {"_id": doc_id}, {"$set": {"filePurged": True, "filePurgedAt": now, "updatedAt": now}}
    )
    await log_action(
        current_user.id,
        "document_file_purged",
        {"documentId": str(doc_id), "ownerUserId": str(doc["userId"]), "byAdmin": True},
    )
    return {
        "message": "Original file permanently removed. Extracted data remains fully accessible."
    }


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
