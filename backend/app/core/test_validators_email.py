from app.core.validators import validate_email


def test_normal_email_ok() -> None:
    assert validate_email("a.b+c@example.co.in") is None


def test_overlong_email_rejected() -> None:
    assert validate_email("a" * 250 + "@x.com") is not None
    assert validate_email("a" * 5000 + "@x.com") is not None


def test_254_char_email_still_allowed() -> None:
    email = "a" * 241 + "@example.com"  # 241 + 12 = 253
    assert len(email) <= 254 and validate_email(email) is None
