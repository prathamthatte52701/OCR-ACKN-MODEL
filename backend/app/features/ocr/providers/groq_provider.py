import asyncio
import itertools
from typing import Any

from groq import Groq

from app.core.config import settings
from app.features.ocr.providers.base import AIProvider
from app.features.ocr.providers.errors import (
    NO_KEYS,
    AIExtractionError,
    classify_exception,
    combine_failures,
    error_detail,
)

_RETRYABLE_STATUSES = {401, 403, 429}
# No timeout was configured on the underlying HTTP call (true in the old
# app's callGroqWithFailover too) - under a hung/stalled connection this left
# a document stuck in "uploaded" forever with no error ever surfaced,
# observed directly during Phase 7 testing. A per-attempt timeout bounds the
# worst case and, since it's caught as an ordinary exception below, also
# triggers failover to the next key instead of just hanging on a bad one.
CALL_TIMEOUT_SECONDS = 60


# Process-wide rotation counter: a new GroqProvider is built for every document, so a per-instance
# counter always started at key #1. next() on itertools.count is atomic, so concurrent documents
# never get the same number.
_rotation = itertools.count()


def _get_key_pool() -> list[str]:
    raw = settings.groq_api_keys
    return [k.strip() for k in raw.split(",") if k.strip()] if raw else []


class GroqProvider(AIProvider):
    """Multiple keys (GROQ_API_KEYS, comma-separated) are round-robined
    across every call in the process (the counter is module-level, shared by all
    GroqProvider instances) so no single key absorbs the full load - ported from the
    old callGroqWithFailover. Only fails over for capacity/auth/server
    errors; a genuine bad-request error is not retried with a different key."""

    def __init__(self) -> None:
        self._key_pool = _get_key_pool()

    async def extract(self, system_prompt: str, user_prompt: str) -> str:
        model = settings.groq_model
        if not self._key_pool:
            raise AIExtractionError(NO_KEYS, None, model)

        start_index = next(_rotation) % len(self._key_pool)

        failures: list[tuple[str, int | None]] = []
        details: list[str | None] = []
        for i in range(len(self._key_pool)):
            key_index = (start_index + i) % len(self._key_pool)
            client = Groq(api_key=self._key_pool[key_index])
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(self._call, client, system_prompt, user_prompt),
                    timeout=CALL_TIMEOUT_SECONDS,
                )
            except Exception as exc:  # noqa: BLE001
                failures.append(classify_exception(exc))
                details.append(error_detail(exc))
                status = getattr(exc, "status_code", None)
                should_failover = (
                    status is None
                    or status in _RETRYABLE_STATUSES
                    or (isinstance(status, int) and 500 <= status < 600)
                )
                if not should_failover:
                    break
        # The FINAL cause across every key tried, classified - never just the last message.
        code, status = combine_failures(failures)
        detail = next(
            (
                d
                for (c, s), d in zip(failures, details, strict=True)
                if (c, s) == (code, status) and d
            ),
            None,
        )
        raise AIExtractionError(code, status, model, detail)

    @staticmethod
    def _call(client: Groq, system_prompt: str, user_prompt: str) -> str:
        # Model, reasoning effort and max tokens come from settings: Groq has retired a model
        # before, and models without a reasoning mode reject reasoning_effort (blank = not sent).
        kwargs: dict[str, Any] = {
            "model": settings.groq_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": settings.groq_max_tokens,
        }
        if settings.groq_reasoning_effort is not None:
            kwargs["reasoning_effort"] = settings.groq_reasoning_effort
        response = client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""


def describe_config() -> str:
    effort = settings.groq_reasoning_effort or "off"
    return (
        f"Groq config: model={settings.groq_model} reasoning_effort={effort} "
        f"max_tokens={settings.groq_max_tokens} keys={len(_get_key_pool())}"
    )
