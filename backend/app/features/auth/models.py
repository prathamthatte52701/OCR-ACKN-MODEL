from typing import Literal

from pydantic import EmailStr, Field

from app.core.base_model import MongoBaseModel


class User(MongoBaseModel):
    username: str = Field(..., min_length=1, max_length=40)
    email: EmailStr
    password_hash: str
    # 'admin' unlocks the admin app - real enforcement is require_admin
    # dependency re-reading this from the DB, never the JWT claim alone.
    role: Literal["user", "admin"] = "user"
    # Bumped to invalidate all previously-issued JWTs (password change,
    # soft-delete) - see get_current_user, which rejects stale values.
    token_version: int = 0


class UserPublic(MongoBaseModel):
    """Shape returned to clients - never includes password_hash."""

    username: str
    email: EmailStr
    role: Literal["user", "admin"]
