import io
import re
import zipfile
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
from app.core.orphaned_files import record_orphaned_file
from app.core.rate_limit import limiter
from app.features.auth.dependencies import CurrentUser, get_current_user
from app.features.documents.gridfs_service import delete_file, download_buffer, upload_buffer
from app.features.documents.schemas import (
    CorrectRequest,
    DownloadAllRequest,
    MessageResponse,
    PurgeFileResponse,
)
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


_UNSAFE_ZIP_ENTRY_CHARS_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')
_EXTENSION_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "application/pdf": ".pdf",
}


def _zip_entry_name(doc: dict, seen: dict[str, int]) -> str:
    """Builds a distinguishable in-archive filename from the document's own
    identifying number/date - e.g. "TI-482910_15-03-2026.pdf" - rather than
    a generic id-based name, so extracted files are recognizable at a
    glance. `seen` dedupes within one zip (same number+date could repeat
    across genuinely different documents)."""
    if doc["documentType"] == "Tax Invoice":
        parts = [p for p in (doc.get("taxInvoiceNo"), doc.get("referenceNo")) if p]
        base = "-".join(parts) if parts else str(doc["_id"])
    else:
        base = doc.get("number") or str(doc["_id"])
    if doc.get("date"):
        base = f"{base}_{doc['date'].replace('/', '-')}"

    ext = PurePosixPath(doc.get("originalFilename") or "").suffix
    if not ext:
        ext = _EXTENSION_BY_MIME.get(doc.get("mimeType") or "", "")

    safe_base = _UNSAFE_ZIP_ENTRY_CHARS_RE.sub("_", base).strip() or str(doc["_id"])
    count = seen.get(safe_base, 0)
    seen[safe_base] = count + 1
    suffix = f" ({count})" if count else ""
    return f"{safe_base}{suffix}{ext}"


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


# Action types relevant to a regular user's own "My Activity" timeline -
# admin-only/system entries (login, signup, password_change, user_updated,
# admin_nuke_*, orphaned_file_*, purge_*_blocked, ...) are deliberately
# excluded. Only "document_deleted" and "document_file_purged" are actually
# logged for a user's own documents today (upload/OCR-processing, manual
# corrections, and reprocess don't call log_action anywhere in this
# codebase - corrections go to the separate `corrections` collection
# instead) - the other names are listed for forward-compatibility only, so
# nothing else needs to change here if logging is ever added for them.
MY_ACTIVITY_ACTIONS = [
    "document_processed",
    "document_uploaded",
    "document_corrected",
    "document_edited",
    "document_deleted",
    "document_file_purged",
    "document_reprocessed",
]


def _serialize_activity(log: dict, doc_lookup: dict) -> dict:
    context = log.get("context") or {}
    doc = doc_lookup.get(context.get("documentId"))
    return {
        "id": str(log["_id"]),
        "action": log["action"],
        "context": context,
        "createdAt": log.get("createdAt"),
        "document": (
            {
                "id": str(doc["_id"]),
                "documentType": doc.get("documentType"),
                "number": doc.get("taxInvoiceNo") or doc.get("number"),
                "date": doc.get("date"),
            }
            if doc
            else None
        ),
    }


