import re

from app.core.common_passwords import COMMON_BASE_WORDS

# Ported 1:1 from the old utils/validators.js - source of truth stays here,
# frontend re-implements the same rules for instant feedback only.

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
USERNAME_RE = re.compile(r"^.{3,8}$")
# At least one lowercase, one uppercase, one digit, one special char. Length is
# checked separately (validate_password) because bcrypt only uses the first 72
# BYTES of a password: counting characters alone would let a 64-character
# multi-byte password be silently truncated.
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 64
BCRYPT_MAX_BYTES = 72
PASSWORD_CLASSES_RE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).+$")
_TRAILING_NON_LETTERS_RE = re.compile(r"[^a-z]+$")
_MIN_IDENTITY_LEN = 3


def normalize_email(email: str) -> str:
    return email.strip().lower()


def normalize_username(username: str) -> str:
    return username.strip()


def validate_username(username: str) -> str | None:
    trimmed = normalize_username(username)
    if not trimmed or not USERNAME_RE.match(trimmed):
        return "Username must be 3-8 characters."
    return None


def validate_email(email: str) -> str | None:
    normalized = normalize_email(email)
    # 254 is the RFC 5321 maximum; without a cap a 5000-char "email" was
    # accepted and then stored/rendered in logs and admin tables.
    if len(normalized) > 254 or not EMAIL_RE.match(normalized):
        return "Enter a valid email address."
    return None


def validate_password(
    password: str, username: str | None = None, email: str | None = None
) -> str | None:
    """Rules for NEW passwords (signup, change-password, forgot-password reset).
    Existing passwords are never re-validated, so nobody gets locked out."""
    if (
        not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH
        or len(password.encode("utf-8")) > BCRYPT_MAX_BYTES
        or not PASSWORD_CLASSES_RE.match(password)
    ):
        return (
            "Password must be 8-64 characters and include an uppercase letter, "
            "a lowercase letter, a number, and a special character."
        )
    if re.search(r"\s", password):
        return "Password cannot contain spaces or whitespace."

    lowered = password.lower()
    base = _TRAILING_NON_LETTERS_RE.sub("", lowered)
    if lowered in COMMON_BASE_WORDS or base in COMMON_BASE_WORDS:
        return "That password is too common. Choose something harder to guess."
    identity_parts = {username or "", (email or "").split("@")[0]}
    for part in identity_parts:
        part = part.strip().lower()
        if len(part) >= _MIN_IDENTITY_LEN and part in lowered:
            return "Password cannot contain your username or email name."
    return None
