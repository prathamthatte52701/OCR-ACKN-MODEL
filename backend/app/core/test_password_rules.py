"""T11: password length (bytes-safe), character classes, identity checks.

There is deliberately NO common-password blocklist (removed on the client's request):
Password1!-style passwords are allowed as long as they meet the format rules."""

import pytest

from app.core.validators import validate_password

GOOD = "Xq7!mZv#4Lp2"


def test_good_password_passes() -> None:
    assert validate_password(GOOD) is None


@pytest.mark.parametrize("pw", ["Ab1!xyz", "Aa1!"])  # 7 and 4 chars
def test_too_short(pw: str) -> None:
    assert validate_password(pw) is not None


def test_length_bounds_8_to_64() -> None:
    ok64 = ("Aa1!" * 16)[:64]
    assert len(ok64) == 64 and validate_password(ok64) is None
    assert validate_password(ok64 + "x") is not None  # 65
    assert validate_password("Aa1!bcde") is None  # exactly 8


def test_multibyte_password_cannot_exceed_bcrypt_72_bytes() -> None:
    # 40 chars (<64) but 2 bytes each for the non-ascii part => > 72 bytes
    pw = "Aa1!" + "é" * 40
    assert len(pw) <= 64 and len(pw.encode()) > 72
    assert validate_password(pw) is not None
    # shorter multibyte password that fits in 72 bytes is fine
    assert validate_password("Aa1!" + "é" * 20) is None


@pytest.mark.parametrize(
    "pw",
    ["Password1!", "Welcome@123", "Admin@12345", "Qwerty!2345", "Passw0rd!", "Secret#2026"],
)
def test_commonly_used_passwords_are_allowed_when_format_is_valid(pw: str) -> None:
    assert validate_password(pw) is None, pw


def test_no_common_password_module_or_message_left() -> None:
    from pathlib import Path

    core = Path(__file__).parent
    assert not (core / "common_passwords.py").exists()
    assert "too common" not in (core / "validators.py").read_text(encoding="utf-8")


def test_password_containing_username_or_email_name_rejected() -> None:
    assert validate_password("Zq9!arjav!Xk77", username="arjav") is not None
    assert validate_password("Zq9!jainxy!Xk77", email="jainxy@example.com") is not None
    # short identities (<3) are ignored to avoid false positives
    assert validate_password(GOOD, username="Xq") is None
    assert validate_password(GOOD, username="other", email="nobody@example.com") is None


def test_whitespace_and_missing_classes_rejected() -> None:
    assert validate_password("Aa1! bcdefg") is not None
    assert validate_password("alllowercase1!") is not None
    assert validate_password("NoSpecial1234") is not None
