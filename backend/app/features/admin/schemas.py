from typing import Literal

from app.core.base_model import CamelModel


class AdminUpdateUserRequest(CamelModel):
    """Pydantic-typed, replacing the previous `body: dict` raw pass-through -
    a non-string username/email in that raw dict (e.g. a JSON object) reached
    normalize_username()/normalize_email()'s .strip() call unchecked and
    crashed with an unhandled 500 instead of a clean validation error. This
    guarantees every field is the right type before it's ever touched."""

    username: str | None = None
    email: str | None = None
    role: Literal["user", "admin"] | None = None
