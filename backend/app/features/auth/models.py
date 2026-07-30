from typing import Literal

from pydantic import EmailStr, Field

from app.core.base_model import MongoBaseModel


class User(MongoBaseModel):
    username: str = Field(..., min_length=1, max_length=40)
    email: EmailStr
    # Absent entirely (no key at all, not "") for Google-only accounts -
    # that absence is the signal used to gate password-based flows
    # (forgot-password, change-password) away from Google-only users.
    password_hash: str | None = None
    # 'admin' unlocks the admin app - real enforcement is require_admin
    # dependency re-reading this from the DB, never the JWT claim alone.
    role: Literal["user", "admin"] = "user"
    # Bumped to invalidate all previously-issued JWTs (password change,
    # soft-delete) - see get_current_user, which rejects stale values.
    token_version: int = 0
    # "local" (default/missing), "google", or "local+google" (a local
    # account that later linked a Google sign-in) - see auth/router.py's
    # POST /google for the linking logic.
    auth_provider: Literal["local", "google", "local+google"] = "local"
    google_id: str | None = None


class UserPublic(MongoBaseModel):
    """Shape returned to clients - never includes password_hash."""

    username: str
    email: EmailStr
    role: Literal["user", "admin"]
