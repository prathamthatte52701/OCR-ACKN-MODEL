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
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


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
