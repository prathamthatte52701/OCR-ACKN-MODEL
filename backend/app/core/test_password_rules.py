"""T11: password length (bytes-safe), blocklist, identity checks."""

import pytest

from app.core.common_passwords import COMMON_BASE_WORDS
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
    [
        "Password1!",
        "PAsSWORD123#",
        "pAssword@2026",
        "Welcome@123",
        "Admin@12345",
        "Qwerty!2345",
        "Iloveyou#99",
        "Letmein!!11",
        "Passw0rd!",
        "Secret#2026",
    ],
)
def test_blocklist_variants_rejected(pw: str) -> None:
    err = validate_password(pw)
    assert err is not None and "too common" in err, pw


def test_blocklist_does_not_reject_strong_passwords_containing_a_word() -> None:
    assert validate_password("Xq7!welcomeZv#4") is None  # not equal to a base word


def test_blocklist_has_about_200_plus_entries() -> None:
    assert 200 <= len(COMMON_BASE_WORDS) <= 400


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
