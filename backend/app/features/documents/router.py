import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Literal

from bson import ObjectId
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import Response
from loguru import logger

from app.core.audit_log import log_action
from app.core.database import get_database
from app.core.object_id import PyObjectId
from app.core.rate_limit import limiter
from app.core.security import verify_password
from app.features.auth.dependencies import CurrentUser, get_current_user
from app.features.documents.gridfs_service import delete_file, download_buffer, upload_buffer
from app.features.documents.schemas import (
    ConfirmedDeleteRequest,
    CorrectRequest,
    MessageResponse,
    PurgeRangeRequest,
)
from app.features.excel import service as excel_service
from app.features.ocr.extraction import normalize_date_to_ddmmyyyy
from app.features.ocr.pipeline import process_document
from app.features.ocr.preprocessing import get_pdf_page_count

router = APIRouter()

DOCUMENT_TYPES = {"Tax Invoice", "Delivery Challan"}
# Rolling windows from "now", not calendar-aligned (e.g. "today" = last 24h,
# not midnight-to-now) - simplest, deterministic, avoids timezone-boundary
# ambiguity between server UTC and the user's local day/week/month/year.
RANGE_DAYS = {"today": 1, "week": 7, "month": 30, "year": 365}
MAX_FILE_SIZE = 5 * 1024 * 1024
MAX_BULK_FILES = 10
ALLOWED_MIME_TYPES = {"image/jpeg", "image/jpg", "image/png", "application/pdf"}

EDITABLE_FIELDS = {"taxInvoiceNo", "referenceNo", "number", "date"}
FIELDS_BY_DOCUMENT_TYPE = {
    "Tax Invoice": {"taxInvoiceNo", "referenceNo", "date"},
    "Delivery Challan": {"number", "date"},
}


def _detect_mime_type(buffer: bytes) -> str | None:
    if len(buffer) < 4:
        return None
    if buffer[0:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if buffer[0:4] == b"\x89PNG":
        return "image/png"
    if buffer[0:4] == b"%PDF":
        return "application/pdf"
    return None


def _mime_matches_upload(declared: str, detected: str | None) -> bool:
    if not detected:
        return False
    if declared == detected:
        return True
    return declared == "image/jpg" and detected == "image/jpeg"


def _name_from_original_filename(original_name: str) -> str:
    return PurePosixPath(original_name).stem or original_name


_UNSAFE_HEADER_CHARS_RE = re.compile(r'[\x00-\x1f\x7f"\\]')


def _sanitize_content_disposition_filename(filename: str) -> str:
    """The uploader's original filename is client-supplied and gets
    interpolated into a Content-Disposition response header - a filename
    containing a `"` or control/CR-LF characters could break out of the
    quoted-string value or corrupt the header. Stripping those characters
    (rather than rejecting the upload) keeps every legitimate filename
    working while making header injection structurally impossible here."""
    cleaned = _UNSAFE_HEADER_CHARS_RE.sub("", filename)
    return cleaned or "document"


async def _validate_and_store(
    buffer: bytes, mime_type: str, original_name: str, document_type: str, user_id: ObjectId
) -> dict:
    """Raises HTTPException on validation failure; otherwise creates the
    Document row and returns it (uploadStatus 'uploaded', not yet processed)."""
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                "Please choose a document type - Tax Invoice or Delivery Challan - "
                "before uploading."
            ),
        )
    if len(buffer) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File size must be 5 MB or less.")
    if mime_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400, detail="Only JPG, JPEG, PNG, and PDF files are allowed."
        )

    detected = _detect_mime_type(buffer)
    if not _mime_matches_upload(mime_type, detected):
        raise HTTPException(
            status_code=400, detail="File content does not match the selected file type."
        )

    if mime_type == "application/pdf":
        pages = await get_pdf_page_count(buffer)
        if not pages:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Could not read this PDF. Please upload a valid PDF or convert it to JPG/PNG."
                ),
            )
        if pages > 4:
            raise HTTPException(status_code=400, detail="PDF must be 4 pages or less.")

    db = get_database()
    auto_name = _name_from_original_filename(original_name)
    grid_fs_file_id = await upload_buffer(buffer, original_name, mime_type)

    now = datetime.now(UTC)
    insert_result = await db.documents.insert_one(
        {
            "userId": user_id,
            "autoName": auto_name,
            "originalFilename": original_name,
            "mimeType": mime_type,
            "size": len(buffer),
            "gridFsFileId": grid_fs_file_id,
            "uploadStatus": "uploaded",
            "documentType": document_type,
            "taxInvoiceNo": None,
            "referenceNo": None,
            "number": None,
            "date": None,
            "taxInvoiceNoConfidence": None,
            "referenceNoConfidence": None,
            "numberConfidence": None,
            "dateConfidence": None,
            "taxInvoiceNoAutoCorrected": None,
            "numberAutoCorrected": None,
            "dateAutoCorrected": None,
            "filePurged": False,
            "filePurgedAt": None,
            "edited": False,
            "exported": False,
            "isDeleted": False,
            "createdAt": now,
            "updatedAt": now,
        }
    )
    doc = await db.documents.find_one({"_id": insert_result.inserted_id})
    assert doc is not None
    return doc


