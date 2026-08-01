from fastapi import HTTPException, Request
from limits import RateLimitItemPerMinute
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.security import decode_token

limiter = Limiter(key_func=get_remote_address)


def user_or_ip_key(request: Request) -> str:
    """Per-account key for endpoints where the risk is a single authenticated
    user hammering their own irreversible-delete action, not a shared IP -
    slowapi's key_func must stay sync, so this decodes the JWT straight off
    the Authorization header (same decode_token used by get_current_user)
    rather than depending on the request's resolved CurrentUser. Falls back
    to IP for the (should-never-happen) case of a missing/invalid token,
    since the route's own auth dependency will 401 it anyway."""
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        payload = decode_token(auth_header[7:])
        if payload and payload.get("userId"):
            return f"user:{payload['userId']}"
    return get_remote_address(request)


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
