import asyncio
import os
from collections import Counter, defaultdict
from collections.abc import Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
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


WORKBOOK_EXISTS_MESSAGE = "A workbook with this name already exists."
# One lock per user for "start a new workbook" (in-process only; the app runs as one process).
_create_locks: dict[ObjectId, asyncio.Lock] = {}


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
        taken = {
            excel_service.workbook_key(w["filename"])
            async for w in db.workbooks.find({"userId": user_id})
        }
        name, n = f"Excel {year}", 1
        while True:
            while excel_service.workbook_key(name) in taken:
                n += 1
                name = f"Excel {year} ({n})"
            try:
                await excel_service.create_workbook(
                    _physical_workbook_filename(user_id, name), month, exclusive=True
                )
                break
            except excel_service.WorkbookExistsError:
                taken.add(excel_service.workbook_key(name))  # a file without a record: next name
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
    # One create at a time per user: the name check, the file write and the record insert are a
    # single step, so two parallel creates of the same name cannot both pass the check.
    async with _create_locks.setdefault(current_user.id, asyncio.Lock()):
        return await _start_new_workbook(db, current_user, trimmed, year, month, now)


async def _start_new_workbook(
    db: Any, current_user: CurrentUser, trimmed: str, year: int, month: str, now: datetime
) -> dict:
    # A name is taken when ANY of the user's workbooks maps to the same file ("Bills",
    # "Bills.xlsx", "bills" are one file on disk): creating it would wipe that workbook's rows.
    key = excel_service.workbook_key(trimmed)
    async for w in db.workbooks.find({"userId": current_user.id}, {"filename": 1}):
        if excel_service.workbook_key(w["filename"]) == key:
            raise HTTPException(status_code=400, detail=WORKBOOK_EXISTS_MESSAGE)

    # Create the file FIRST. It used to archive the active workbook before
    # creating the new one, so a failed create left the user with no active
    # workbook at all. exclusive=True: an existing file is never replaced.
    try:
        await excel_service.create_workbook(
            _physical_workbook_filename(current_user.id, trimmed), month, exclusive=True
        )
    except excel_service.WorkbookExistsError as exc:
        raise HTTPException(status_code=400, detail=WORKBOOK_EXISTS_MESSAGE) from exc
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


CHECK_FAILED_WARNING = (
    "The new row was saved, but the old row could not be checked. Press Save Again to try again."
)
EDITED_WHILE_SAVING_WARNING = (
    "This document was edited while it was being saved, so the Excel row has the earlier values. "
    "Press Save Again to update it."
)


@dataclass
class _SavePlan:
    """Everything PREPARE decided for one document; EXECUTE only writes."""

    doc: dict
    user_id: ObjectId
    row: dict
    physical: str
    sheet_month: str
    workbook_doc: dict
    year: int
    date_used: bool
    now: datetime
    captured_updated_at: Any
    new_file_existed: bool = True
    new_record_id: ObjectId | None = None
    replaced: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class _OldRowsJob:
    """The old export records of one document that live in one workbook (one physical file)."""

    plan: _SavePlan
    name: str
    physical: str
    recs: list[dict]


