from typing import Literal

from pydantic import Field

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


class AdminConfirmedDeleteRequest(CamelModel):
    """Shared confirmation gate for every admin nuke-delete variant: the
    ADMIN's own password entered TWICE (must match) plus a typed
    confirmation phrase unique to the action being confirmed. There is no
    email/OTP channel anywhere in this app (see CLAUDE.md), so this is the
    whole gate - no separate token/one-time-key mechanism."""

    password: str
    confirm_password: str
    confirmation_phrase: str


class AdminAgeRangeRequest(AdminConfirmedDeleteRequest):
    """Oldest-first age-bucket delete. Used both for the per-user admin mode
    (target user comes from the URL path) and the global/all-users admin
    mode (no target - every user) - same body shape either way."""

    older_than_months: Literal[1, 2, 3, 6, 9]


class AdminMonthsRequest(AdminConfirmedDeleteRequest):
    """Precise calendar-range delete: exact year + specific month(s).
    Always global/all-users - there is no per-user version of this mode."""

    year: int
    months: list[Literal[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]] = Field(min_length=1)
