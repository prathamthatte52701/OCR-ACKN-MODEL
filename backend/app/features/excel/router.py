from datetime import UTC, datetime
from pathlib import Path

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse

from app.core.database import get_database
from app.core.object_id import PyObjectId
from app.core.rate_limit import limiter
from app.features.auth.dependencies import CurrentUser, get_current_user
from app.features.excel import service as excel_service
from app.features.excel.schemas import BulkSaveRequest, NewExcelFileRequest

router = APIRouter()


def _physical_workbook_filename(user_id: ObjectId, filename: str) -> str:
    """Workbooks/Settings are per-user, but excel_service resolves a filename
    straight to a shared exports/ directory - two users picking the same
    display name would otherwise collide on the SAME physical .xlsx file even
    though their Workbook/Settings records are isolated. Namespacing the
    on-disk filename with the owning userId keeps the files isolated too."""
    return excel_service.physical_workbook_filename(user_id, filename)


def _owned_workbook_file(owner_id: ObjectId, filename: str) -> Path:
    """Resolves the physical .xlsx for a workbook the CALLER owns, or 404s.
    Last line of defence for downloads: whatever the DB record said, the file
    that gets served must live directly in the exports dir and carry the
    caller's own userId prefix - a record or name that somehow resolves to
    another user's file (or outside the dir) is treated as not found."""
    target = excel_service.file_path(_physical_workbook_filename(owner_id, filename))
    inside_exports = target.parent == excel_service.EXPORT_DIR
    if not inside_exports or not target.name.startswith(f"{owner_id}_"):
        raise HTTPException(status_code=404, detail="Workbook not found.")
    if not target.exists():
        raise HTTPException(status_code=404, detail="Workbook file not found on the server.")
    return target


async def _get_settings(user_id: ObjectId) -> dict | None:
    db = get_database()
    return await db.settings.find_one({"userId": user_id, "key": "excelState"})


def _serialize_workbook(wb: dict) -> dict:
    return {
        "id": str(wb["_id"]),
        "userId": str(wb["userId"]),
        "year": wb["year"],
        "filename": wb["filename"],
        "isActive": wb["isActive"],
        "archivedAt": wb.get("archivedAt"),
    }


@router.get("/workbooks")
async def list_workbooks(current_user: CurrentUser = Depends(get_current_user)) -> dict:
    db = get_database()
    cursor = db.workbooks.find({"userId": current_user.id}).sort("year", -1)
    workbooks = [_serialize_workbook(wb) async for wb in cursor]
    settings = await _get_settings(current_user.id)
    return {
        "workbooks": workbooks,
        "active": settings.get("activeWorkbookName") if settings else None,
        "activeYear": settings.get("activeYear") if settings else None,
    }


