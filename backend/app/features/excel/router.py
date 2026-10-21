import asyncio
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from loguru import logger

from app.core.database import get_database
from app.core.object_id import PyObjectId
from app.core.rate_limit import limiter
from app.features.auth.dependencies import CurrentUser, get_current_user
from app.features.excel import service as excel_service
from app.features.excel.schemas import BulkSaveRequest, NewExcelFileRequest

router = APIRouter()

# Largest "Save All" batch (a My Documents page is 30, the page-size cap is 100).
MAX_BULK_SAVE = 100
# Errors that would hit EVERY remaining document identically - the bulk loop stops on them.
BLOCKING_ERRORS = {"NO_ACTIVE_WORKBOOK", "NEED_NEW_WORKBOOK"}
FILE_BUSY_MESSAGE = "The Excel file is busy or open. Close it in Excel and try again."

DEFAULT_EXPORT_PAGE_SIZE = 30
MAX_EXPORT_PAGE_SIZE = 100
MAX_EXPORT_PAGE_NUMBER = 100_000


# One lock per (user, year): two saves that both need the same missing old-year workbook must not
# both create it (in-process only; the app runs as a single process).
_period_locks: dict[tuple[ObjectId, int], asyncio.Lock] = {}


async def _workbook_for_year(db: Any, user_id: ObjectId, year: int) -> dict | None:
    """The user's workbook for `year`: the active one if there is one, else the newest."""
    return await db.workbooks.find_one(
        {"userId": user_id, "year": year}, sort=[("isActive", -1), ("createdAt", -1)]
    )


async def _create_year_workbook(db: Any, user_id: ObjectId, year: int, month: str) -> dict:
    """Creates the workbook for a year that is not the current one (a late paper dated in an
    earlier year) with the same file structure as any new workbook. It is born archived and does
    NOT touch settings.excelState: activeYear/activeWorkbookName keep meaning "the workbook the
    dashboard shows by default" and never flip because one late paper was saved."""
    async with _period_locks.setdefault((user_id, year), asyncio.Lock()):
        existing = await _workbook_for_year(db, user_id, year)
        if existing:
            return existing
        taken = {w["filename"] async for w in db.workbooks.find({"userId": user_id})}
        name, n = f"Excel {year}", 1
        while name in taken:
            n += 1
            name = f"Excel {year} ({n})"
        await excel_service.create_workbook(_physical_workbook_filename(user_id, name), month)
        now = datetime.now(UTC)
        record = {
            "userId": user_id,
            "year": year,
            "filename": name,
            "isActive": False,
            "archivedAt": now,
            "createdAt": now,
            "updatedAt": now,
        }
        record["_id"] = (await db.workbooks.insert_one(record)).inserted_id
        return record


