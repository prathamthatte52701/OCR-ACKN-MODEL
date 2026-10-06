from app.core.security import hash_password, verify_password


def test_correct_password_still_verifies() -> None:
    assert verify_password("Lg9@12345", hash_password("Lg9@12345"))


def test_wrong_password_is_rejected() -> None:
    assert not verify_password("nope", hash_password("Lg9@12345"))


def test_over_72_byte_password_is_rejected_not_a_crash() -> None:
    h = hash_password("Lg9@12345")
    assert verify_password("A" * 73, h) is False
    assert verify_password("A" * 100000, h) is False
    assert verify_password("é" * 40, h) is False  # 80 bytes, still under the char limit
