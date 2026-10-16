"""AI failure classification: provider failover, extract_header retry, pipeline status, logging."""

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from bson import ObjectId
from groq import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    InternalServerError,
    NotFoundError,
    RateLimitError,
)
from loguru import logger
from pydantic import ValidationError

from app.core.config import Settings
from app.features.ocr import pipeline
from app.features.ocr.ai_extraction import extract_header
from app.features.ocr.providers import errors, groq_provider
from app.features.ocr.providers.base import AIProvider
from app.features.ocr.providers.errors import AIExtractionError

KEY = "gsk_SECRETKEY123"
MARKER = "OCR-MARKER-XYZ"
SET_UP = "The AI service is not set up correctly. Please contact the administrator."
BUSY = "The AI service is busy right now. Please try again in a few minutes."
OLD_TEXT = "AI analysis is unavailable. Please check the Groq API key"


def _req() -> httpx.Request:
    return httpx.Request("POST", "https://x")


def _status_exc(cls: Any, status: int, body: dict | None = None) -> Exception:
    res = httpx.Response(status, request=_req(), json=body or {})
    exc: Exception = cls("err", response=res, body=body)
    return exc


def rate() -> Exception:
    return _status_exc(RateLimitError, 429)


def auth() -> Exception:
    return _status_exc(AuthenticationError, 401)


def gone() -> Exception:
    return _status_exc(NotFoundError, 404, {"error": {"code": "model_not_found"}})


# ---------------- classifier ----------------


def test_classify_and_messages() -> None:
    assert errors.classify_exception(rate()) == (errors.RATE_LIMIT, 429)
    assert errors.classify_exception(auth()) == (errors.AUTH, 401)
    assert errors.classify_exception(gone()) == (errors.MODEL_GONE, 404)
    assert errors.classify_exception(APITimeoutError(_req()))[0] == errors.TIMEOUT_NETWORK
    conn = APIConnectionError(request=_req())
    assert errors.classify_exception(conn)[0] == errors.TIMEOUT_NETWORK
    assert errors.classify_exception(RuntimeError("x")) == (errors.UNKNOWN, None)
    mixed: list[tuple[str, int | None]] = [(errors.RATE_LIMIT, 429), (errors.MODEL_GONE, 404)]
    assert errors.combine_failures(mixed) == (errors.MODEL_GONE, 404)
    assert errors.user_message(errors.NO_KEYS) == SET_UP
    assert errors.user_message("nonsense") == errors.user_message(errors.UNKNOWN)


# ---------------- settings ----------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, "openai/gpt-oss-120b"), ("   ", "openai/gpt-oss-120b"), ("  my/model ", "my/model")],
)
def test_groq_model_setting(
    monkeypatch: pytest.MonkeyPatch, raw: str | None, expected: str
) -> None:
    if raw is None:
        monkeypatch.delenv("GROQ_MODEL", raising=False)
    else:
        monkeypatch.setenv("GROQ_MODEL", raw)
    assert Settings().groq_model == expected  # type: ignore[call-arg]


