"""A Groq answer cut off by the token limit (finish_reason "length"): one retry, double limit."""

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from groq import RateLimitError
from loguru import logger

from app.features.ocr.providers import errors, groq_provider
from app.features.ocr.providers.errors import AIExtractionError

CUT_MESSAGE = (
    "The AI answer was cut off. Press Reprocess. If it keeps happening, ask the admin to raise "
    "GROQ_MAX_TOKENS."
)
REPLY_TEXT = "SECRET-REPLY-TEXT-123"


def _fake(
    monkeypatch: pytest.MonkeyPatch,
    keys: list[str],
    replies: dict[str, list[Any]],
    tokens: int,
    seen: list[tuple[str, dict]],
) -> None:
    """replies[key] = per-call list of (content, finish_reason) or an exception to raise."""
    monkeypatch.setattr(groq_provider.settings, "groq_api_keys", ",".join(keys), raising=False)
    monkeypatch.setattr(groq_provider.settings, "groq_model", "test/model", raising=False)
    monkeypatch.setattr(groq_provider.settings, "groq_max_tokens", tokens, raising=False)
    monkeypatch.setattr(groq_provider.settings, "groq_reasoning_effort", None, raising=False)

    class FakeGroq:
        def __init__(self, api_key: str = "", **_k: Any) -> None:
            def create(**kw: Any) -> Any:
                seen.append((api_key, kw))
                item = replies[api_key].pop(0)
                if isinstance(item, Exception):
                    raise item
                content, reason = item
                msg = SimpleNamespace(content=content)
                return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=reason)])

            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

    monkeypatch.setattr(groq_provider, "Groq", FakeGroq)


@pytest.fixture
def sink() -> Any:
    lines: list[str] = []
    hid = logger.add(lines.append, format="{message}")
    yield lines
    logger.remove(hid)


async def test_cut_off_retries_once_with_doubled_limit_same_key(
    monkeypatch: pytest.MonkeyPatch, sink: list[str]
) -> None:
    seen: list[tuple[str, dict]] = []
    _fake(monkeypatch, ["k1", "k2"], {"k1": [(REPLY_TEXT, "length"), ("{}", "stop")]}, 1000, seen)
    # rotation is process-wide: pin it so key k1 is tried first
    monkeypatch.setattr(groq_provider, "_rotation", iter([0]))
    assert await groq_provider.GroqProvider().extract("s", "u") == "{}"
    assert [k for k, _ in seen] == ["k1", "k1"]
    assert [kw["max_tokens"] for _, kw in seen] == [1000, 2000]
    log = "\n".join(sink)
    assert "length" in log and "1000" in log and "test/model" in log
    assert REPLY_TEXT not in log


async def test_doubling_is_capped_at_4000(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, dict]] = []
    _fake(monkeypatch, ["k1"], {"k1": [("x", "length"), ("{}", "stop")]}, 3000, seen)
    assert await groq_provider.GroqProvider().extract("s", "u") == "{}"
    assert [kw["max_tokens"] for _, kw in seen] == [3000, 4000]


async def test_cut_off_at_4000_does_not_retry(
    monkeypatch: pytest.MonkeyPatch, sink: list[str]
) -> None:
    seen: list[tuple[str, dict]] = []
    _fake(monkeypatch, ["k1", "k2"], {"k1": [(REPLY_TEXT, "length")]}, 4000, seen)
    monkeypatch.setattr(groq_provider, "_rotation", iter([0]))
    with pytest.raises(AIExtractionError) as ei:
        await groq_provider.GroqProvider().extract("s", "u")
    assert ei.value.code == errors.REPLY_CUT_OFF
    assert len(seen) == 1  # no retry, and no failover to another key
    assert REPLY_TEXT not in "\n".join(sink)


async def test_cut_off_twice_gives_new_code_and_message(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, dict]] = []
    _fake(monkeypatch, ["k1"], {"k1": [("a", "length"), ("b", "length")]}, 1000, seen)
    with pytest.raises(AIExtractionError) as ei:
        await groq_provider.GroqProvider().extract("s", "u")
    assert ei.value.code == errors.REPLY_CUT_OFF == "REPLY_CUT_OFF"
    assert ei.value.model == "test/model"
    assert len(seen) == 2  # exactly one retry
    assert errors.user_message(errors.REPLY_CUT_OFF) == CUT_MESSAGE
    assert errors.REPLY_CUT_OFF in errors.CODES
    assert errors.classify_exception(ei.value)[0] == errors.REPLY_CUT_OFF


async def test_normal_reply_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, dict]] = []
    _fake(monkeypatch, ["k1"], {"k1": [("{}", "stop")]}, 2000, seen)
    assert await groq_provider.GroqProvider().extract("s", "u") == "{}"
    assert len(seen) == 1 and seen[0][1]["max_tokens"] == 2000


async def test_missing_finish_reason_is_a_normal_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(groq_provider.settings, "groq_api_keys", "k1", raising=False)
    calls: list[int] = []

    def create(**_kw: Any) -> Any:
        calls.append(1)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))])

    class FakeGroq:
        def __init__(self, **_k: Any) -> None:
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

    monkeypatch.setattr(groq_provider, "Groq", FakeGroq)
    assert await groq_provider.GroqProvider().extract("s", "u") == "{}"
    assert len(calls) == 1


async def test_rate_limit_still_fails_over_to_next_key(monkeypatch: pytest.MonkeyPatch) -> None:
    res = httpx.Response(429, request=httpx.Request("POST", "https://x"), json={})
    seen: list[tuple[str, dict]] = []
    replies: dict[str, list[Any]] = {
        "k1": [RateLimitError("e", response=res, body=None)],
        "k2": [("{}", "stop")],
    }
    _fake(monkeypatch, ["k1", "k2"], replies, 2000, seen)
    monkeypatch.setattr(groq_provider, "_rotation", iter([0]))
    assert await groq_provider.GroqProvider().extract("s", "u") == "{}"
    assert [k for k, _ in seen] == ["k1", "k2"]


def test_cut_off_code_is_not_a_key_failure_cause() -> None:
    # combine_failures: a model that is gone still wins; otherwise the last failure is reported
    assert errors.combine_failures([(errors.REPLY_CUT_OFF, None), (errors.MODEL_GONE, 404)]) == (
        errors.MODEL_GONE,
        404,
    )
