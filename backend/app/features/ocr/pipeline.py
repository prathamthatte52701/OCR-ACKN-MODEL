import asyncio
import os
import tempfile
from datetime import UTC, datetime

from bson import ObjectId
from loguru import logger

from app.core.audit_log import safe_log_action
from app.core.database import get_database
from app.features.ocr.ai_extraction import extract_header
from app.features.ocr.paddle_runner import (
    OCR_TIMEOUT_SECONDS_IMAGE,
    OCR_TIMEOUT_SECONDS_PDF,
    classify_page_orientation,
    run_ocr,
)
from app.features.ocr.page_normalize import normalize_photo
from app.features.ocr.preprocessing import (
    HEADER_CROP_RATIO,
    LARGE_TEXT_DET_LIMIT,
    LARGE_TEXT_DET_LIMIT_STEP,
    ORIENTATION_CHECK_STEP,
    PHOTO_HEADER_CROP_RATIO,
    assess_and_preprocess,
    crop_header,
    get_pdf_header_text_or_image,
)

_ocr_lock = asyncio.Lock()  # only 1 OCR job runs at a time - mirrors old app's single-slot queue

# Timestamp the lock was last acquired, or None while free. asyncio.Lock can't
# itself deadlock from a hard thread crash (asyncio.wait_for's timeout still
# fires and the `async with` block still exits), but a wedge is still
# possible if something upstream hangs holding it without going through
# run_ocr's timeout path. Tracking this lets /health tell "OCR subsystem
# stuck" apart from "app fine, just mid-job."
_lock_held_since: datetime | None = None
# Generous ceiling above the longest legitimate hold (OCR_TIMEOUT_SECONDS_IMAGE)
# to absorb scheduling jitter before flagging a false positive.
_LOCK_WEDGED_THRESHOLD_SECONDS = OCR_TIMEOUT_SECONDS_IMAGE + 60


def ocr_lock_status() -> dict:
    """Used by /health. wedged=True only if the lock has been held longer
    than any legitimate single-document OCR call should ever take."""
    if _lock_held_since is None:
        return {"held": False, "wedged": False}
    held_seconds = (datetime.now(UTC) - _lock_held_since).total_seconds()
    return {"held": True, "wedged": held_seconds > _LOCK_WEDGED_THRESHOLD_SECONDS}


# One normalization at a time: each decodes and warps a full-size photo, and
# a bulk upload/reprocess used to run dozens concurrently (memory spike).
_normalize_slot = asyncio.Semaphore(1)


async def _normalize_photo_page(buffer: bytes) -> bytes:
    """normalize_photo needs the orientation classifier only for photos that
    look sideways or have background around the paper - it calls it lazily,
    so the lock is held (via the sync callback below) only in those cases.
    Fails open: any problem returns the original bytes."""
    loop = asyncio.get_running_loop()

    def classify(png: bytes) -> tuple[int, float]:
        # Runs in a worker thread (see to_thread below); take the SAME
        # process-wide OCR slot via the loop so it can never overlap run_ocr.
        fut = asyncio.run_coroutine_threadsafe(_classify_under_lock(png), loop)
        # The OCR slot can be busy with a long queue of other jobs ahead of
        # this one; a short timeout here silently skipped the rotation fix
        # for any document that waited. Match the OCR budget instead.
        return fut.result(timeout=OCR_TIMEOUT_SECONDS_IMAGE + 60)

    try:
        async with _normalize_slot:
            page_bytes, steps = await asyncio.to_thread(normalize_photo, buffer, classify)
        if steps:
            logger.info(f"Photo page normalization: {steps}")
        return page_bytes
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Photo page normalization failed, using original: {exc}")
        return buffer


async def _classify_under_lock(png: bytes) -> tuple[int, float]:
    async with _ocr_lock:
        return await asyncio.to_thread(classify_page_orientation, png)


