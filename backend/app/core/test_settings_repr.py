"""Secrets must never show up when a Settings object is printed, logged or put in an f-string."""

import json
import logging
import re

from app.core.config import Settings

FAKE = {
    "MONGO_URI": "mongodb+srv://fakeuser:fake-db-password-9f2@cluster.fake.invalid/db",
    "JWT_SECRET": "fake-jwt-secret-0123456789-abcdefghijklmnopqrstuvwxyz",
    "GROQ_API_KEYS": "gsk_fakekeyone111,gsk_fakekeytwo222",
    "ADMIN_1_PASSWORD": "fake-admin-one-pass-AAA111!",
    "ADMIN_2_PASSWORD": "fake-admin-two-pass-BBB222!",
}
SECRET_PARTS = [
    "fake-db-password-9f2",
    "fakeuser",
    "fake-jwt-secret",
    "gsk_fakekeyone111",
    "gsk_fakekeytwo222",
    "fake-admin-one-pass",
    "fake-admin-two-pass",
]


def _settings() -> Settings:
    return Settings(_env_file=None, **FAKE)  # type: ignore[call-arg,arg-type]


def test_repr_str_and_fstring_hide_every_secret() -> None:
    s = _settings()
    for text in (repr(s), str(s), f"{s}", f"{s!r}", "%s %r" % (s, s)):  # noqa: UP031
        for part in SECRET_PARTS:
            assert part not in text, f"{part} leaked"
    # non-secrets stay visible, so the repr is still useful for debugging
    assert "mongo_db_name=" in repr(s) and "enable_docs=" in repr(s)


def test_logging_the_object_or_its_fields_dict_does_not_leak(caplog) -> None:  # type: ignore[no-untyped-def]
    s = _settings()
    with caplog.at_level(logging.DEBUG):
        logging.getLogger("t").info("settings=%s", s)
        logging.getLogger("t").info("settings=%r", s)
    assert not any(p in caplog.text for p in SECRET_PARTS)


def test_values_are_still_plain_strings_and_dump_is_unchanged() -> None:
    s = _settings()
    assert s.mongo_uri == FAKE["MONGO_URI"] and isinstance(s.mongo_uri, str)
    assert s.jwt_secret == FAKE["JWT_SECRET"] and isinstance(s.jwt_secret, str)
    assert s.groq_api_keys == FAKE["GROQ_API_KEYS"]
    assert s.admin_1_password == FAKE["ADMIN_1_PASSWORD"]
    dump = s.model_dump()  # code that reads the dump keeps working: repr=False only hides from repr
    assert dump["mongo_uri"] == FAKE["MONGO_URI"] and dump["jwt_secret"] == FAKE["JWT_SECRET"]
    assert sorted(dump) == sorted(Settings.model_fields)


def test_repr_hides_only_secret_fields() -> None:
    hidden = {n for n, f in Settings.model_fields.items() if f.repr is False}
    assert hidden == {
        "mongo_uri",
        "jwt_secret",
        "groq_api_keys",
        "admin_1_password",
        "admin_2_password",
    }
    assert re.search(r"mongo_db_name='", repr(_settings()))


def test_describe_config_shows_no_key_or_uri() -> None:
    from app.features.ocr.providers.groq_provider import describe_config

    text = describe_config()
    assert "keys=" in text and "mongodb" not in text and "gsk_" not in text
    json.dumps(text)  # plain text


def test_start_up_error_for_a_weak_secret_does_not_echo_the_value(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import pytest

    from app.core.config import _load_settings

    monkeypatch.setenv("JWT_SECRET", "too-short-fake-secret")
    monkeypatch.setenv("MONGO_URI", FAKE["MONGO_URI"])
    with pytest.raises(SystemExit) as exc:
        _load_settings()
    assert "too-short-fake-secret" not in str(exc.value)
    assert "at least" in str(exc.value)
