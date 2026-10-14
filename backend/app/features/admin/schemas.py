import unicodedata
from typing import Literal

from pydantic import Field, StrictStr, field_validator

from app.core.base_model import CamelModel


class AdminUpdateUserRequest(CamelModel):
    """Pydantic-typed, replacing the previous `body: dict` raw pass-through -
    a non-string username/email in that raw dict (e.g. a JSON object) reached
    normalize_username()/normalize_email()'s .strip() call unchecked and
    crashed with an unhandled 500 instead of a clean validation error. This
    guarantees every field is the right type before it's ever touched."""

    username: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=254)
    role: Literal["user", "admin"] | None = None


MAX_REASON = 300


def clean_reason(raw: str) -> str | None:
    """Plain text only: line breaks/tabs become spaces, every other control character
    (incl. null bytes) is dropped, whitespace is trimmed. Empty -> None; > 300 -> error."""
    spaced = "".join(" " if ch in "\r\n\t" else ch for ch in raw)
    kept = "".join(ch for ch in spaced if unicodedata.category(ch) != "Cc")
    text = " ".join(kept.split())
    if len(text) > MAX_REASON:
        raise ValueError(f"The reason can be at most {MAX_REASON} characters.")
    return text or None


class RejectRequest(CamelModel):
    """Optional body of reject/revoke. StrictStr: a list/number/object is a 422, never coerced."""

    # the raw cap only stops a huge payload being scanned; the real limit is applied after cleaning
    reason: StrictStr | None = Field(default=None, max_length=2000)

    @field_validator("reason")
    @classmethod
    def _clean(cls, value: str | None) -> str | None:
        return clean_reason(value) if value is not None else None


class AdminChangeEmailRequest(CamelModel):
    email: str = Field(max_length=254)


class AdminConfirmedDeleteRequest(CamelModel):
    """Shared confirmation gate for every admin nuke-delete variant: the
    ADMIN's own password entered TWICE (must match) plus a typed
    confirmation phrase unique to the action being confirmed. There is no
    email/OTP channel anywhere in this app (see CLAUDE.md), so this is the
    whole gate - no separate token/one-time-key mechanism."""

    password: str = Field(max_length=128)
    confirm_password: str = Field(max_length=128)
    confirmation_phrase: str = Field(max_length=200)


class AdminAgeRangeRequest(AdminConfirmedDeleteRequest):
    """Oldest-first age-bucket delete. Used both for the per-user admin mode
    (target user comes from the URL path) and the global/all-users admin
    mode (no target - every user) - same body shape either way."""

    older_than_months: Literal[1, 2, 3, 6, 9]


class AdminMonthsRequest(AdminConfirmedDeleteRequest):
    """Precise calendar-range delete: exact year + specific month(s). Used
    both for the per-user admin mode (target user comes from the URL path)
    and the global/all-users admin mode - same body shape either way."""

    # Bounded so year=0 / -5 / 99999 fail validation (422) instead of
    # reaching datetime(year, ...) and 500ing mid-request.
    year: int = Field(ge=2000, le=2100)
    months: list[Literal[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]] = Field(min_length=1)