async def _extract_header_text(buffer: bytes, mime_type: str) -> str | None:
    """Returns the header-region OCR/text-layer text, or None on failure -
    mirrors the old app's extractHeaderText()."""
    cut_from_background = False
    try:
        if mime_type == "application/pdf":
            text, header_png = await get_pdf_header_text_or_image(buffer)
            if text:
                return text
            if header_png is None:
                return None
            image_bytes = header_png
        else:
            # Photos only: find the paper and fix sideways/upside-down shots
            # so the fixed top-30% crop below lands on the header. A scan or
            # tight upright photo comes back as the original bytes, untouched.
            # The orientation classifier is a Paddle predictor, so it runs
            # under the same lock as OCR; the lock is released before the
            # OCR block below re-acquires it.
            page_bytes = await _normalize_photo_page(buffer)
            cut_from_background = page_bytes != buffer
            image_bytes = crop_header(
                page_bytes, PHOTO_HEADER_CROP_RATIO if cut_from_background else HEADER_CROP_RATIO
            )

        # Feature 6: quality-gated preprocessing on the header crop itself -
        # skips straight through (unmodified bytes) when the crop is already
        # good quality. See preprocessing.py's module-level docstring for the
        # scope boundaries (header-only, not full-page rotation recovery).
        # Photos cut out of a background are small and soft; the binarizing steps
        # turned digits into noise (8<->0, 3<->6, 2026 -> 2028), so raw is better.
        if mime_type != "application/pdf" and cut_from_background:
            preprocess_steps: list[str] = []
        else:
            image_bytes, preprocess_steps = assess_and_preprocess(image_bytes)
        if preprocess_steps:
            logger.info(f"OCR preprocessing steps triggered: {preprocess_steps}")
        use_doc_orientation_classify = ORIENTATION_CHECK_STEP in preprocess_steps
        text_det_limit_side_len = (
            LARGE_TEXT_DET_LIMIT if LARGE_TEXT_DET_LIMIT_STEP in preprocess_steps else None
        )

        # Timeout is keyed on the ORIGINAL upload's mime type, not the
        # post-processing form (a PDF page is also "an image" by the time it
        # reaches run_ocr, but should keep the PDF budget).
        timeout = (
            OCR_TIMEOUT_SECONDS_PDF if mime_type == "application/pdf" else OCR_TIMEOUT_SECONDS_IMAGE
        )

        suffix = ".png"
        fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(image_bytes)
            global _lock_held_since
            async with _ocr_lock:
                _lock_held_since = datetime.now(UTC)
                try:
                    text = await asyncio.wait_for(
                        asyncio.to_thread(
                            run_ocr,
                            tmp_path,
                            use_doc_orientation_classify=use_doc_orientation_classify,
                            text_det_limit_side_len=text_det_limit_side_len,
                        ),
                        timeout=timeout,
                    )
                except TimeoutError:
                    text = None
                finally:
                    _lock_held_since = None
            return text
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Header OCR error: {exc}")
        return None


async def _update_active_document(doc_id: ObjectId, update: dict) -> bool:
    """Returns False when no active document matched (e.g. deleted meanwhile)."""
    db = get_database()
    update["updatedAt"] = datetime.now(UTC)
    res = await db.documents.update_one(
        {"_id": doc_id, "isDeleted": {"$ne": True}}, {"$set": update}
    )
    return res.matched_count > 0


async def _log_processed(doc_id: ObjectId) -> None:
    try:
        doc = await get_database().documents.find_one(
            {"_id": doc_id}, {"userId": 1, "documentType": 1, "originalFilename": 1}
        )
        if not doc:
            return
        await safe_log_action(
            doc["userId"],
            "document_processed",
            {
                "documentId": str(doc_id),
                "documentType": doc.get("documentType"),
                "filename": doc.get("originalFilename"),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Audit log 'document_processed' failed: {exc}")


async def process_document(
    doc_id: ObjectId, buffer: bytes, mime_type: str, document_type: str
) -> None:
    """Full OCR -> AI extraction -> validation pipeline for one document -
    mirrors the old app's processDocument()."""
    try:
        header_text = await _extract_header_text(buffer, mime_type)
        if not header_text or not header_text.strip():
            await _update_active_document(
                doc_id,
                {
                    "uploadStatus": "failed",
                    "processingError": (
                        "We could not read any text from this document. Try a clearer "
                        "photo or scan, or a higher-quality PDF."
                    ),
                },
            )
            return

        try:
            result = await extract_header(document_type, header_text)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"AI extraction error: {exc}")
            await _update_active_document(
                doc_id,
                {
                    "uploadStatus": "failed",
                    "ocrTextHidden": header_text,
                    "processingError": (
                        "AI analysis is unavailable. Please check the Groq API key "
                        "or try again later."
                    ),
                },
            )
            return

        update = {
            "uploadStatus": "processed",
            "ocrTextHidden": header_text,
            "processingError": None,
            "processedAt": datetime.now(UTC),
        }
        for key in (
            "taxInvoiceNo",
            "referenceNo",
            "number",
            "date",
            "taxInvoiceNoNeedsReview",
            "referenceNoNeedsReview",
            "taxInvoiceNoAutoCorrected",
            "numberAutoCorrected",
            "dateAutoCorrected",
        ):
            if key in result:
                update[key] = result[key]
        if await _update_active_document(doc_id, update):
            await _log_processed(doc_id)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"process_document error: {exc}")
        await _update_active_document(
            doc_id,
            {
                "uploadStatus": "failed",
                "processingError": "Something went wrong while processing this document.",
            },
        )
