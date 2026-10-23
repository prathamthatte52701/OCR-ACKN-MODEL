"""Groq keys are round-robined across ALL documents, not per provider instance."""

import asyncio
from collections import Counter
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from groq import RateLimitError

from app.features.ocr.providers import errors, groq_provider
from app.features.ocr.providers.errors import AIExtractionError


def _rate() -> RateLimitError:
    resp = httpx.Response(429, request=httpx.Request("POST", "http://x"))
    return RateLimitError("rate", response=resp, body=None)


def _install(
    monkeypatch: pytest.MonkeyPatch, keys: list[str], failing: set[str] | None = None
) -> list[str]:
    """Fake Groq client; returns the list that records which key served each call."""
    used: list[str] = []
    monkeypatch.setattr(groq_provider.settings, "groq_api_keys", ",".join(keys), raising=False)
    monkeypatch.setattr(groq_provider.settings, "groq_model", "test/model", raising=False)

    class FakeGroq:
        def __init__(self, api_key: str = "", **_k: Any) -> None:
            def create(**_kw: Any) -> Any:
                if failing and api_key in failing:
                    raise _rate()
                used.append(api_key)
                msg = SimpleNamespace(content="{}")
                return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

    monkeypatch.setattr(groq_provider, "Groq", FakeGroq)
    return used


async def test_new_provider_per_call_still_spreads_evenly(monkeypatch: pytest.MonkeyPatch) -> None:
    used = _install(monkeypatch, ["k1", "k2", "k3"])
    for _ in range(30):
        assert await groq_provider.GroqProvider().extract("s", "u") == "{}"
    assert Counter(used) == {"k1": 10, "k2": 10, "k3": 10}


async def test_concurrent_calls_spread_evenly(monkeypatch: pytest.MonkeyPatch) -> None:
    used = _install(monkeypatch, ["k1", "k2", "k3"])
    await asyncio.gather(*(groq_provider.GroqProvider().extract("s", "u") for _ in range(30)))
    counts = Counter(used)
    assert sum(counts.values()) == 30
    assert all(9 <= counts[k] <= 11 for k in ("k1", "k2", "k3"))


async def test_failover_still_reaches_next_key(monkeypatch: pytest.MonkeyPatch) -> None:
    used = _install(monkeypatch, ["k1", "k2"], failing={"k1"})
    for _ in range(6):
        assert await groq_provider.GroqProvider().extract("s", "u") == "{}"
    assert used == ["k2"] * 6


async def test_single_key_works(monkeypatch: pytest.MonkeyPatch) -> None:
    used = _install(monkeypatch, ["only"])
    for _ in range(3):
        await groq_provider.GroqProvider().extract("s", "u")
    assert used == ["only"] * 3


async def test_empty_pool_raises_no_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, [])
    with pytest.raises(AIExtractionError) as ei:
        await groq_provider.GroqProvider().extract("s", "u")
    assert ei.value.code == errors.NO_KEYS


async def test_pool_shrinks_between_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, ["k1", "k2", "k3", "k4", "k5"])
    for _ in range(7):
        await groq_provider.GroqProvider().extract("s", "u")
    provider = groq_provider.GroqProvider()  # holds the 5-key pool
    used = _install(monkeypatch, ["k1", "k2"])
    provider._key_pool = ["k1", "k2"]
    for _ in range(5):
        await provider.extract("s", "u")
    assert set(used) <= {"k1", "k2"} and len(used) == 5
