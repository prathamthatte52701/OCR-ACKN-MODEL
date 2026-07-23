import asyncio

from groq import Groq

from app.core.config import settings
from app.features.ocr.providers.base import AIProvider

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
        if not self._key_pool:
            raise RuntimeError("GROQ_API_KEYS is not set")

        start_index = self._next_start_index % len(self._key_pool)
        self._next_start_index += 1

        last_error: Exception | None = None
        for i in range(len(self._key_pool)):
            key_index = (start_index + i) % len(self._key_pool)
            client = Groq(api_key=self._key_pool[key_index])
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(self._call, client, system_prompt, user_prompt),
                    timeout=CALL_TIMEOUT_SECONDS,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                status = getattr(exc, "status_code", None)
                should_failover = (
                    status is None
                    or status in _RETRYABLE_STATUSES
                    or (isinstance(status, int) and 500 <= status < 600)
                )
                if not should_failover:
                    raise
        assert last_error is not None
        raise last_error

    @staticmethod
    def _call(client: Groq, system_prompt: str, user_prompt: str) -> str:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=300,
        )
        return response.choices[0].message.content or ""
