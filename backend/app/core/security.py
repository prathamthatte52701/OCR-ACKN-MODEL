import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import settings

TOKEN_TTL = timedelta(days=7)
ALGORITHM = "HS256"
SALT_ROUNDS = 10


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=SALT_ROUNDS)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


# A real bcrypt hash of a random throwaway value, computed once at import. Login
# verifies against it when the email is unknown (or the account has no password,
# e.g. Google-created), so "no such account" costs the same bcrypt time as "wrong
# password" and response time cannot be used to find registered emails.
DUMMY_PASSWORD_HASH = bcrypt.hashpw(
    secrets.token_bytes(24), bcrypt.gensalt(rounds=SALT_ROUNDS)
).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    # bcrypt 5 raises ValueError for input over 72 bytes, which surfaced as a
    # 500 on login/change-password/admin-confirm for an existing user (login
    # bodies have no length cap). New passwords are capped (64 chars, 72 bytes), so a
    # longer value can never match a stored hash - answer "no" instead of
    # crashing, and never hand an attacker-sized buffer to bcrypt.
    raw = password.encode("utf-8")
    if len(raw) > 72:
        return False
    try:
        return bcrypt.checkpw(raw, password_hash.encode("utf-8"))
    except ValueError:
        return False


def sign_token(user_id: str, token_version: int, role: str) -> str:
    payload = {
        "userId": user_id,
        "tokenVersion": token_version,
        "role": role,
        "exp": datetime.now(UTC) + TOKEN_TTL,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        # algorithms pinned to HS256 only (no "none", no RS/ES confusion) and exp is
        # mandatory, so a token without an expiry is rejected rather than eternal.
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[ALGORITHM],
            options={"require": ["exp"]},
        )
    except jwt.PyJWTError:
        return None