async def _collect_old_rows(
    db: Any,
    plan: _SavePlan,
    position: int = 0,
    snapshot: set[str] | None = None,
    created_at: dict[str, int] | None = None,
) -> list[_OldRowsJob]:
    """Save Again REPLACES: finds this document's earlier export records, grouped by workbook. A
    record whose workbook record or file is gone (or whose file this very save re-created empty) is
    just deleted here - nothing to remove or warn about. The rest are returned as jobs for the one
    batched removal. Uses each old record's STORED values (type, number, date, sheet), never the
    document's current ones.
    Known limit: rows have no ID, so matching is by (document type, number, date). Two DIFFERENT
    documents with identical type+number+date can have the wrong physical row removed; at most as
    many rows as this document has old records are ever removed."""
    old = (
        await db.exportedrows.find(
            {
                "documentId": plan.doc["_id"],
                "userId": plan.user_id,
                "_id": {"$ne": plan.new_record_id},
            }
        )
        .sort("exportedAt", 1)
        .to_list(None)
    )
    by_workbook: dict[Any, list[dict]] = defaultdict(list)
    for rec in old:
        by_workbook[(rec.get("workbookId"), rec.get("workbookFilename"))].append(rec)

    jobs: list[_OldRowsJob] = []
    for (workbook_id, workbook_filename), recs in by_workbook.items():
        record_ids = [r["_id"] for r in recs]
        workbook = (
            await db.workbooks.find_one({"_id": workbook_id, "userId": plan.user_id})
            if workbook_id
            else None
        )
        if not workbook and workbook_id is None and workbook_filename:
            # saved while the workbook record was missing: the file is found by its stored name
            workbook = {"filename": workbook_filename}
        if not workbook:
            await db.exportedrows.delete_many({"_id": {"$in": record_ids}})
            continue
        physical = _physical_workbook_filename(plan.user_id, workbook["filename"])
        target = excel_service.file_path(physical)
        # the file as this document's turn in a sequential loop would have seen it: one that a
        # LATER document of the batch creates did not exist yet
        existed_then = (
            snapshot is None
            or target.name in snapshot
            or (created_at or {}).get(physical, len(created_at or {}) + 10**9) <= position
        )
        if (
            not target.exists()
            or not existed_then
            or (physical == plan.physical and not plan.new_file_existed)
        ):
            # the file is gone (or this very save re-created it empty): nothing to remove or warn
            await db.exportedrows.delete_many({"_id": {"$in": record_ids}})
            continue
        jobs.append(_OldRowsJob(plan, workbook["filename"], physical, recs))
    return jobs


async def _remove_old_rows(db: Any, jobs: list[_OldRowsJob], appended: list[_SavePlan]) -> None:
    """ONE removal per physical file for the old rows of every document of the batch. A locked or
    unwritable file keeps its old records so the next Save Again retries. The rows appended in this
    batch to that file are protected: they look exactly like unchanged old rows."""
    by_file: dict[str, list[_OldRowsJob]] = defaultdict(list)
    for job in jobs:
        by_file[job.physical].append(job)
    for physical, file_jobs in by_file.items():
        protect = Counter(
            (p.sheet_month, excel_service.row_key(p.row))
            for p in appended
            if p.physical == physical
        )
        all_recs = [rec for job in file_jobs for rec in job.recs]
        try:
            found = await excel_service.remove_rows_detailed(physical, all_recs, protect=protect)
        except excel_service.FileLockedError:
            for job in file_jobs:
                job.plan.warnings.append(
                    f"The new row was saved, but the old row could not be removed from {job.name} "
                    "because it is open in Excel. Close it and press Save Again to finish."
                )
            continue
        except (
            Exception
        ) as exc:  # noqa: BLE001 - the new rows are in; never fail the save over this
            logger.error(f"Removing old Excel rows failed: class={type(exc).__name__}")
            for job in file_jobs:
                job.plan.warnings.append(
                    f"The new row was saved, but the old row could not be removed from {job.name}. "
                    "Press Save Again to try again."
                )
            continue
        pos = 0
        for job in file_jobs:
            removed = sum(found[pos : pos + len(job.recs)])
            pos += len(job.recs)
            try:
                await db.exportedrows.delete_many({"_id": {"$in": [r["_id"] for r in job.recs]}})
            except Exception as exc:  # noqa: BLE001 - never fail the save over this
                logger.error(
                    f"Replacing the old Excel rows of document {job.plan.doc['_id']} failed: "
                    f"class={type(exc).__name__}"
                )
                job.plan.warnings.append(CHECK_FAILED_WARNING)
                continue
            job.plan.replaced += removed
            if removed < len(job.recs):
                sheet = job.recs[0].get("worksheet") or excel_service.month_from_date(
                    job.recs[0].get("date")
                )
                job.plan.warnings.append(
                    f"The old row for this document was not found in {job.name} ({sheet}). "
                    "Please check that file by hand."
                )


DUPLICATE_WARNING = (
    "Another document with the same number and date is already in Excel. "
    "Check that this is not a duplicate."
)


def _number_is_blank(doc: dict) -> bool:
    keys = ("taxInvoiceNo", "referenceNo") if doc["documentType"] == "Tax Invoice" else ("number",)
    return not any(str(doc.get(k) or "").strip() for k in keys)