@router.post("/upload", status_code=201)
@limiter.limit("60/hour")
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    document: UploadFile = File(...),
    document_type: str = Form(..., alias="documentType"),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Rate limited - every upload triggers real PaddleOCR + Groq work
    serialized through a single process-wide lock (see ocr/pipeline.py), so
    unthrottled uploads are a DoS vector against every OTHER user's queue,
    not just this account's own storage. 60/hour is well above genuine
    single-document use while making scripted spam impractical."""
    if not document:
        raise HTTPException(status_code=400, detail="No file uploaded.")
    buffer = await document.read()
    doc = await _validate_and_store(
        buffer,
        document.content_type or "",
        document.filename or "upload",
        document_type,
        current_user.id,
    )
    background_tasks.add_task(
        process_document, doc["_id"], buffer, doc["mimeType"], doc["documentType"]
    )
    return {"document": _serialize_document(doc)}


@router.post("/bulk-upload", status_code=201)
@limiter.limit("30/hour")
async def bulk_upload_documents(
    request: Request,
    background_tasks: BackgroundTasks,
    documents: list[UploadFile] = File(...),
    document_types: list[str] = Form(..., alias="documentTypes"),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    if not documents:
        raise HTTPException(status_code=400, detail="No files uploaded.")
    if len(documents) > MAX_BULK_FILES:
        raise HTTPException(
            status_code=400, detail=f"You can upload a maximum of {MAX_BULK_FILES} files at once."
        )
    if len(document_types) != len(documents):
        raise HTTPException(status_code=400, detail="Each file needs a document type.")

    results: list[dict[str, object]] = []
    created: list[tuple[ObjectId, bytes, str, str]] = []
    for upload_file, doc_type in zip(documents, document_types, strict=True):
        buffer = await upload_file.read()
        try:
            doc = await _validate_and_store(
                buffer,
                upload_file.content_type or "",
                upload_file.filename or "upload",
                doc_type,
                current_user.id,
            )
        except HTTPException as exc:
            results.append({"originalFilename": upload_file.filename, "error": exc.detail})
            continue
        created.append((doc["_id"], buffer, doc["mimeType"], doc["documentType"]))
        results.append({"document": _serialize_document(doc)})

    # Strictly sequential - one file's full OCR->AI->save pipeline completes
    # before the next starts, matching the old app's single-slot queue.
    # process_document() already catches every Exception internally and
    # marks the doc "failed" rather than raising - this outer guard is
    # defense-in-depth so that even a failure INSIDE that safety net (e.g.
    # the DB write in its own except-block failing) can't abort the rest of
    # the batch. An unhandled exception here would otherwise stop the loop
    # at whichever file triggered it, silently leaving every later file in
    # the batch stuck at "uploaded" forever.
    async def _run_sequentially() -> None:
        for doc_id, buffer, mime_type, doc_type in created:
            try:
                await process_document(doc_id, buffer, mime_type, doc_type)
            except Exception as exc:  # noqa: BLE001
                logger.error(f"Bulk-upload file {doc_id} crashed the pipeline: {exc}")
                db = get_database()
                try:
                    await db.documents.update_one(
                        {"_id": doc_id},
                        {
                            "$set": {
                                "uploadStatus": "failed",
                                "processingError": (
                                    "Something went wrong while processing this document."
                                ),
                                "updatedAt": datetime.now(UTC),
                            }
                        },
                    )
                except Exception:  # noqa: BLE001
                    pass

    background_tasks.add_task(_run_sequentially)
    return {"results": results}


def _serialize_document(doc: dict) -> dict:
    out = {k: v for k, v in doc.items() if k != "ocrTextHidden"}
    out["_id"] = str(out["_id"])
    out["userId"] = str(out["userId"])
    if out.get("gridFsFileId"):
        out["gridFsFileId"] = str(out["gridFsFileId"])
    return out


def _escape_regex(value: str) -> str:
    return re.escape(value)


@router.get("")
async def list_documents(
    document_type: str | None = Query(default=None, alias="documentType"),
    number: str | None = Query(default=None),
    date: str | None = Query(default=None),
    range: Literal["today", "week", "month", "year"] | None = Query(default=None),
    page: int | None = Query(default=None),
    limit: int | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Paginated only when ?page= is passed (My Documents page). No ?page ->
    full-list behavior, since the Dashboard needs every document back to
    compute its stats/recent-docs widget from - ported 1:1 from the old
    Express route's contract (see old backend/routes/documents.js)."""
    db = get_database()
    filter_query: dict = {"userId": current_user.id, "isDeleted": {"$ne": True}}

    if document_type in DOCUMENT_TYPES:
        filter_query["documentType"] = document_type
    if number and number.strip():
        regex = {"$regex": _escape_regex(number.strip()), "$options": "i"}
        filter_query["$or"] = [
            {"taxInvoiceNo": regex},
            {"referenceNo": regex},
            {"number": regex},
        ]
    if date and date.strip():
        filter_query["date"] = date.strip()
    if range in RANGE_DAYS:
        cutoff = datetime.now(UTC) - timedelta(days=RANGE_DAYS[range])
        filter_query["createdAt"] = {"$gte": cutoff}

    if page:
        lim = max(1, limit or 30)
        pg = max(1, page)
        skip = (pg - 1) * lim
        total_documents = await db.documents.count_documents(filter_query)
        cursor = db.documents.find(filter_query).sort("createdAt", -1).skip(skip).limit(lim)
        documents = [_serialize_document(d) async for d in cursor]
        return {
            "documents": documents,
            "totalDocuments": total_documents,
            "totalPages": max(1, -(-total_documents // lim)),
            "currentPage": pg,
        }

    cursor = db.documents.find(filter_query).sort("createdAt", -1)
    documents = [_serialize_document(d) async for d in cursor]
    by_document_type = {"Tax Invoice": 0, "Delivery Challan": 0}
    for d in documents:
        if d["documentType"] in by_document_type:
            by_document_type[d["documentType"]] += 1
    return {"documents": documents, "byDocumentType": by_document_type}


@router.get("/training-stats")
async def training_stats(current_user: CurrentUser = Depends(get_current_user)) -> dict:
    db = get_database()
    base_filter = {"userId": current_user.id, "isDeleted": {"$ne": True}}
    trained_count = await db.documents.count_documents({**base_filter, "uploadStatus": "processed"})
    corrected_count = await db.documents.count_documents({**base_filter, "edited": True})
    return {"trainedCount": trained_count, "correctedCount": corrected_count}


def _build_range_filter(
    user_id: ObjectId, older_than_months: int | None, year: int | None
) -> tuple[dict, datetime | None, datetime | None]:
    """Shared by the read-only preview and the actual purge-range delete, so
    "what will be deleted" and "what gets deleted" can never drift apart.
    Exactly one of older_than_months/year must be set (400 otherwise) - the
    single validation point for both endpoints."""
    if (older_than_months is None) == (year is None):
        raise HTTPException(
            status_code=400, detail="Specify exactly one of olderThanMonths or year."
        )
    # older_than_months arrives typed as plain int (not Literal[3, 6, 9]) on
    # the GET preview's Query param - FastAPI/pydantic Literal validation
    # doesn't coerce a query string ("6") the way it coerces JSON body
    # numbers, so the DELETE body keeps the Literal (422 on garbage there);
    # this is the one shared checkpoint for both callers.
    if older_than_months is not None and older_than_months not in (3, 6, 9):
        raise HTTPException(status_code=400, detail="olderThanMonths must be 3, 6, or 9.")
    filter_query: dict = {"userId": user_id, "isDeleted": {"$ne": True}}
    if year is not None:
        range_start = datetime(year, 1, 1, tzinfo=UTC)
        range_end = datetime(year + 1, 1, 1, tzinfo=UTC)
        filter_query["createdAt"] = {"$gte": range_start, "$lt": range_end}
        return filter_query, range_start, range_end

    # Rolling window from "now", not calendar-aligned - N*30 days, same
    # simplifying convention this file already uses for RANGE_DAYS above
    # (deterministic, avoids month-length/timezone-boundary edge cases).
    assert older_than_months is not None  # guaranteed by the XOR check above
    range_end = datetime.now(UTC) - timedelta(days=older_than_months * 30)
    filter_query["createdAt"] = {"$lt": range_end}
    return filter_query, None, range_end


@router.get("/purge-range/preview")
async def purge_range_preview(
    older_than_months: int | None = Query(default=None, alias="olderThanMonths"),
    year: int | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Read-only - no confirmation needed. Registered before GET /{doc_id} so
    "purge-range" is never matched as a doc_id (same reasoning as DELETE
    /purge-all above DELETE /{doc_id})."""
    db = get_database()
    filter_query, range_start, range_end = _build_range_filter(
        current_user.id, older_than_months, year
    )
    docs = await db.documents.find(filter_query, {"size": 1}).to_list(None)
    return {
        "count": len(docs),
        "dateRangeStart": range_start,
        "dateRangeEnd": range_end,
        "approxSizeBytes": sum(d.get("size") or 0 for d in docs),
    }


async def _verify_delete_confirmation(
    current_user: CurrentUser,
    body: ConfirmedDeleteRequest,
    expected_phrase: str,
    blocked_action: str,
) -> None:
    """Shared gate for both irreversible bulk-delete endpoints. Re-fetches the
    user (never trusts anything off the JWT) and requires BOTH the account
    password and an exact typed phrase - there's no email/OTP channel
    anywhere in this app to use instead (see CLAUDE.md). Every blocked
    attempt is audit-logged before raising; the caller logs the success case
    itself once the actual delete completes."""
    # 400, not 401, for the password/no-password failures below: the axios
    # client interceptor (client.js) treats ANY 401 outside /auth/* as an
    # expired session - it force-clears the token and redirects to /login.
    # That's correct for a stale JWT but would be a broken UX here (kicks the
    # user off the Danger Zone dialog they're actively filling in just
    # because they mistyped their password).
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


async def _get_owned_document(doc_id: PyObjectId, user_id: ObjectId) -> dict:
    db = get_database()
    doc = await db.documents.find_one(
        {"_id": doc_id, "userId": user_id, "isDeleted": {"$ne": True}}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    return doc


@router.get("/{doc_id}")
async def get_document(
    doc_id: PyObjectId, current_user: CurrentUser = Depends(get_current_user)
) -> dict:
    doc = await _get_owned_document(doc_id, current_user.id)
    return {"document": _serialize_document(doc)}


@router.get("/{doc_id}/download")
async def download_document(
    doc_id: PyObjectId, current_user: CurrentUser = Depends(get_current_user)
) -> Response:
    doc = await _get_owned_document(doc_id, current_user.id)
    if doc.get("filePurged"):
        raise HTTPException(
            status_code=400,
            detail=("Original file removed to save space - extracted data below remains accurate."),
        )
    buffer = await download_buffer(doc["gridFsFileId"])
    safe_filename = _sanitize_content_disposition_filename(doc["originalFilename"])
    return Response(
        content=buffer,
        media_type=doc["mimeType"],
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )


@router.post("/{doc_id}/reprocess")
async def reprocess_document(
    doc_id: PyObjectId,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(get_current_user),
) -> MessageResponse:
    doc = await _get_owned_document(doc_id, current_user.id)
    if doc.get("filePurged"):
        raise HTTPException(
            status_code=400,
            detail=(
                "The original file was removed to save space, so this document "
                "can no longer be reprocessed."
            ),
        )
    buffer = await download_buffer(doc["gridFsFileId"])

    db = get_database()
    await db.documents.update_one(
        {"_id": doc["_id"]},
        {
            "$set": {
                "uploadStatus": "uploaded",
                "processingError": None,
                "taxInvoiceNo": None,
                "referenceNo": None,
                "number": None,
                "date": None,
                "edited": False,
                "exported": False,
                "updatedAt": datetime.now(UTC),
            }
        },
    )

    async def _reprocess_then_stamp() -> None:
        await process_document(doc["_id"], buffer, doc["mimeType"], doc["documentType"])
        await db.documents.update_one(
            {"_id": doc["_id"]}, {"$set": {"reprocessedAt": datetime.now(UTC)}}
        )

    background_tasks.add_task(_reprocess_then_stamp)
    return MessageResponse(message="Reprocessing started. Check document status shortly.")


@router.delete("/purge-all")
async def purge_all_user_data(
    body: ConfirmedDeleteRequest,
    current_user: CurrentUser = Depends(get_current_user),
) -> MessageResponse:
    """Full nuclear delete - permanently wipes EVERY record this user owns
    (documents, GridFS files, workbooks, settings, exported-row log) plus the
    physical .xlsx files on disk. Genuinely irreversible: no soft-delete
    flag, no recovery path. Gated behind password + typed phrase ("DELETE",
    matching the frontend's existing constant) via _verify_delete_confirmation.
    Registered before DELETE /{doc_id} so Starlette's path-pattern matching
    (which tries routes in registration order) picks this static route
    instead of matching "purge-all" as a doc_id and failing PyObjectId
    validation."""
    db = get_database()
    user_id = current_user.id

    await _verify_delete_confirmation(current_user, body, "DELETE", "purge_all_blocked")

    await log_action(user_id, "purge_all_data", {})

    docs = await db.documents.find({"userId": user_id}, {"gridFsFileId": 1}).to_list(None)
    for doc in docs:
        if doc.get("gridFsFileId"):
            try:
                await delete_file(doc["gridFsFileId"])
            except Exception:  # noqa: BLE001
                pass

    workbooks = await db.workbooks.find({"userId": user_id}, {"filename": 1}).to_list(None)
    for wb in workbooks:
        target = excel_service.file_path(f"{user_id}_{wb['filename']}")
        target.unlink(missing_ok=True)
        target.with_suffix(".lock").unlink(missing_ok=True)

    await db.documents.delete_many({"userId": user_id})
    await db.workbooks.delete_many({"userId": user_id})
    await db.settings.delete_many({"userId": user_id})
    await db.exportedrows.delete_many({"userId": user_id})

    return MessageResponse(message="All your data has been permanently deleted.")


async def _remove_exported_rows_from_workbooks(exported_rows: list[dict]) -> tuple[int, list[str]]:
    """Groups the exported-row records being purged by workbookId, surgically
    removes just those rows from each workbook's physical .xlsx (matching by
    (documentType, formatted-number, date) - rows have no stable ID, same
    convention as excel/service.py's append path), and reports which
    workbooks ended up with zero data rows left across every sheet (deleted
    from disk entirely rather than left as an empty shell)."""
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
            # File is gone from disk - mark the DB row inactive/archived
            # (same field pair year-rollover already uses) rather than
            # hard-deleting it, so historical references (audit context,
            # ExportedRow rows for OTHER users sharing export-history) still
            # resolve a filename/year. If this happened to be the user's
            # CURRENTLY active workbook, append_row's existing self-heal
            # (recreate the file if the target is missing on next save)
            # keeps future saves working even though this row is now inactive.
            await db.workbooks.update_one(
                {"_id": workbook_id},
                {"$set": {"isActive": False, "archivedAt": now, "updatedAt": now}},
            )
    return total_removed, fully_deleted_filenames


@router.delete("/purge-range")
async def purge_range_user_data(
    body: PurgeRangeRequest, current_user: CurrentUser = Depends(get_current_user)
) -> dict:
    """Partial delete gated the same way as /purge-all (password + typed
    phrase, "DELETE RANGE" - deliberately distinct from /purge-all's "DELETE"
    to reduce fat-finger cross-action mistakes), scoped to documents whose
    createdAt falls in the requested age bucket/year. Unlike /purge-all this
    surgically removes only the matching Excel rows rather than deleting
    whole workbooks (see _remove_exported_rows_from_workbooks), except when a
    workbook's rows are removed down to zero. Registered before DELETE
    /{doc_id} for the same route-ordering reason as /purge-all above."""
    db = get_database()
    user_id = current_user.id
    filter_query, _range_start, _range_end = _build_range_filter(
        user_id, body.older_than_months, body.year
    )

    await log_action(
        user_id,
        "purge_range_attempted",
        {"olderThanMonths": body.older_than_months, "year": body.year},
    )
    await _verify_delete_confirmation(current_user, body, "DELETE RANGE", "purge_range_blocked")

    docs = await db.documents.find(filter_query).to_list(None)
    doc_ids = [d["_id"] for d in docs]

    for doc in docs:
        if doc.get("gridFsFileId"):
            try:
                await delete_file(doc["gridFsFileId"])
            except Exception:  # noqa: BLE001
                pass

    rows_removed = 0
    workbooks_fully_deleted: list[str] = []
    if doc_ids:
        exported_rows = await db.exportedrows.find({"documentId": {"$in": doc_ids}}).to_list(None)
        rows_removed, workbooks_fully_deleted = await _remove_exported_rows_from_workbooks(
            exported_rows
        )
        await db.documents.delete_many({"_id": {"$in": doc_ids}})
        await db.exportedrows.delete_many({"documentId": {"$in": doc_ids}})

    await log_action(
        user_id,
        "purge_range_data",
        {
            "olderThanMonths": body.older_than_months,
            "year": body.year,
            "documentsDeleted": len(doc_ids),
            "rowsRemoved": rows_removed,
            "workbooksFullyDeleted": workbooks_fully_deleted,
        },
    )

    return {
        "message": f"{len(doc_ids)} document(s) permanently deleted.",
        "documentsDeleted": len(doc_ids),
        "workbooksFullyDeleted": workbooks_fully_deleted,
        "rowsRemoved": rows_removed,
    }


@router.delete("/{doc_id}")
async def delete_document(
    doc_id: PyObjectId, current_user: CurrentUser = Depends(get_current_user)
) -> MessageResponse:
    doc = await _get_owned_document(doc_id, current_user.id)
    db = get_database()
    await db.documents.update_one(
        {"_id": doc["_id"]},
        {"$set": {"isDeleted": True, "deletedAt": datetime.now(UTC)}},
    )
    if doc.get("gridFsFileId"):
        try:
            await delete_file(doc["gridFsFileId"])
        except Exception:  # noqa: BLE001
            pass
    await log_action(current_user.id, "document_deleted", {"documentId": str(doc["_id"])})
    return MessageResponse(message="Document deleted successfully.")


@router.post("/{doc_id}/purge-file")
async def purge_document_file(
    doc_id: PyObjectId, current_user: CurrentUser = Depends(get_current_user)
) -> MessageResponse:
    """Space-saving, irreversible action: permanently removes the stored
    original file from GridFS while leaving the Document record's extracted
    metadata (number, date, type, status, confidence, timestamps) untouched.
    Distinct from DELETE /{doc_id} (soft-delete of the whole record) - this
    only purges the heavy file data."""
    doc = await _get_owned_document(doc_id, current_user.id)
    if doc.get("filePurged"):
        raise HTTPException(
            status_code=400, detail="This document's original file has already been removed."
        )
    if not doc.get("gridFsFileId"):
        raise HTTPException(status_code=400, detail="No original file is stored for this document.")

    await delete_file(doc["gridFsFileId"])

    db = get_database()
    now = datetime.now(UTC)
    await db.documents.update_one(
        {"_id": doc["_id"]}, {"$set": {"filePurged": True, "filePurgedAt": now, "updatedAt": now}}
    )
    await log_action(current_user.id, "document_file_purged", {"documentId": str(doc["_id"])})
    return MessageResponse(
        message="Original file permanently removed. Extracted data remains fully accessible."
    )


@router.patch("/{doc_id}/correct")
async def correct_document(
    doc_id: PyObjectId, body: CorrectRequest, current_user: CurrentUser = Depends(get_current_user)
) -> dict:
    if body.field not in EDITABLE_FIELDS:
        raise HTTPException(status_code=400, detail="That field cannot be edited.")
    if not body.value or not body.value.strip():
        raise HTTPException(status_code=400, detail="Please enter a value before saving.")

    doc = await _get_owned_document(doc_id, current_user.id)

    # A document still mid-OCR can have its uploadStatus flip to 'processed'
    # right after this handler reads it and silently overwrite a correction
    # made in that window - block corrections until processing has actually
    # finished (race-condition fix ported from the old app).
    if doc["uploadStatus"] not in ("processed", "failed"):
        raise HTTPException(
            status_code=409,
            detail=(
                "This document is still being processed. "
                "Please wait for it to finish before editing."
            ),
        )

    if body.field not in FIELDS_BY_DOCUMENT_TYPE[doc["documentType"]]:
        raise HTTPException(
            status_code=400,
            detail=f"That field cannot be edited on a {doc['documentType']} document.",
        )

    value = body.value.strip()
    if body.field == "date":
        normalized = normalize_date_to_ddmmyyyy(value)
        if not normalized:
            raise HTTPException(status_code=400, detail="Date must be in DD/MM/YYYY format.")
        value = normalized

    old_value = doc.get(body.field)
    db = get_database()
    now = datetime.now(UTC)
    set_fields = {
        body.field: value,
        "edited": True,
        # A correction changes what would be written to Excel - the previous
        # export (if any) no longer reflects this document's current values.
        "exported": False,
        # Manually verified by the user - no longer a "please verify" case.
        f"{body.field}Confidence": 100,
        "updatedAt": now,
    }
    if body.field in ("taxInvoiceNo", "number", "date"):
        # Manual entry supersedes the auto-correction pass - no longer
        # something the OCR correction layer touched.
        set_fields[f"{body.field}AutoCorrected"] = False
    await db.documents.update_one({"_id": doc["_id"]}, {"$set": set_fields})
    await db.corrections.insert_one(
        {
            "documentId": doc["_id"],
            "fieldLabel": body.field,
            "fieldKey": body.field,
            "oldValue": old_value,
            "newValue": value,
            "correctedAt": now,
            "createdAt": now,
            "updatedAt": now,
        }
    )

    updated = await db.documents.find_one({"_id": doc["_id"]})
    assert updated is not None
    return {"message": "Field corrected successfully.", "document": _serialize_document(updated)}


async def recover_interrupted_uploads() -> int:
    """Requeues anything stuck in 'uploaded' status after a server restart -
    ported from the old app's recoverInterruptedUploads(), called once at
    startup from main.py's lifespan."""
    db = get_database()
    cursor = db.documents.find({"uploadStatus": "uploaded", "isDeleted": {"$ne": True}})
    docs = await cursor.to_list(length=None)
    for doc in docs:
        try:
            buffer = await download_buffer(doc["gridFsFileId"])
            await process_document(doc["_id"], buffer, doc["mimeType"], doc["documentType"])
        except Exception:  # noqa: BLE001
            await db.documents.update_one(
                {"_id": doc["_id"]},
                {
                    "$set": {
                        "uploadStatus": "failed",
                        "processingError": (
                            "Processing was interrupted and could not be recovered. "
                            "Please reprocess this document."
                        ),
                    }
                },
            )
    return len(docs)
