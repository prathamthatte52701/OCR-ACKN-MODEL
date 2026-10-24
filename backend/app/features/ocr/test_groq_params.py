"""GROQ_REASONING_EFFORT / GROQ_MAX_TOKENS settings and what the provider sends (fake client)."""

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from groq import BadRequestError
from loguru import logger
from pydantic import ValidationError

from app.core.config import Settings
from app.features.ocr.providers import errors, groq_provider
from app.features.ocr.providers.errors import AIExtractionError


@pytest.fixture(autouse=True)
def _required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONGO_URI", "mongodb://localhost:27017")


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str | None) -> Settings:
    for name in ("GROQ_REASONING_EFFORT", "GROQ_MAX_TOKENS"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        if value is not None:
            monkeypatch.setenv(name, value)
    return Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, "high"), ("", None), ("  ", None), ("HIGH", "high"), (" medium ", "medium")],
)
def test_effort_setting(monkeypatch: pytest.MonkeyPatch, raw: str | None, expected: Any) -> None:
    assert _settings(monkeypatch, GROQ_REASONING_EFFORT=raw).groq_reasoning_effort == expected


@pytest.mark.parametrize("bad", ["extreme", "0", "low,high"])
def test_effort_invalid(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    with pytest.raises(ValidationError):
        _settings(monkeypatch, GROQ_REASONING_EFFORT=bad)


@pytest.mark.parametrize(
    ("raw", "expected"), [(None, 2000), ("", 2000), ("1000", 1000), ("50", 50), ("4000", 4000)]
)
def test_max_tokens_setting(
    monkeypatch: pytest.MonkeyPatch, raw: str | None, expected: int
) -> None:
    assert _settings(monkeypatch, GROQ_MAX_TOKENS=raw).groq_max_tokens == expected


@pytest.mark.parametrize("bad", ["49", "4001", "abc", "-5", "1e3", "12.5"])
def test_max_tokens_invalid(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    with pytest.raises(ValidationError):
        _settings(monkeypatch, GROQ_MAX_TOKENS=bad)


def test_blank_vs_unset_from_a_real_env_file(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("GROQ_REASONING_EFFORT", "GROQ_MAX_TOKENS"):
        monkeypatch.delenv(name, raising=False)
    blank = tmp_path / "blank.env"
    blank.write_text("GROQ_REASONING_EFFORT=\nGROQ_MAX_TOKENS=\n")
    unset = tmp_path / "unset.env"
    unset.write_text("GROQ_MODEL=x/y\n")
    b = Settings(_env_file=blank)  # type: ignore[call-arg]
    u = Settings(_env_file=unset)  # type: ignore[call-arg]
    assert (b.groq_reasoning_effort, b.groq_max_tokens) == (None, 2000)
    assert (u.groq_reasoning_effort, u.groq_max_tokens) == ("high", 2000)


def _bad_request() -> BadRequestError:
    req = httpx.Request("POST", "http://x")
    resp = httpx.Response(400, request=req)
    body = {"error": {"code": "invalid_request_error", "message": "unsupported reasoning_effort"}}
    return BadRequestError("bad", response=resp, body=body)


def _fake(
    monkeypatch: pytest.MonkeyPatch, effort: str | None, tokens: int, seen: list[dict]
) -> None:
    monkeypatch.setattr(groq_provider.settings, "groq_api_keys", "k1", raising=False)
    monkeypatch.setattr(groq_provider.settings, "groq_reasoning_effort", effort, raising=False)
    monkeypatch.setattr(groq_provider.settings, "groq_max_tokens", tokens, raising=False)

    def create(**kw: Any) -> Any:
        seen.append(kw)
        if "reasoning_effort" in kw:
            raise _bad_request()
        msg = SimpleNamespace(content="{}")
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    class FakeGroq:
        def __init__(self, **_k: Any) -> None:
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

    monkeypatch.setattr(groq_provider, "Groq", FakeGroq)


@pytest.mark.asyncio
async def test_effort_sent_and_model_rejects_it(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict] = []
    _fake(monkeypatch, "high", 800, seen)
    with pytest.raises(AIExtractionError) as ei:
        await groq_provider.GroqProvider().extract("s", "u")
    assert ei.value.code == errors.UNKNOWN
    assert seen[0]["reasoning_effort"] == "high" and seen[0]["max_tokens"] == 800
    assert len(seen) == 1  # no retry on the parameter error


@pytest.mark.asyncio
async def test_blank_effort_sends_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict] = []
    _fake(monkeypatch, None, 300, seen)
    assert await groq_provider.GroqProvider().extract("s", "u") == "{}"
    assert "reasoning_effort" not in seen[0] and seen[0]["temperature"] == 0.1


def test_startup_line_has_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(groq_provider.settings, "groq_api_keys", "gsk_SECRET1, gsk_SECRET2")
    monkeypatch.setattr(groq_provider.settings, "groq_reasoning_effort", None)
    line = groq_provider.describe_config()
    assert "reasoning_effort=off" in line and "keys=2" in line and "SECRET" not in line
    sink: list[str] = []
    hid = logger.add(sink.append, format="{message}")
    try:
        logger.info(line)
    finally:
        logger.remove(hid)
    assert len(sink) == 1
