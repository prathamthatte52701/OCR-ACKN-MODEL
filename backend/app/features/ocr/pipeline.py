import asyncio
import os
import tempfile
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import cv2
import numpy as np
from bson import ObjectId
from loguru import logger

from app.core.audit_log import safe_log_action
from app.core.config import settings
from app.core.database import get_database
from app.core.image_limits import ImageTooLarge, check_upload
from app.features.ocr.ai_extraction import extract_header
from app.features.ocr.extraction import extraction_success_fields
from app.features.ocr.paddle_runner import (
    OCR_TIMEOUT_SECONDS_IMAGE,
    OCR_TIMEOUT_SECONDS_PDF,
    OcrEngineError,
    classify_page_orientation,
    run_ocr,
    short_error_message,
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
from app.features.ocr.providers.errors import (
    NO_TEXT,
    OCR_ENGINE_ERROR,
    OCR_STUCK,
    OCR_TIMEOUT,
    PROCESSING_ERROR,
    AIExtractionError,
    classify_exception,
    error_detail,
    user_message,
)

_ocr_lock = asyncio.Lock()  # only 1 OCR job runs at a time - mirrors old app's single-slot queue

# The slot belongs to the OCR THREAD, not to the await that started it. A Python thread cannot be
# killed or cancelled: when the awaiting job times out (or is cancelled) the thread keeps running on
# the one shared PaddleOCR model. Releasing the lock then let the next document start a second
# run_ocr on the same model (double memory, mixed results, crashes). So on a timeout the lock is
# handed to a small background task that releases it only after the thread has really ended.
# REAL LIMIT: if the thread never ends, nothing but restarting the app clears it. The mitigation is
# the "wedged" state below: waiting and new jobs fail fast with a clear message instead of hanging.
_lock_held_since: datetime | None = None  # set while the slot is held (by a job or an orphan)
_orphan_since: datetime | None = None  # set while the holder timed out but its thread still runs
_orphan_tasks: set[asyncio.Task] = set()  # keeps the release tasks referenced (not GC'd)

# A hold longer than the longest legitimate OCR call (the image timeout) plus this grace means an
# orphaned thread has outlived its timeout: the slot is "wedged".
OCR_WEDGE_GRACE_SECONDS = 60
_LOCK_WEDGED_THRESHOLD_SECONDS = OCR_TIMEOUT_SECONDS_IMAGE + OCR_WEDGE_GRACE_SECONDS
# How often a job waiting for the slot re-checks whether the slot is wedged. Waiters are NOT
# timed out in general: a legitimate bulk queue of dozens of documents may wait a long time.
_WAIT_SLICE_SECONDS = 3.0


class OcrStuckError(Exception):
    """The OCR slot is wedged (an orphaned OCR thread never ended): fail fast instead of waiting."""


class OcrTimeoutError(Exception):
    """The OCR engine took longer than its time limit (the slot is still kept until it ends)."""


# Consecutive OCR ENGINE failures (not timeouts, not blank or bad files), for the admin warning.
# Reset by any engine call that completes without raising, including an empty result.
_engine_failures = 0
_last_engine_error: tuple[str, datetime] | None = None


def ocr_engine_status() -> dict:
    return {
        "consecutiveFailures": _engine_failures,
        "lastErrorClass": _last_engine_error[0] if _last_engine_error else None,
        "lastErrorAt": _last_engine_error[1].isoformat() if _last_engine_error else None,
    }


def _note_engine_ok() -> None:
    global _engine_failures
    _engine_failures = 0


def _note_engine_failure(cls_name: str) -> None:
    global _engine_failures, _last_engine_error
    _engine_failures += 1
    _last_engine_error = (cls_name, datetime.now(UTC))


def ocr_lock_status() -> dict:
    """Used by /health and /admin/system. wedged=True only if the slot has been held longer than
    any legitimate single-document OCR call should ever take. orphan=True means the current holder
    already timed out and only its thread is still running."""
    if _lock_held_since is None:
        return {"held": False, "wedged": False, "orphan": False, "orphanSeconds": None}
    now = datetime.now(UTC)
    held_seconds = (now - _lock_held_since).total_seconds()
    orphan = _orphan_since is not None
    return {
        "held": True,
        "wedged": held_seconds > _LOCK_WEDGED_THRESHOLD_SECONDS,
        "orphan": orphan,
        "orphanSeconds": (now - _orphan_since).total_seconds() if _orphan_since else None,
    }


def _reset_slot_for_tests() -> None:
    """Fresh lock and cleared state (tests run on a new event loop each time)."""
    global _ocr_lock, _lock_held_since, _orphan_since, _engine_failures, _last_engine_error
    _engine_failures = 0
    _last_engine_error = None
    for task in list(_orphan_tasks):
        try:
            task.cancel()
        except RuntimeError:  # its loop is already closed
            pass
    _orphan_tasks.clear()
    _ocr_lock = asyncio.Lock()
    _lock_held_since = None
    _orphan_since = None


def _release_slot() -> None:
    global _lock_held_since, _orphan_since
    _lock_held_since = None
    _orphan_since = None
    _ocr_lock.release()


async def _acquire_slot() -> None:
    """Waits for the slot in short slices so a wedged slot is noticed. The SAME acquire is kept for
    the whole wait (cancelling and re-queueing every slice would lose the waiter's place in the
    FIFO queue). Never returns holding nothing and never leaks the lock: on any exit other than a
    successful acquire the pending acquire is cancelled, and if it had just succeeded it is given
    back."""
    global _lock_held_since
    if ocr_lock_status()["wedged"]:
        raise OcrStuckError()
    acquire = asyncio.ensure_future(_ocr_lock.acquire())
    try:
        while True:
            finished, _ = await asyncio.wait({acquire}, timeout=_WAIT_SLICE_SECONDS)
            if finished:
                acquire.result()
                break
            if ocr_lock_status()["wedged"]:
                raise OcrStuckError()
    except BaseException:
        if acquire.done():
            if not acquire.cancelled() and acquire.exception() is None:
                _ocr_lock.release()  # we had just got it: give it back
        else:
            acquire.cancel()
        raise
    _lock_held_since = datetime.now(UTC)


def _resolve(done: asyncio.Future, outcome: tuple[bool, Any]) -> None:
    if not done.done():
        done.set_result(outcome)


async def _release_when_done(done: asyncio.Future, started: datetime | None) -> None:
    try:
        await done
    finally:
        _release_slot()
        if done.done() and started is not None:
            seconds = (datetime.now(UTC) - started).total_seconds()
            logger.info(
                f"Orphaned OCR thread ended after {seconds:.0f}s; the OCR slot is free again"
            )


def _hand_slot_to_thread(done: asyncio.Future, why: str) -> None:
    """The awaiting job gave up (timeout or cancellation) but its thread may still run: keep the
    slot locked until the thread really ends."""
    global _orphan_since
    if done.done():  # the thread finished right at the boundary: nothing is orphaned
        _release_slot()
        return
    started = _lock_held_since
    _orphan_since = datetime.now(UTC)
    logger.warning(
        f"OCR {why}; its thread is still running, so the OCR slot stays locked until it ends"
    )
    task = asyncio.get_running_loop().create_task(_release_when_done(done, started))
    _orphan_tasks.add(task)
    task.add_done_callback(_orphan_tasks.discard)


async def _run_in_slot[T](fn: Callable[[], T], timeout: float) -> T:
    """Runs fn in its own daemon thread while holding the OCR slot. Returns fn's result, re-raises
    its exception, raises TimeoutError when it takes longer than `timeout` (the job stops waiting at
    once, but the slot is only released when the thread ends) and OcrStuckError when the slot is
    wedged. A daemon thread (not the default executor) so a thread that never ends cannot block the
    process from exiting."""
    await _acquire_slot()
    loop = asyncio.get_running_loop()
    done: asyncio.Future[tuple[bool, Any]] = loop.create_future()

    def work() -> None:
        try:
            outcome: tuple[bool, Any] = (True, fn())
        except BaseException as exc:  # noqa: BLE001 - handed back to the awaiting job
            # SystemExit/KeyboardInterrupt from inside the engine must not escape the batch task
            outcome = (
                False,
                exc if isinstance(exc, Exception) else RuntimeError(type(exc).__name__),
            )
        try:
            loop.call_soon_threadsafe(_resolve, done, outcome)
        except RuntimeError:  # the loop is closed (app shutdown)
            pass

    try:
        threading.Thread(target=work, name="ocr-worker", daemon=True).start()
    except BaseException:
        _release_slot()
        raise
    try:
        ok, value = await asyncio.wait_for(asyncio.shield(done), timeout)
    except TimeoutError:
        if not done.done():
            _hand_slot_to_thread(done, f"timed out after {timeout:.0f}s")
            raise
        ok, value = done.result()  # it finished at the very boundary: use the result
        _release_slot()
    except asyncio.CancelledError:
        _hand_slot_to_thread(done, "job was cancelled")
        raise
    else:
        _release_slot()
    if ok:
        return value
    raise value


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
        logger.error(f"Photo page normalization failed, using original: class={type(exc).__name__}")
        return buffer


async def _classify_under_lock(png: bytes) -> tuple[int, float]:
    # Same slot and the same hand-off rule as OCR: a classifier that times out keeps the slot until
    # its thread ends. The caller (normalize_photo) fails open on any exception.
    return await _run_in_slot(lambda: classify_page_orientation(png), OCR_TIMEOUT_SECONDS_IMAGE)


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
            # Bad INPUT is not an engine failure: an undecodable image never reaches the engine
            # (it decodes pictures with OpenCV, so check with OpenCV).
            if cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR) is None:
                raise ValueError("the image could not be decoded")
            try:
                text = await _run_in_slot(
                    lambda: run_ocr(
                        tmp_path,
                        use_doc_orientation_classify=use_doc_orientation_classify,
                        text_det_limit_side_len=text_det_limit_side_len,
                    ),
                    timeout,
                )
            except TimeoutError:
                raise OcrTimeoutError(f"timed out after {timeout:.0f}s") from None
            except OcrStuckError:
                raise
            except Exception as exc:  # noqa: BLE001
                engine_error = (
                    exc if isinstance(exc, OcrEngineError) else OcrEngineError.from_exception(exc)
                )
                if engine_error.file_caused:  # the engine could not read THIS file: no text
                    logger.error(
                        f"OCR input problem: class={engine_error.cls_name} msg={engine_error.short}"
                    )
                    return None
                _note_engine_failure(engine_error.cls_name)
                raise engine_error from None
            _note_engine_ok()
            return text
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    except (OcrStuckError, OcrEngineError, OcrTimeoutError):
        raise
    except Exception as exc:  # noqa: BLE001
        # Before the engine: an unreadable file or PDF (no text, not an engine failure).
        logger.error(
            f"OCR input problem: class={type(exc).__name__} msg={short_error_message(exc)}"
        )
        return None