@router.get("/my-activity")
async def my_activity(
    page: int | None = Query(default=None),
    limit: int | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Read-only timeline of the authenticated user's OWN activity, sourced
    entirely from the existing auditlogs collection - no new logging, no
    change to what gets logged or when. Always scoped to current_user.id
    from the JWT (re-verified via get_current_user, same as every other
    user-scoped route) - there is no id parameter here for a caller to
    manipulate. Paginated at 40/page, distinct from the 30/page used
    elsewhere - intentional, not a bug. Registered before GET /{doc_id} so
    "my-activity" is never matched as a doc_id (same reasoning as the
    former /purge-* routes)."""
    db = get_database()
    lim = max(1, limit or 40)
    pg = max(1, page or 1)
    skip = (pg - 1) * lim
    filt = {"userId": current_user.id, "action": {"$in": MY_ACTIVITY_ACTIONS}}

    total = await db.auditlogs.count_documents(filt)
    cursor = db.auditlogs.find(filt).sort("createdAt", -1).skip(skip).limit(lim)
    logs = await cursor.to_list(length=None)

    doc_ids: list[ObjectId] = []
    for log in logs:
        doc_id_str = (log.get("context") or {}).get("documentId")
        if doc_id_str:
            try:
                doc_ids.append(ObjectId(doc_id_str))
            except Exception:  # noqa: BLE001
                pass
    doc_lookup: dict[str, dict] = {}
    if doc_ids:
        # Deliberately unfiltered by isDeleted - a soft-deleted document
        # still has a live record and should still resolve here; only a
        # hard-deleted one (no tier of delete in this app does that to a
        # user's OWN documents today) would fail this lookup, which is
        # exactly the "log entry persists independently" behavior wanted.
        async for d in db.documents.find(
            {"_id": {"$in": doc_ids}},
            {"documentType": 1, "taxInvoiceNo": 1, "number": 1, "date": 1},
        ):
            doc_lookup[str(d["_id"])] = d

    return {
        "activity": [_serialize_activity(log, doc_lookup) for log in logs],
        "totalActivity": total,
        "totalPages": max(1, -(-total // lim)),
        "currentPage": pg,
    }


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


@router.post("/download-all")
async def download_all_documents(
    body: DownloadAllRequest, current_user: CurrentUser = Depends(get_current_user)
) -> Response:
    """ "Download All" for one documents page: bundles every requested
    document's original file into a single ZIP, same page-scoping contract
    as bulk-save (excel/router.py::bulk_save_documents_to_excel) - the
    frontend sends exactly the ids currently on that page. Any id that
    doesn't belong to this user (ownership lookup 404s the same way
    _get_owned_document does, just non-fatally here), any document with no
    file (filePurged, or a GridFS fetch that fails for any reason) is
    silently skipped and counted rather than aborting the whole archive -
    a manipulated id list can only ever skip an entry, never leak another
    user's file into the zip."""
    db = get_database()
    seen_names: dict[str, int] = {}
    included = 0
    skipped = 0
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for doc_id in body.document_ids:
            doc = await db.documents.find_one(
                {"_id": doc_id, "userId": current_user.id, "isDeleted": {"$ne": True}}
            )
            if not doc or doc.get("filePurged") or not doc.get("gridFsFileId"):
                skipped += 1
                continue
            try:
                file_buffer = await download_buffer(doc["gridFsFileId"])
            except Exception:  # noqa: BLE001
                skipped += 1
                continue
            zf.writestr(_zip_entry_name(doc, seen_names), file_buffer)
            included += 1

    await log_action(
        current_user.id,
        "documents_download_all",
        {"requested": len(body.document_ids), "included": included, "skipped": skipped},
    )
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="documents.zip"',
            "X-Download-Included": str(included),
            "X-Download-Skipped": str(skipped),
            "X-Download-Total": str(len(body.document_ids)),
        },
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
        except Exception as exc:  # noqa: BLE001
            await record_orphaned_file(
                doc["gridFsFileId"], doc["_id"], current_user.id, "soft_delete", exc
            )
    await log_action(current_user.id, "document_deleted", {"documentId": str(doc["_id"])})
    return MessageResponse(message="Document deleted successfully.")


@router.post("/{doc_id}/purge-file")
async def purge_document_file(
    doc_id: PyObjectId, current_user: CurrentUser = Depends(get_current_user)
) -> PurgeFileResponse:
    """Space-saving, irreversible action: permanently removes the stored
    original file from GridFS while leaving the Document record's extracted
    metadata (number, date, type, status, confidence, timestamps) untouched.
    Distinct from DELETE /{doc_id} (soft-delete of the whole record) - this
    only purges the heavy file data. A GridFS failure here does NOT block
    the user's action (filePurged is still set) - it's tracked in
    orphanedfiles and surfaced via gridFsCleanupFailed so the frontend can
    show a softer "flagged for admin review" message instead of a plain
    success toast."""
    doc = await _get_owned_document(doc_id, current_user.id)
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
            doc["gridFsFileId"], doc["_id"], current_user.id, "purge_file", exc
        )
        cleanup_failed = True

    db = get_database()
    now = datetime.now(UTC)
    await db.documents.update_one(
        {"_id": doc["_id"]}, {"$set": {"filePurged": True, "filePurgedAt": now, "updatedAt": now}}
    )
    await log_action(current_user.id, "document_file_purged", {"documentId": str(doc["_id"])})
    message = (
        "Original file permanently removed. Extracted data remains fully accessible."
        if not cleanup_failed
        else (
            "Your document's data was removed, but we couldn't fully clean up the original "
            "file due to a system issue. This has been flagged for admin review - no action "
            "needed from you."
        )
    )
    return PurgeFileResponse(message=message, grid_fs_cleanup_failed=cleanup_failed)


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
