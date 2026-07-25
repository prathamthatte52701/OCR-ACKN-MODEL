import re
from datetime import UTC, datetime
from pathlib import PurePosixPath

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

from app.core.audit_log import log_action
from app.core.database import get_database
from app.core.object_id import PyObjectId
from app.core.rate_limit import limiter
from app.features.auth.dependencies import CurrentUser, get_current_user
from app.features.documents.gridfs_service import delete_file, download_buffer, upload_buffer
from app.features.documents.schemas import CorrectRequest, MessageResponse
from app.features.excel import service as excel_service
from app.features.ocr.extraction import normalize_date_to_ddmmyyyy
from app.features.ocr.pipeline import process_document
from app.features.ocr.preprocessing import get_pdf_page_count

router = APIRouter()

DOCUMENT_TYPES = {"Tax Invoice", "Delivery Challan"}
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
    async def _run_sequentially() -> None:
        for doc_id, buffer, mime_type, doc_type in created:
            await process_document(doc_id, buffer, mime_type, doc_type)

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
    current_user: CurrentUser = Depends(get_current_user),
) -> MessageResponse:
    """Full nuclear delete - permanently wipes EVERY record this user owns
    (documents, GridFS files, workbooks, settings, exported-row log) plus the
    physical .xlsx files on disk. Genuinely irreversible: no soft-delete
    flag, no recovery path. Registered before DELETE /{doc_id} so Starlette's
    path-pattern matching (which tries routes in registration order) picks
    this static route instead of matching "purge-all" as a doc_id and
    failing PyObjectId validation."""
    db = get_database()
    user_id = current_user.id

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