@pytest.mark.parametrize("bad", ["a b", "x" * 101])
def test_groq_model_invalid(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    monkeypatch.setenv("GROQ_MODEL", bad)
    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


# ---------------- provider ----------------


def _fake_groq(monkeypatch: pytest.MonkeyPatch, keys: list[str], behaviours: list[Any]) -> None:
    """behaviours[i] is an exception to raise or a str to return, for key i."""
    monkeypatch.setattr(groq_provider.settings, "groq_api_keys", ",".join(keys), raising=False)
    monkeypatch.setattr(groq_provider.settings, "groq_model", "test/model", raising=False)

    class FakeGroq:
        def __init__(self, api_key: str = "", **_k: Any) -> None:
            idx = keys.index(api_key)

            def create(**_kw: Any) -> Any:
                b = behaviours[idx]
                if isinstance(b, Exception):
                    raise b
                msg = SimpleNamespace(content=b)
                return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

    monkeypatch.setattr(groq_provider, "Groq", FakeGroq)


async def _run_provider() -> AIExtractionError:
    with pytest.raises(AIExtractionError) as ei:
        await groq_provider.GroqProvider().extract("s", "u")
    return ei.value


async def test_provider_model_gone_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_groq(monkeypatch, ["k1", "k2"], [rate(), gone()])
    err = await _run_provider()
    assert err.code == errors.MODEL_GONE
    assert err.model == "test/model"


async def test_provider_all_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_groq(monkeypatch, ["k1", "k2"], [rate(), rate()])
    assert (await _run_provider()).code == errors.RATE_LIMIT


async def test_provider_all_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_groq(monkeypatch, ["k1", "k2"], [auth(), auth()])
    assert (await _run_provider()).code == errors.AUTH


async def test_provider_no_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_groq(monkeypatch, [], [])
    assert (await _run_provider()).code == errors.NO_KEYS


async def test_provider_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_groq(monkeypatch, ["k1"], [APITimeoutError(_req())])
    assert (await _run_provider()).code == errors.TIMEOUT_NETWORK


async def test_provider_failover_to_good_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_groq(monkeypatch, ["k1", "k2"], [_status_exc(InternalServerError, 500), "{}"])
    assert await groq_provider.GroqProvider().extract("s", "u") == "{}"


# ---------------- extract_header ----------------


class SeqProvider(AIProvider):
    def __init__(self, replies: list[Any]) -> None:
        self.replies = replies
        self.calls = 0

    async def extract(self, system_prompt: str, user_prompt: str) -> str:
        r = self.replies[self.calls]
        self.calls += 1
        if isinstance(r, Exception):
            raise r
        return str(r)


GOOD = json.dumps({"number": "820000001", "date": "01/01/2026"})


@pytest.mark.parametrize("bad", ["[1,2]", '"text"', "null", "42"])
async def test_non_dict_reply_retries_once_then_bad_reply(bad: str) -> None:
    p = SeqProvider([bad, bad, GOOD])
    with pytest.raises(AIExtractionError) as ei:
        await extract_header("Delivery Challan", "hdr", provider=p)
    assert ei.value.code == errors.BAD_REPLY
    assert p.calls == 2


async def test_bad_then_good_succeeds() -> None:
    p = SeqProvider(["[1]", GOOD])
    result = await extract_header("Delivery Challan", "hdr", provider=p)
    assert isinstance(result, dict)
    assert p.calls == 2


async def test_provider_error_propagates_unchanged() -> None:
    boom = AIExtractionError(errors.RATE_LIMIT, 429, "m")
    with pytest.raises(AIExtractionError) as ei:
        await extract_header("Delivery Challan", "hdr", provider=SeqProvider([boom]))
    assert ei.value is boom


# ---------------- pipeline + logging ----------------


async def _ok(*_a: Any, **_k: Any) -> None:
    return None


async def _run_pipeline(
    db: Any, monkeypatch: pytest.MonkeyPatch, extract: Any, **row: Any
) -> tuple[dict, list[str]]:
    res = await db.documents.insert_one(
        {
            "userId": ObjectId(),
            "uploadStatus": "uploaded",
            "documentType": "Delivery Challan",
            "isDeleted": False,
            **row,
        }
    )

    async def fake_text(*_a: Any, **_k: Any) -> str:
        return MARKER

    monkeypatch.setattr(pipeline, "_extract_header_text", fake_text)
    monkeypatch.setattr(pipeline, "extract_header", extract)
    monkeypatch.setattr(pipeline, "check_upload", _ok, raising=False)
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(str(m)), format="{message}", level="DEBUG")
    try:
        await pipeline.process_document(
            res.inserted_id, b"%PDF-1.4 x", "application/pdf", "Delivery Challan"
        )
    finally:
        logger.remove(sink)
    doc = await db.documents.find_one({"_id": res.inserted_id})
    return doc, lines


