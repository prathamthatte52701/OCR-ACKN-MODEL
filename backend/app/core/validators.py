import re

# Ported 1:1 from the old utils/validators.js - source of truth stays here,
# frontend re-implements the same rules for instant feedback only.

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
USERNAME_RE = re.compile(r"^.{3,8}$")
# 8-32 chars, at least one lowercase, one uppercase, one digit, one special char.
PASSWORD_RE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{8,32}$")


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
    if not EMAIL_RE.match(normalize_email(email)):
        return "Enter a valid email address."
    return None


def validate_password(password: str) -> str | None:
    if not PASSWORD_RE.match(password):
        return (
            "Password must be 8-32 characters and include an uppercase letter, "
            "a lowercase letter, a number, and a special character."
        )
    if re.search(r"\s", password):
        return "Password cannot contain spaces or whitespace."
    return None