async def _warn_duplicates(db: Any, plans: list[_SavePlan]) -> None:
    """Warns (never blocks) when another document of the same user with the same (type, number,
    date) is already exported, or comes earlier in this batch. One query per batch; it needs an
    exportedrows index on (userId, date)."""
    dated = [p for p in plans if p.row.get("date")]
    if not dated:
        return
    try:
        recs = await db.exportedrows.find(
            {"userId": dated[0].user_id, "date": {"$in": list({p.row["date"] for p in dated})}}
        ).to_list(None)
    except Exception as exc:  # noqa: BLE001 - a warning must never fail the save
        logger.error(f"Duplicate check failed: class={type(exc).__name__}")
        return
    seen: dict[tuple, set] = defaultdict(set)
    for rec in recs:
        seen[excel_service.row_key(rec)].add(rec["documentId"])
    for plan in dated:
        key = excel_service.row_key(plan.row)
        if seen[key] - {plan.doc["_id"]}:
            plan.warnings.append(DUPLICATE_WARNING)
        seen[key].add(plan.doc["_id"])


async def _prepare_save(db: Any, doc_id: ObjectId, current_user: CurrentUser) -> _SavePlan:
    """PREPARE of one document's save: every decision and check, no Excel write. Raises
    HTTPException on any failure, exactly as the single-document save always did; callers decide
    whether that aborts the request (single save) or is caught per-document (bulk save)."""
    doc = await db.documents.find_one(
        {"_id": doc_id, "userId": current_user.id, "isDeleted": {"$ne": True}}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    if doc["uploadStatus"] != "processed":
        raise HTTPException(status_code=400, detail="Document has not been processed yet.")

    if _number_is_blank(doc):  # before any workbook is created or rolled over
        raise HTTPException(
            status_code=400,
            detail="Number not read. Reprocess the document, or type the number, then save.",
        )

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
    physical = _physical_workbook_filename(current_user.id, workbook_doc["filename"])
    return _SavePlan(
        doc=doc,
        user_id=current_user.id,
        row=row,
        physical=physical,
        sheet_month=sheet_month,
        workbook_doc=workbook_doc,
        year=year,
        date_used=date_used,
        now=now,
        # race B: the document may be edited between now and the final "exported" write
        captured_updated_at=doc.get("updatedAt"),
        new_file_existed=excel_service.file_path(physical).exists(),
    )


@dataclass
class _BatchOutcome:
    results: dict[ObjectId, dict] = field(default_factory=dict)
    errors: dict[ObjectId, Exception] = field(default_factory=dict)
    blocked: dict | None = None
    not_attempted: list[str] = field(default_factory=list)


async def _finish_plan(db: Any, plan: _SavePlan, current_user: CurrentUser) -> dict:
    """Last step of one saved document: the conditional exported flag (race B), audit, result."""
    stale_warning = " ".join(plan.warnings) or None
    res = await db.documents.update_one(
        {"_id": plan.doc["_id"], "updatedAt": plan.captured_updated_at},
        {"$set": {"exported": True}},
    )
    if res.matched_count == 0:
        # edited during the save: the edit already reset exported to False and must keep that
        stale_warning = " ".join(filter(None, [stale_warning, EDITED_WHILE_SAVING_WARNING]))

    from app.core.audit_log import log_action

    await log_action(
        current_user.id,
        "document_exported",
        {
            "documentId": str(plan.doc["_id"]),
            "worksheet": plan.sheet_month,
            "workbook": plan.workbook_doc["filename"],
            "replaced": plan.replaced,
        },
    )
    result: dict = {
        "message": "Excel file appended successfully.",
        "worksheet": plan.sheet_month,
        "workbook": plan.workbook_doc["filename"],
        "year": plan.year,
        # True when the date was missing/unreal/implausible and the row went to the SAVE date's
        # year and month instead
        "dateFallback": not plan.date_used,
        "replaced": plan.replaced,
    }
    if stale_warning:
        result["staleRowWarning"] = stale_warning
    return result


def _log_orphaned_batch(task: "asyncio.Future[Any]") -> None:
    if task.cancelled():
        return
    exc = task.exception()  # retrieved, so asyncio never reports it as unretrieved
    if exc is not None:
        logger.error(
            f"Save batch finished after its request ended with an error: class={type(exc).__name__}"
        )


async def _save_batch(ids: Sequence[ObjectId], current_user: CurrentUser) -> _BatchOutcome:
    """Runs the batch as its own task and shields it: if the client disconnects (the request is
    cancelled) the work still finishes - rows already in the workbook always get their export
    records - and the document locks are released only when it really ended."""
    task = asyncio.ensure_future(_save_batch_inner(ids, current_user))
    task.add_done_callback(_log_orphaned_batch)
    return await asyncio.shield(task)


async def _save_batch_inner(ids: Sequence[ObjectId], current_user: CurrentUser) -> _BatchOutcome:
    """Save-to-Excel for 1..N documents: PREPARE each (request order, stops at the first blocking
    error), then EXECUTE with one workbook write per physical file and one batched removal of the
    old rows per file. Every document's lock is held for the whole batch, taken in sorted id order
    so two overlapping requests can never deadlock. Failures are isolated: a prepare failure fails
    that document, a file failure fails the documents of that file only."""
    out = _BatchOutcome()
    db = get_database()
    async with AsyncExitStack() as stack:
        for doc_id in sorted(ids):
            await stack.enter_async_context(_doc_locks.setdefault(doc_id, asyncio.Lock()))

        # files that exist before this batch touches anything (prepare may create a year workbook)
        try:
            snapshot = {e.name for e in os.scandir(excel_service.EXPORT_DIR)}
        except OSError:
            snapshot = set()
        created_at: dict[str, int] = {}

        # PREPARE
        plans: list[_SavePlan] = []
        seen_files: set[str] = set()
        for index, doc_id in enumerate(ids):
            try:
                plan = await _prepare_save(db, doc_id, current_user)
            except HTTPException as exc:
                out.errors[doc_id] = exc
                detail = exc.detail
                if isinstance(detail, dict) and detail.get("error") in BLOCKING_ERRORS:
                    # No workbook yet / year rolled over: every remaining document would fail the
                    # same way, so stop here and hand the decision (name a workbook) to the caller.
                    out.blocked = {
                        "error": detail["error"],
                        "year": detail.get("year"),
                        "message": detail.get("message", "Create an Excel workbook to continue."),
                    }
                    out.not_attempted = [str(i) for i in ids[index:]]
                    break
                continue
            except Exception as exc:  # noqa: BLE001 - one bad document must not abort the batch
                out.errors[doc_id] = exc
                continue
            # what a sequential loop would have seen: an earlier document's append creates the file
            if plan.physical in seen_files:
                plan.new_file_existed = True
            seen_files.add(plan.physical)
            if excel_service.file_path(plan.physical).name not in snapshot:
                created_at.setdefault(plan.physical, len(plans))
            plans.append(plan)
        await _warn_duplicates(db, plans)

        # EXECUTE: one append per physical file, request order inside a file
        by_file: dict[str, list[_SavePlan]] = defaultdict(list)
        for plan in plans:
            by_file[plan.physical].append(plan)
        appended: list[_SavePlan] = []
        for physical, file_plans in by_file.items():
            try:
                await excel_service.append_rows(
                    physical, [(p.sheet_month, p.row) for p in file_plans]
                )
            except excel_service.FileLockedError as exc:
                busy = HTTPException(status_code=409, detail=FILE_BUSY_MESSAGE)
                busy.__cause__ = exc
                for p in file_plans:
                    out.errors[p.doc["_id"]] = busy
                continue
            except Exception as exc:  # noqa: BLE001 - this file failed; other files carry on
                for p in file_plans:
                    out.errors[p.doc["_id"]] = exc
                continue
            appended.extend(file_plans)
        appended_ids = {p.doc["_id"] for p in appended}
        appended = [p for p in plans if p.doc["_id"] in appended_ids]  # back to request order

        # the export records, one per document that made it into its workbook
        recorded: list[_SavePlan] = []
        for plan in appended:
            try:
                new_record = await db.exportedrows.insert_one(
                    {
                        "documentId": plan.doc["_id"],
                        "userId": plan.user_id,
                        "workbookId": plan.workbook_doc["_id"],
                        # kept so Save Again can still find the file if the workbook record is gone
                        "workbookFilename": plan.workbook_doc["filename"],
                        "worksheet": plan.sheet_month,
                        "documentType": plan.row["documentType"],
                        "taxInvoiceNo": plan.row["taxInvoiceNo"],
                        "referenceNo": plan.row["referenceNo"],
                        "number": plan.row["number"],
                        "date": plan.row["date"],
                        "exportedAt": plan.now,
                        "createdAt": plan.now,
                        "updatedAt": plan.now,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                out.errors[plan.doc["_id"]] = exc
                continue
            plan.new_record_id = new_record.inserted_id
            recorded.append(plan)

        # Save Again replaces: the old rows are removed AFTER the new ones are safely in.
        jobs: list[_OldRowsJob] = []
        for plan in recorded:
            try:
                jobs.extend(
                    await _collect_old_rows(db, plan, plans.index(plan), snapshot, created_at)
                )
            except Exception as exc:  # noqa: BLE001 - a DB hiccup must not fail the save
                logger.error(
                    f"Replacing the old Excel rows of document {plan.doc['_id']} failed: "
                    f"class={type(exc).__name__}"
                )
                plan.warnings[:] = [CHECK_FAILED_WARNING]
                plan.replaced = 0
                jobs = [j for j in jobs if j.plan is not plan]
        await _remove_old_rows(db, jobs, appended)

        for plan in recorded:
            try:
                out.results[plan.doc["_id"]] = await _finish_plan(db, plan, current_user)
            except Exception as exc:  # noqa: BLE001
                out.errors[plan.doc["_id"]] = exc
    return out


async def _save_document_to_excel(doc_id: ObjectId, current_user: CurrentUser) -> dict:
    out = await _save_batch([doc_id], current_user)
    if doc_id in out.errors:
        raise out.errors[doc_id]
    return out.results[doc_id]


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
    individual "Save Again" would do) as ONE batch: documents are prepared one
    by one, then each workbook file is written once (see _save_batch).
    Per-document ownership is enforced the same way as the single-save route -
    _prepare_save's own userId-scoped lookup 404s (not 403s) on any id that
    doesn't belong to this user, so a manipulated id list can only ever fail
    that one entry, never touch another user's document."""
    # Same id twice in one request used to write the row twice - keep first occurrence, in order.
    ids = list(dict.fromkeys(body.document_ids))
    if len(ids) > MAX_BULK_SAVE:
        raise HTTPException(
            status_code=400, detail=f"You can save at most {MAX_BULK_SAVE} documents at once."
        )

    out = await _save_batch(ids, current_user)
    succeeded: list[str] = []
    failed: list[dict] = []
    date_fallback: list[str] = []
    replaced_total = 0
    stale_warnings: list[dict] = []
    for doc_id in ids:
        if doc_id in out.results:
            result = out.results[doc_id]
            succeeded.append(str(doc_id))
            replaced_total += result.get("replaced", 0)
            if result.get("staleRowWarning"):
                stale_warnings.append(
                    {"documentId": str(doc_id), "message": result["staleRowWarning"]}
                )
            if result.get("dateFallback"):
                date_fallback.append(str(doc_id))
        elif doc_id in out.errors:
            exc = out.errors[doc_id]
            if isinstance(exc, HTTPException):
                detail = exc.detail
                if isinstance(detail, dict) and detail.get("error") in BLOCKING_ERRORS:
                    continue  # reported through `blocked` / `notAttempted`
                reason = (
                    detail if isinstance(detail, str) else detail.get("message", "Could not save.")
                )
                failed.append({"documentId": str(doc_id), "reason": reason})
            else:
                logger.error(f"Bulk save of document {doc_id} failed: class={type(exc).__name__}")
                failed.append(
                    {"documentId": str(doc_id), "reason": "Could not save this document."}
                )

    return {
        "message": f"{len(succeeded)}/{len(ids)} saved successfully.",
        "succeeded": succeeded,
        "failed": failed,
        "blocked": out.blocked,
        "notAttempted": out.not_attempted,
        "dateFallback": date_fallback,
        "replaced": replaced_total,
        "staleWarnings": stale_warnings,
    }