async def _update_active_document(doc_id: ObjectId, update: dict, run_id: str | None) -> bool:
    """Every write of a processing job goes through here and is conditional on the job's run id:
    the document must still belong to THIS job (processingRunId == run_id; None matches a
    document that has no id, i.e. one from before run ids existed). Returns False when nothing
    matched: the document was deleted meanwhile, or a newer run owns it (the job is stale and
    writes nothing)."""
    db = get_database()
    update["updatedAt"] = datetime.now(UTC)
    res = await db.documents.update_one(
        {"_id": doc_id, "isDeleted": {"$ne": True}, "processingRunId": run_id}, {"$set": update}
    )
    if res.matched_count == 0:
        still_there = await db.documents.find_one(
            {"_id": doc_id, "isDeleted": {"$ne": True}}, {"_id": 1}
        )
        if still_there:
            logger.warning("Stale processing job ignored: a newer run owns this document")
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
        logger.error(f"Audit log 'document_processed' failed: class={type(exc).__name__}")


async def _fail_ocr(
    doc_id: ObjectId,
    code: str,
    error_class: str | None,
    message: str,
    document_type: str,
    mime_type: str,
    started: float,
    run_id: str | None,
) -> None:
    """Marks the document failed with the code and its plain user message. Logs the code, the
    exception class, a short message, the document type, the mime type and the elapsed seconds:
    never the OCR text, a file name, a key or a prompt."""
    logger.error(
        f"OCR failed: code={code} class={error_class or '-'} msg={message[:200]} "
        f"doctype={document_type} mime={mime_type} elapsed={time.monotonic() - started:.1f}s"
    )
    await _update_active_document(
        doc_id,
        {
            "uploadStatus": "failed",
            "processingError": user_message(code),
            "processingErrorCode": code,
        },
        run_id,
    )


