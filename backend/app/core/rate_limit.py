from fastapi import HTTPException, Request
from limits import RateLimitItemPerMinute
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

# Per-EMAIL login limiter, kept separate from slowapi's per-IP limiter (see
# router.py) - the real brute-force guard, keyed on the account actually
# being attacked so an office/shared-WiFi IP doesn't get punished for one
# person's mistyped password. slowapi's key_func must be sync, and reading
# the request body to extract the email requires an await, so this one is
# implemented directly with the same `limits` library slowapi uses underneath.
_email_storage = MemoryStorage()
_email_limiter = MovingWindowRateLimiter(_email_storage)
_email_login_limit = RateLimitItemPerMinute(20, 15)


async def enforce_login_email_limit(request: Request, email: str) -> None:
    key = email.strip().lower() if email and email.strip() else get_remote_address(request)
    if not _email_limiter.hit(_email_login_limit, key):
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts for this account. Please try again in a few minutes.",
        )