@router.get("/workbook/download")
async def download_workbook(
    workbook_id: str | None = Query(default=None, alias="workbookId"),
    year: int | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
) -> FileResponse:
    db = get_database()
    filename: str
    owner_user_id = current_user.id

    if workbook_id:
        try:
            wb_oid = ObjectId(workbook_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid workbook id.") from None
        wb = await db.workbooks.find_one({"_id": wb_oid, "userId": current_user.id})
        if not wb:
            raise HTTPException(status_code=404, detail="Workbook not found.")
        filename = wb["filename"]
        owner_user_id = wb["userId"]
    elif year is not None:
        wb = await db.workbooks.find_one(
            {"year": year, "userId": current_user.id}, sort=[("isActive", -1), ("createdAt", -1)]
        )
        if not wb:
            raise HTTPException(status_code=404, detail="No workbook for that year.")
        filename = wb["filename"]
    else:
        settings = await _get_settings(current_user.id)
        if not settings or not settings.get("activeWorkbookName"):
            raise HTTPException(
                status_code=400, detail="No active Excel workbook yet. Save a document first."
            )
        filename = settings["activeWorkbookName"]

    target = _owned_workbook_file(owner_user_id, filename)

    download_name = filename if filename.endswith(".xlsx") else f"{filename}.xlsx"
    return FileResponse(
        path=target,
        filename=download_name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# Export History is PRIVATE per user: a user sees only the rows they exported,
# and no other user's name/email ever appears in the response. (It used to be
# a deliberate cross-user view; that was reversed - the admin's full cross-user
# view lives in the admin router instead: GET /admin/exports and /admin/workbooks.)
# Like every other documents/workbooks route, scope by userId by default.
@router.get("/export-history")
async def export_history(current_user: CurrentUser = Depends(get_current_user)) -> dict:
    db = get_database()
    cursor = db.exportedrows.find({"userId": current_user.id}).sort("exportedAt", -1)
    rows = []
    async for row in cursor:
        workbook = None
        if row.get("workbookId"):
            wb = await db.workbooks.find_one(
                {"_id": row["workbookId"], "userId": current_user.id}, {"filename": 1, "year": 1}
            )
            if wb:
                workbook = {"filename": wb["filename"], "year": wb["year"]}
        rows.append(
            {
                "id": str(row["_id"]),
                "documentId": str(row["documentId"]),
                "workbookId": str(row["workbookId"]) if row.get("workbookId") else None,
                "workbook": workbook,
                "documentType": row["documentType"],
                "taxInvoiceNo": row.get("taxInvoiceNo"),
                "referenceNo": row.get("referenceNo"),
                "number": row.get("number"),
                "date": row.get("date"),
                "exportedAt": row["exportedAt"],
            }
        )
    return {"exports": rows}


# Download of a workbook listed on the caller's own Export History page. Scoped
# to the caller like everything else: someone else's workbook id is a 404.
@router.get("/export-history/workbook/{workbook_id}/download")
async def download_workbook_from_export_history(
    workbook_id: PyObjectId, current_user: CurrentUser = Depends(get_current_user)
) -> FileResponse:
    db = get_database()
    wb = await db.workbooks.find_one({"_id": workbook_id, "userId": current_user.id})
    if not wb:
        raise HTTPException(status_code=404, detail="Workbook not found.")

    target = _owned_workbook_file(current_user.id, wb["filename"])

    download_name = wb["filename"] if wb["filename"].endswith(".xlsx") else f"{wb['filename']}.xlsx"
    return FileResponse(
        path=target,
        filename=download_name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.post("/new-excel-file")
@limiter.limit("20/hour")
async def new_excel_file(
    request: Request,
    body: NewExcelFileRequest,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Rate limited - unbounded calls each archive the current workbook and
    write a fresh physical .xlsx + Workbook row, so without a limit this is a
    disk/DB exhaustion vector (verified: 15 rapid calls -> 15 files with zero
    throttling before this fix). 20/hour is generous for genuine use (this is
    a rare action - new workbook per year, or an occasional manual restart)
    while making scripted abuse impractical."""
    if not body.filename or not body.filename.strip():
        raise HTTPException(status_code=400, detail="filename is required.")
    trimmed = body.filename.strip()
    year, month = excel_service.current_period()

    db = get_database()
    now = datetime.now(UTC)
    # create_workbook always replaces the physical file, so reusing a name
    # would silently wipe that workbook's rows.
    if await db.workbooks.find_one({"userId": current_user.id, "filename": trimmed}):
        raise HTTPException(
            status_code=400, detail="You already have a workbook with that name. Pick another."
        )

    # Create the file FIRST. It used to archive the active workbook before
    # creating the new one, so a failed create left the user with no active
    # workbook at all.
    try:
        await excel_service.create_workbook(
            _physical_workbook_filename(current_user.id, trimmed), month
        )
    except excel_service.FileLockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=400, detail="That workbook name can't be used. Try a simpler name."
        ) from exc

    # Archive whatever workbook THIS USER currently has active, regardless of
    # year - covers both year rollover AND a same-year "start new file" click,
    # which the old app's earlier (buggy) version silently overwrote instead.
    await db.workbooks.update_many(
        {"userId": current_user.id, "isActive": True},
        {"$set": {"isActive": False, "archivedAt": now, "updatedAt": now}},
    )
    await db.workbooks.insert_one(
        {
            "userId": current_user.id,
            "year": year,
            "filename": trimmed,
            "isActive": True,
            "archivedAt": None,
            "createdAt": now,
            "updatedAt": now,
        }
    )
    await db.settings.update_one(
        {"userId": current_user.id, "key": "excelState"},
        {"$set": {"activeWorkbookName": trimmed, "activeYear": year, "updatedAt": now}},
        upsert=True,
    )
    return {"message": "New Excel workbook started.", "filename": trimmed, "year": year}


async def _save_document_to_excel(doc_id: ObjectId, current_user: CurrentUser) -> dict:
    """Core of a single document's save-to-Excel, shared by the individual
    Save/Save Again endpoint below and the bulk "Save All" endpoint - same
    lookup, same year-rollover/no-workbook handling, same locked
    excel_service.append_row call, same ExportedRow + audit log write.
    Raises HTTPException on any failure, exactly as before this was split
    out; callers decide whether that aborts the request (single save) or is
    caught per-document and continues the batch (bulk save)."""
    db = get_database()
    doc = await db.documents.find_one(
        {"_id": doc_id, "userId": current_user.id, "isDeleted": {"$ne": True}}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    if doc["uploadStatus"] != "processed":
        raise HTTPException(status_code=400, detail="Document has not been processed yet.")

    year, _ = excel_service.current_period()
    settings = await _get_settings(current_user.id)
    if not settings or not settings.get("activeWorkbookName"):
        # Structured the same way as the year-rollover 409 below (error code +
        # message) so the frontend can auto-prompt for a filename instead of
        # just displaying the message and telling the user to go find "Start
        # New Excel File" themselves - this is the very first export ever for
        # this user, so there's genuinely no workbook to append to yet.
        raise HTTPException(
            status_code=400,
            detail={
                "error": "NO_ACTIVE_WORKBOOK",
                "year": year,
                "message": "No active Excel workbook yet. Name your first workbook to continue.",
            },
        )

    now = datetime.now(UTC)
    # Year rollover: archive the old workbook and ask the frontend to create a
    # new one for the new year (prompts the user once for its name, then
    # retries this save). Previous year's file stays on disk, untouched.
    if settings.get("activeYear") != year:
        await db.workbooks.update_many(
            {"userId": current_user.id, "isActive": True, "year": settings.get("activeYear")},
            {"$set": {"isActive": False, "archivedAt": now, "updatedAt": now}},
        )
        raise HTTPException(
            status_code=409,
            detail={
                "error": "NEED_NEW_WORKBOOK",
                "year": year,
                "message": (
                    f"The year changed to {year}. Create a new workbook for {year} to continue."
                ),
            },
        )

    row = {
        "documentType": doc["documentType"],
        "taxInvoiceNo": doc.get("taxInvoiceNo"),
        "referenceNo": doc.get("referenceNo"),
        "number": doc.get("number"),
        "date": doc.get("date"),
        "timestamp": now.isoformat(),
    }

    # Worksheet = the document's OWN date, not today's date - a document dated
    # 30/06 always lands in the June sheet even if saved in July.
    sheet_month = excel_service.month_from_date(doc.get("date"))
    active_filename = settings["activeWorkbookName"]
    try:
        await excel_service.append_row(
            _physical_workbook_filename(current_user.id, active_filename), sheet_month, row
        )
    except excel_service.FileLockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    workbook_doc = await db.workbooks.find_one(
        {"userId": current_user.id, "filename": active_filename, "isActive": True}
    )

    await db.exportedrows.insert_one(
        {
            "documentId": doc["_id"],
            "userId": current_user.id,
            "workbookId": workbook_doc["_id"] if workbook_doc else None,
            "documentType": row["documentType"],
            "taxInvoiceNo": row["taxInvoiceNo"],
            "referenceNo": row["referenceNo"],
            "number": row["number"],
            "date": row["date"],
            "exportedAt": now,
            "createdAt": now,
            "updatedAt": now,
        }
    )
    # No limit on Save Again - this just flips the flag so the frontend can
    # show a "you've already saved this one" confirmation before a repeat
    # save, not a block. Every save still logs its own ExportedRow above and
    # its own audit_log entry below, repeats included, by design.
    await db.documents.update_one({"_id": doc["_id"]}, {"$set": {"exported": True}})

    from app.core.audit_log import log_action

    await log_action(
        current_user.id,
        "document_exported",
        {"documentId": str(doc["_id"]), "worksheet": sheet_month, "workbook": active_filename},
    )
    return {
        "message": "Excel file appended successfully.",
        "worksheet": sheet_month,
        "workbook": active_filename,
    }


@router.post("/{doc_id}/save")
async def save_document_to_excel(
    doc_id: PyObjectId, current_user: CurrentUser = Depends(get_current_user)
) -> dict:
    return await _save_document_to_excel(doc_id, current_user)


@router.post("/bulk-save")
async def bulk_save_documents_to_excel(
    body: BulkSaveRequest, current_user: CurrentUser = Depends(get_current_user)
) -> dict:
    """ "Save All" for one documents page: re-saves every document id the
    frontend sends (already-exported ones included, matching what an
    individual "Save Again" would do) - processed as a plain sequential
    loop, not asyncio.gather, so this request never issues concurrent
    writes itself; excel_service.append_row's per-filename asyncio.Lock +
    cross-process FileLock (see excel/service.py) is what actually protects
    against a *different* concurrent request (another tab, another bulk
    save) hitting the same workbook at the same time. Per-document
    ownership is enforced the same way as the single-save route -
    _save_document_to_excel's own userId-scoped lookup 404s (not 403s) on
    any id that doesn't belong to this user, so a manipulated id list can
    only ever fail that one entry, never touch another user's document."""
    succeeded: list[str] = []
    failed: list[dict] = []
    for doc_id in body.document_ids:
        try:
            await _save_document_to_excel(doc_id, current_user)
            succeeded.append(str(doc_id))
        except HTTPException as exc:
            reason = (
                exc.detail
                if isinstance(exc.detail, str)
                else exc.detail.get("message", "Could not save.")
            )
            failed.append({"documentId": str(doc_id), "reason": reason})

    return {
        "message": f"{len(succeeded)}/{len(body.document_ids)} saved successfully.",
        "succeeded": succeeded,
        "failed": failed,
    }
