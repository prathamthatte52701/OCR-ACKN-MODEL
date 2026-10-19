"""Why did AI extraction fail? A small closed set of codes instead of a catch-all "check the key".

Public names (used by groq_provider.py, ai_extraction.py, pipeline.py):
  CODES                         - the twelve code strings below
  AIExtractionError(code, status=None, model=None)
  classify_exception(exc)       -> (code, status)   for any exception the SDK/asyncio can raise
  combine_failures(failures)    -> (code, status)   final cause after failing over across keys
  user_message(code)            -> plain text for the document's owner (never names a key or model)

Only the code, the HTTP status and the model name are ever logged - never keys, request bodies,
prompts or OCR text."""

import asyncio
import re

NO_KEYS = "NO_KEYS"
AUTH = "AUTH"
RATE_LIMIT = "RATE_LIMIT"
MODEL_GONE = "MODEL_GONE"
TIMEOUT_NETWORK = "TIMEOUT_NETWORK"
BAD_REPLY = "BAD_REPLY"
UNKNOWN = "UNKNOWN"
# Not an AI failure: the OCR slot is held by a timed-out OCR thread that never ended (pipeline.py)
OCR_STUCK = "OCR_STUCK"
# Also not AI failures: why the text reader (OCR) could not give text (pipeline.py)
OCR_ENGINE_ERROR = "OCR_ENGINE_ERROR"  # the engine itself failed (model, memory, crash)
OCR_TIMEOUT = "OCR_TIMEOUT"  # the engine took longer than its time limit
NO_TEXT = "NO_TEXT"  # the engine ran fine but found no text (blank or unreadable paper)
# The catch-all of process_document: something unexpected failed after the upload
PROCESSING_ERROR = "PROCESSING_ERROR"
CODES = (
    NO_KEYS,
    AUTH,
    RATE_LIMIT,
    MODEL_GONE,
    TIMEOUT_NETWORK,
    BAD_REPLY,
    UNKNOWN,
    OCR_STUCK,
    OCR_ENGINE_ERROR,
    OCR_TIMEOUT,
    NO_TEXT,
    PROCESSING_ERROR,
)

_USER_MESSAGES = {
    NO_KEYS: "The AI service is not set up correctly. Please contact the administrator.",
    AUTH: "The AI service is not set up correctly. Please contact the administrator.",
    MODEL_GONE: "The AI service is not set up correctly. Please contact the administrator.",
    RATE_LIMIT: "The AI service is busy right now. Please try again in a few minutes.",
    TIMEOUT_NETWORK: (
        "Could not reach the AI service. Check the internet connection and try again."
    ),
    BAD_REPLY: "The AI gave an unreadable answer. Please try again.",
    UNKNOWN: "Something went wrong while reading this document. Please try again.",
    OCR_STUCK: (
        "The text reader is stuck. Please tell the administrator to restart the app, "
        "then press Reprocess."
    ),
    OCR_ENGINE_ERROR: "The text reader failed. Please tell the administrator.",
    OCR_TIMEOUT: (
        "Reading this document took too long. Please try again, or upload a smaller or "
        "clearer file."
    ),
    NO_TEXT: (
        "We could not read any text from this document. Try a clearer photo or scan, or a "
        "higher-quality PDF."
    ),
    PROCESSING_ERROR: "Something went wrong while processing this document.",
}

_MODEL_GONE_BODY_CODES = {"model_not_found", "model_decommissioned", "model_not_active"}


class AIExtractionError(Exception):
    """The final, classified cause of a failed AI extraction. The message is only the code."""

    def __init__(
        self,
        code: str,
        status: int | None = None,
        model: str | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code if code in CODES else UNKNOWN
        self.status = status
        self.model = model
        self.detail = detail  # Groq's own short error code (e.g. invalid_request_error), log only


def user_message(code: str) -> str:
    return _USER_MESSAGES.get(code, _USER_MESSAGES[UNKNOWN])


def _body_code(exc: BaseException) -> str:
    """The error code Groq puts in the response body ({"error": {"code": ...}}), lower-cased."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        inner = body.get("error", body)
        if isinstance(inner, dict):
            value = inner.get("code")
            if isinstance(value, str):
                return value.lower()
    return ""


_SAFE_TOKEN_RE = re.compile(r"[A-Za-z0-9_.-]{1,60}")


def error_detail(exc: BaseException) -> str | None:
    """Groq's own short error code from the response body, only if it is a plain token. Safe to
    log (never the message text, which can echo request details)."""
    if isinstance(exc, AIExtractionError):
        return exc.detail
    value = _body_code(exc)
    return value if _SAFE_TOKEN_RE.fullmatch(value or "") else None


def classify_exception(exc: BaseException) -> tuple[str, int | None]:
    """(code, http status or None) for any exception. Never raises."""
    if isinstance(exc, AIExtractionError):
        return exc.code, exc.status
    status = getattr(exc, "status_code", None)
    status = status if isinstance(status, int) else None
    if status == 404 or _body_code(exc) in _MODEL_GONE_BODY_CODES:
        return MODEL_GONE, status
    if status in (401, 403):
        return AUTH, status
    if status == 429:
        return RATE_LIMIT, status
    if status is None:
        if isinstance(exc, (asyncio.TimeoutError, TimeoutError, ConnectionError, OSError)):
            return TIMEOUT_NETWORK, None
        # groq.APITimeoutError / APIConnectionError carry no status code
        name = type(exc).__name__
        if name in ("APITimeoutError", "APIConnectionError", "ReadTimeout", "ConnectError"):
            return TIMEOUT_NETWORK, None
        if isinstance(exc, (ValueError, RecursionError, TypeError)):
            return BAD_REPLY, None
        return UNKNOWN, None
    return UNKNOWN, status


def combine_failures(failures: list[tuple[str, int | None]]) -> tuple[str, int | None]:
    """The one cause to report after trying every key. A model that no longer exists is the most
    specific (and the same for every key), so it wins; otherwise the cause shared by every key
    (all 429 -> RATE_LIMIT, all 401 -> AUTH); a mix reports the last failure."""
    if not failures:
        return UNKNOWN, None
    for code, status in failures:
        if code == MODEL_GONE:
            return code, status
    return failures[-1]
