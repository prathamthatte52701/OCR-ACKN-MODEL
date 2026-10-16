import asyncio

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


def _get_key_pool() -> list[str]:
    raw = settings.groq_api_keys
    return [k.strip() for k in raw.split(",") if k.strip()] if raw else []


class GroqProvider(AIProvider):
    """Multiple keys (GROQ_API_KEYS, comma-separated) are round-robined
    across calls so no single key absorbs the full load - ported from the
    old callGroqWithFailover. Only fails over for capacity/auth/server
    errors; a genuine bad-request error is not retried with a different key."""

    def __init__(self) -> None:
        self._key_pool = _get_key_pool()
        self._next_start_index = 0

    async def extract(self, system_prompt: str, user_prompt: str) -> str:
        model = settings.groq_model
        if not self._key_pool:
            raise AIExtractionError(NO_KEYS, None, model)

        start_index = self._next_start_index % len(self._key_pool)
        self._next_start_index += 1

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
        response = client.chat.completions.create(
            # The model comes from GROQ_MODEL (default openai/gpt-oss-120b): Groq has retired a
            # model before (404 model_not_found) and every extraction failed. "low" reasoning
            # effort keeps latency down and leaves the 300-token budget for the JSON answer.
            model=settings.groq_model,
            reasoning_effort="low",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=300,
        )
        return response.choices[0].message.content or ""