async def process_document(
    doc_id: ObjectId,
    buffer: bytes,
    mime_type: str,
    document_type: str,
    run_id: str | None = None,
) -> None:
    """Full OCR -> AI extraction -> validation pipeline for one document -
    mirrors the old app's processDocument(). run_id is the identity of this job: every write is
    conditional on the document still carrying it (see _update_active_document)."""
    try:
        # Defense in depth: covers reprocess, startup recovery and files stored before the
        # upload-time check existed. Must run before any decode.
        try:
            await check_upload(buffer, mime_type)
        except ImageTooLarge as exc:
            await _update_active_document(
                doc_id, {"uploadStatus": "failed", "processingError": str(exc)}, run_id
            )
            return
        started = time.monotonic()
        try:
            header_text = await _extract_header_text(buffer, mime_type)
        except OcrEngineError as exc:
            await _fail_ocr(
                doc_id,
                OCR_ENGINE_ERROR,
                exc.cls_name,
                exc.short,
                document_type,
                mime_type,
                started,
                run_id,
            )
            return
        except OcrTimeoutError as exc:
            await _fail_ocr(
                doc_id,
                OCR_TIMEOUT,
                "TimeoutError",
                str(exc),
                document_type,
                mime_type,
                started,
                run_id,
            )
            return
        except OcrStuckError:
            logger.error("OCR slot is wedged: failing the document fast")
            await _update_active_document(
                doc_id,
                {
                    "uploadStatus": "failed",
                    "processingError": user_message(OCR_STUCK),
                    "processingErrorCode": OCR_STUCK,
                },
                run_id,
            )
            return
        if not header_text or not header_text.strip():
            await _fail_ocr(
                doc_id, NO_TEXT, None, "no text found", document_type, mime_type, started, run_id
            )
            return

        try:
            result = await extract_header(document_type, header_text)
        except Exception as exc:  # noqa: BLE001
            code, status = classify_exception(exc)
            model = (
                exc.model if isinstance(exc, AIExtractionError) else None
            ) or settings.groq_model
            # Only the code, the model name and the HTTP status: never a key, the prompt, a request
            # body or the OCR text (an SDK exception message can echo some of those).
            detail = error_detail(exc)
            logger.error(
                f"AI extraction failed: code={code} model={model} status={status} detail={detail}"
            )
            await _update_active_document(
                doc_id,
                {
                    "uploadStatus": "failed",
                    "ocrTextHidden": header_text,
                    "processingError": user_message(code),
                    "processingErrorCode": code,
                },
                run_id,
            )
            return

        update = {
            "uploadStatus": "processed",
            "ocrTextHidden": header_text,
            "processingError": None,
            "processingErrorCode": None,
            "processedAt": datetime.now(UTC),
        }
        update.update(extraction_success_fields(result))
        if await _update_active_document(doc_id, update, run_id):
            await _log_processed(doc_id)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"process_document error: class={type(exc).__name__}")
        await _update_active_document(
            doc_id,
            {
                "uploadStatus": "failed",
                "processingError": user_message(PROCESSING_ERROR),
                "processingErrorCode": PROCESSING_ERROR,
            },
            run_id,
        )