def _raiser(exc: Exception) -> Any:
    async def _raise(*_a: Any, **_k: Any) -> dict:
        raise exc

    return _raise


@pytest.mark.parametrize(
    ("exc", "code", "message"),
    [
        (AIExtractionError(errors.NO_KEYS), "NO_KEYS", SET_UP),
        (AIExtractionError(errors.AUTH, 401, "m"), "AUTH", SET_UP),
        (AIExtractionError(errors.MODEL_GONE, 404, "m"), "MODEL_GONE", SET_UP),
        (AIExtractionError(errors.RATE_LIMIT, 429, "m"), "RATE_LIMIT", BUSY),
        (
            AIExtractionError(errors.TIMEOUT_NETWORK),
            "TIMEOUT_NETWORK",
            "Could not reach the AI service. Check the internet connection and try again.",
        ),
        (
            AIExtractionError(errors.BAD_REPLY),
            "BAD_REPLY",
            "The AI gave an unreadable answer. Please try again.",
        ),
        (
            RuntimeError(f"{KEY} {MARKER}"),
            "UNKNOWN",
            "Something went wrong while reading this document. Please try again.",
        ),
        (rate(), "RATE_LIMIT", BUSY),
    ],
)
async def test_pipeline_failure_state_and_log(
    db: Any, monkeypatch: pytest.MonkeyPatch, exc: Exception, code: str, message: str
) -> None:
    doc, lines = await _run_pipeline(db, monkeypatch, _raiser(exc))
    assert doc["uploadStatus"] == "failed"
    assert doc["ocrTextHidden"] == MARKER
    assert doc["processingError"] == message
    assert doc["processingErrorCode"] == code
    assert OLD_TEXT not in doc["processingError"]
    hits = [ln for ln in lines if f"code={code}" in ln]
    assert len(hits) == 1
    assert "model=" in hits[0] and "status=" in hits[0]
    joined = "\n".join(lines)
    assert KEY not in joined and MARKER not in joined


async def test_pipeline_log_has_model_and_status(db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    exc = AIExtractionError(errors.RATE_LIMIT, 429, "m/x")
    _, lines = await _run_pipeline(db, monkeypatch, _raiser(exc))
    line = next(ln for ln in lines if "code=RATE_LIMIT" in ln)
    assert "model=m/x" in line and "status=429" in line


async def test_pipeline_success_clears_code(db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_extract(*_a: Any, **_k: Any) -> dict:
        return {"number": "820000001", "date": "01/01/2026"}

    doc, _ = await _run_pipeline(db, monkeypatch, fake_extract, processingErrorCode="RATE_LIMIT")
    assert doc["processingErrorCode"] is None


async def test_deeply_nested_json_reply_is_a_bad_reply_not_unknown() -> None:
    from app.features.ocr.ai_extraction import extract_header
    from app.features.ocr.providers.base import AIProvider
    from app.features.ocr.providers.errors import BAD_REPLY, AIExtractionError

    class Nested(AIProvider):
        calls = 0

        async def extract(self, system_prompt: str, user_prompt: str) -> str:
            Nested.calls += 1
            return "[" * 10000

    with pytest.raises(AIExtractionError) as info:
        await extract_header("Delivery Challan", "hdr", provider=Nested())
    assert info.value.code == BAD_REPLY and Nested.calls == 2


def test_error_detail_is_only_a_safe_token() -> None:
    import groq
    import httpx

    from app.features.ocr.providers.errors import error_detail

    req = httpx.Request("POST", "https://x")

    def err(body: object) -> Exception:
        return groq.BadRequestError(
            "m", response=httpx.Response(400, request=req, json={}), body=body
        )

    assert (
        error_detail(err({"error": {"code": "invalid_request_error", "message": "secret"}}))
        == "invalid_request_error"
    )
    assert error_detail(err({"error": {"code": "has spaces and gsk_KEY"}})) is None
    assert error_detail(err("not a dict")) is None
