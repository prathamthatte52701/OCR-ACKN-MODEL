import asyncio
import os
import tempfile
from datetime import UTC, datetime

from bson import ObjectId
from loguru import logger

from app.core.database import get_database
from app.features.ocr.ai_extraction import extract_header
from app.features.ocr.paddle_runner import (
    OCR_TIMEOUT_SECONDS_IMAGE,
    OCR_TIMEOUT_SECONDS_PDF,
    run_ocr,
)
from app.features.ocr.preprocessing import crop_header, get_pdf_header_text_or_image

_ocr_lock = asyncio.Lock()  # only 1 OCR job runs at a time - mirrors old app's single-slot queue


async def _extract_header_text(buffer: bytes, mime_type: str) -> str | None:
    """Returns the header-region OCR/text-layer text, or None on failure -
    mirrors the old app's extractHeaderText()."""
    try:
        if mime_type == "application/pdf":
            text, header_png = await get_pdf_header_text_or_image(buffer)
            if text:
                return text
            if header_png is None:
                return None
            image_bytes = header_png
        else:
            image_bytes = crop_header(buffer)

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
            async with _ocr_lock:
                try:
                    text = await asyncio.wait_for(
                        asyncio.to_thread(run_ocr, tmp_path), timeout=timeout
                    )
                except TimeoutError:
                    text = None
            return text
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Header OCR error: {exc}")
        return None


async def _update_active_document(doc_id: ObjectId, update: dict) -> None:
    db = get_database()
    update["updatedAt"] = datetime.now(UTC)
    await db.documents.update_one({"_id": doc_id, "isDeleted": {"$ne": True}}, {"$set": update})


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
            "taxInvoiceNoConfidence",
            "referenceNoConfidence",
            "numberConfidence",
            "dateConfidence",
            "taxInvoiceNoAutoCorrected",
            "numberAutoCorrected",
            "dateAutoCorrected",
        ):
            if key in result:
                update[key] = result[key]
        await _update_active_document(doc_id, update)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"process_document error: {exc}")
        await _update_active_document(
            doc_id,
            {
                "uploadStatus": "failed",
                "processingError": "Something went wrong while processing this document.",
            },
        )