# One lock per document: Save Again appends the new row, then removes the old ones. Two concurrent
# saves of the SAME document (two tabs) would each remove the other's fresh row, so the whole save
# of one document is serialized (in-process only; the app runs as a single process).
_doc_locks: dict[ObjectId, asyncio.Lock] = {}


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
async def export_history(
    page: int | None = Query(default=None),
    limit: int | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Paginated (30 per page by default, 100 max) so the page stays fast however many
    documents a user has exported. Same capped page/limit convention as GET /documents."""
    db = get_database()
    lim = min(MAX_EXPORT_PAGE_SIZE, max(1, limit or DEFAULT_EXPORT_PAGE_SIZE))
    scope = {"userId": current_user.id}
    total = await db.exportedrows.count_documents(scope)
    total_pages = max(1, -(-total // lim))
    # a page past the end (rows were removed meanwhile) answers with the last real page
    pg = min(total_pages, MAX_EXPORT_PAGE_NUMBER, max(1, page or 1))
    cursor = db.exportedrows.find(scope).sort("exportedAt", -1).skip((pg - 1) * lim).limit(lim)
    page_rows = await cursor.to_list(length=None)
    # one lookup for every workbook on this page instead of one query per row
    workbook_ids = {r["workbookId"] for r in page_rows if r.get("workbookId")}
    workbooks = {
        w["_id"]: w
        async for w in db.workbooks.find(
            {"_id": {"$in": list(workbook_ids)}, "userId": current_user.id},
            {"filename": 1, "year": 1},
        )
    }
    rows = []
    for row in page_rows:
        wb = workbooks.get(row.get("workbookId"))
        workbook = {"filename": wb["filename"], "year": wb["year"]} if wb else None
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
    return {
        "exports": rows,
        "totalExports": total,
        "totalPages": total_pages,
        "currentPage": pg,
    }


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


async def _replace_old_rows(
    db: Any,
    user_id: ObjectId,
    doc_id: ObjectId,
    new_record_id: ObjectId,
    new_file: str,
    new_sheet: str,
    new_key: tuple,
    new_file_existed: bool,
) -> tuple[int, str | None]:
    """Save Again REPLACES: removes this document's earlier rows from their workbooks and deletes
    their exportedrows records. Runs only AFTER the new row is appended and its record inserted, so
    a failure here can never lose the new row. Uses each old record's STORED values (type, number,
    date, sheet), never the document's current ones.
    Known limit: rows have no ID, so matching is by (document type, number, date). Two DIFFERENT
    documents with identical type+number+date can have the wrong physical row removed; at most as
    many rows as this document has old records are ever removed.
    Returns (rows removed, warning text or None). A locked/unwritable file keeps its old records
    so the next Save Again retries."""
    old = (
        await db.exportedrows.find(
            {"documentId": doc_id, "userId": user_id, "_id": {"$ne": new_record_id}}
        )
        .sort("exportedAt", 1)
        .to_list(None)
    )
    by_workbook: dict[Any, list[dict]] = defaultdict(list)
    for rec in old:
        by_workbook[(rec.get("workbookId"), rec.get("workbookFilename"))].append(rec)

    replaced = 0
    warnings: list[str] = []
    for (workbook_id, workbook_filename), recs in by_workbook.items():
        record_ids = [r["_id"] for r in recs]
        workbook = (
            await db.workbooks.find_one({"_id": workbook_id, "userId": user_id})
            if workbook_id
            else None
        )
        if not workbook and workbook_id is None and workbook_filename:
            # saved while the workbook record was missing: the file is found by its stored name
            workbook = {"filename": workbook_filename}
        if not workbook:
            await db.exportedrows.delete_many({"_id": {"$in": record_ids}})
            continue
        physical = _physical_workbook_filename(user_id, workbook["filename"])
        if not excel_service.file_path(physical).exists() or (
            physical == new_file and not new_file_existed
        ):
            # the file is gone (or this very save re-created it empty): nothing to remove or warn
            await db.exportedrows.delete_many({"_id": {"$in": record_ids}})
            continue
        name = workbook["filename"]
        try:
            # the row just appended looks exactly like an unchanged old row: never remove it
            protect = (new_sheet, new_key) if physical == new_file else None
            removed, _ = await excel_service.remove_rows(
                physical, recs, keep_file=True, protect=protect
            )
        except excel_service.FileLockedError:
            warnings.append(
                f"The new row was saved, but the old row could not be removed from {name} "
                "because it is open in Excel. Close it and press Save Again to finish."
            )
            continue
        except Exception as exc:  # noqa: BLE001 - the new row is in; never fail the save over this
            logger.error(
                f"Removing the old Excel row of document {doc_id} failed: "
                f"class={type(exc).__name__}"
            )
            warnings.append(
                f"The new row was saved, but the old row could not be removed from {name}. "
                "Press Save Again to try again."
            )
            continue
        replaced += removed
        await db.exportedrows.delete_many({"_id": {"$in": record_ids}})
        if removed < len(recs):
            sheet = recs[0].get("worksheet") or excel_service.month_from_date(recs[0].get("date"))
            warnings.append(
                f"The old row for this document was not found in {name} ({sheet}). "
                "Please check that file by hand."
            )
    return replaced, (" ".join(warnings) or None)


async def _save_document_to_excel(doc_id: ObjectId, current_user: CurrentUser) -> dict:
    async with _doc_locks.setdefault(doc_id, asyncio.Lock()):
        return await _save_document_locked(doc_id, current_user)


async def _save_document_locked(doc_id: ObjectId, current_user: CurrentUser) -> dict:
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

    now_local = excel_service.now_ist()  # one clock read for both decisions
    current_year, _ = excel_service.current_period(now_local)
    year, sheet_month, date_used = excel_service.document_period(doc.get("date"), now_local)
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
                "year": current_year,
                "message": "No active Excel workbook yet. Name your first workbook to continue.",
            },
        )

    now = datetime.now(UTC)
    # The PAPER's date picks the workbook year (not the save date): a paper dated Dec 2025
    # saved in Jan 2026 goes to the 2025 workbook, December sheet.
    workbook_doc = await _workbook_for_year(db, current_user.id, year)
    if workbook_doc is None and year == settings.get("activeYear"):
        # settings point at a workbook whose record is missing: keep appending to it by name
        workbook_doc = {"_id": None, "filename": settings["activeWorkbookName"], "year": year}
    if workbook_doc is None and year == current_year:
        # Year rollover: archive the old workbook and ask the frontend to create a new one for
        # the new year (prompts the user once for its name, then retries this save). Previous
        # year's file stays on disk, untouched.
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
    if workbook_doc is None:
        try:
            workbook_doc = await _create_year_workbook(db, current_user.id, year, sheet_month)
        except excel_service.FileLockedError as exc:
            raise HTTPException(status_code=409, detail=FILE_BUSY_MESSAGE) from exc

    row = {
        "documentType": doc["documentType"],
        "taxInvoiceNo": doc.get("taxInvoiceNo"),
        "referenceNo": doc.get("referenceNo"),
        "number": doc.get("number"),
        "date": doc.get("date"),
        "timestamp": now.isoformat(),
    }

    active_filename = workbook_doc["filename"]
    new_file_existed = excel_service.file_path(
        _physical_workbook_filename(current_user.id, active_filename)
    ).exists()
    try:
        await excel_service.append_row(
            _physical_workbook_filename(current_user.id, active_filename), sheet_month, row
        )
    except excel_service.FileLockedError as exc:
        raise HTTPException(status_code=409, detail=FILE_BUSY_MESSAGE) from exc

    new_record = await db.exportedrows.insert_one(
        {
            "documentId": doc["_id"],
            "userId": current_user.id,
            "workbookId": workbook_doc["_id"],
            # kept so Save Again can still find the file if the workbook record is missing
            "workbookFilename": active_filename,
            "worksheet": sheet_month,
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
    # Save Again replaces: the old rows of this document are removed AFTER the new one is safely in.
    try:
        replaced, stale_warning = await _replace_old_rows(
            db,
            current_user.id,
            doc["_id"],
            new_record.inserted_id,
            _physical_workbook_filename(current_user.id, active_filename),
            sheet_month,
            excel_service.row_key(row),
            new_file_existed,
        )
    except Exception as exc:  # noqa: BLE001 - the new row is in; a DB hiccup must not fail the save
        logger.error(
            f"Replacing the old Excel rows of document {doc_id} failed: class={type(exc).__name__}"
        )
        replaced = 0
        stale_warning = (
            "The new row was saved, but the old row could not be checked. "
            "Press Save Again to try again."
        )
    await db.documents.update_one({"_id": doc["_id"]}, {"$set": {"exported": True}})

    from app.core.audit_log import log_action

    await log_action(
        current_user.id,
        "document_exported",
        {
            "documentId": str(doc["_id"]),
            "worksheet": sheet_month,
            "workbook": active_filename,
            "replaced": replaced,
        },
    )
    result: dict = {
        "message": "Excel file appended successfully.",
        "worksheet": sheet_month,
        "workbook": active_filename,
        "year": year,
        # True when the date was missing/unreal/implausible and the row went to the SAVE date's
        # year and month instead
        "dateFallback": not date_used,
        "replaced": replaced,
    }
    if stale_warning:
        result["staleRowWarning"] = stale_warning
    return result


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
    # Same id twice in one request used to write the row twice - keep first occurrence, in order.
    ids = list(dict.fromkeys(body.document_ids))
    if len(ids) > MAX_BULK_SAVE:
        raise HTTPException(
            status_code=400, detail=f"You can save at most {MAX_BULK_SAVE} documents at once."
        )

    succeeded: list[str] = []
    failed: list[dict] = []
    date_fallback: list[str] = []
    blocked: dict | None = None
    not_attempted: list[str] = []
    replaced_total = 0
    stale_warnings: list[dict] = []
    for index, doc_id in enumerate(ids):
        try:
            result = await _save_document_to_excel(doc_id, current_user)
            succeeded.append(str(doc_id))
            replaced_total += result.get("replaced", 0)
            if result.get("staleRowWarning"):
                stale_warnings.append(
                    {"documentId": str(doc_id), "message": result["staleRowWarning"]}
                )
            if result.get("dateFallback"):
                date_fallback.append(str(doc_id))
        except HTTPException as exc:
            detail = exc.detail
            if isinstance(detail, dict) and detail.get("error") in BLOCKING_ERRORS:
                # No workbook yet / year rolled over: every remaining document would fail the
                # same way, so stop here and hand the decision (name a workbook) to the caller.
                blocked = {
                    "error": detail["error"],
                    "year": detail.get("year"),
                    "message": detail.get("message", "Create an Excel workbook to continue."),
                }
                not_attempted = [str(i) for i in ids[index:]]
                break
            reason = detail if isinstance(detail, str) else detail.get("message", "Could not save.")
            failed.append({"documentId": str(doc_id), "reason": reason})
        except Exception as exc:  # noqa: BLE001 - one bad document must not abort the batch
            logger.error(f"Bulk save of document {doc_id} failed: class={type(exc).__name__}")
            failed.append({"documentId": str(doc_id), "reason": "Could not save this document."})

    return {
        "message": f"{len(succeeded)}/{len(ids)} saved successfully.",
        "succeeded": succeeded,
        "failed": failed,
        "blocked": blocked,
        "notAttempted": not_attempted,
        "dateFallback": date_fallback,
        "replaced": replaced_total,
        "staleWarnings": stale_warnings,
    }
