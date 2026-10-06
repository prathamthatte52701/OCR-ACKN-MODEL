from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings

TOKEN_TTL = timedelta(days=7)
ALGORITHM = "HS256"
SALT_ROUNDS = 10


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=SALT_ROUNDS)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    # bcrypt 5 raises ValueError for input over 72 bytes, which surfaced as a
    # 500 on login/change-password/admin-confirm for an existing user (login
    # bodies have no length cap). Signup caps passwords at 32 chars, so a
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
        return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except JWTError:
        return None
