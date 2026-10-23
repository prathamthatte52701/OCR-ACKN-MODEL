"""Blank / missing MONGO_DB_NAME, FRONTEND_ORIGIN and ADMIN_ORIGIN mean "use the default";
MONGO_URI and JWT_SECRET stay required. Settings are built from explicit values only
(`_env_file=None` unless a test passes a template path) - the real backend/.env is never read
and no database is contacted."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings

DEFAULT_DB = "ackn_AI_model"
DEFAULT_FRONTEND = "http://localhost:5174"
DEFAULT_ADMIN = "http://localhost:5175"
FAKE_URI = "mongodb://localhost:27017/placeholder"
FAKE_SECRET = "x" * 48
ENV_KEYS = ("MONGO_URI", "MONGO_DB_NAME", "JWT_SECRET", "FRONTEND_ORIGIN", "ADMIN_ORIGIN")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """conftest sets MONGO_DB_NAME for the suite; these tests control every value themselves."""
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _settings(**values: Any) -> Settings:
    base: dict[str, Any] = {"MONGO_URI": FAKE_URI, "JWT_SECRET": FAKE_SECRET}
    base.update(values)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


@pytest.mark.parametrize("blank", ["", "   ", "\t", " \n "])
def test_blank_db_name_and_origins_use_the_defaults(blank: str) -> None:
    s = _settings(MONGO_DB_NAME=blank, FRONTEND_ORIGIN=blank, ADMIN_ORIGIN=blank)
    assert s.mongo_db_name == DEFAULT_DB
    assert s.frontend_origin == DEFAULT_FRONTEND
    assert s.admin_origin == DEFAULT_ADMIN
    assert s.cors_origins == [DEFAULT_FRONTEND, DEFAULT_ADMIN]
    assert all(origin for origin in s.cors_origins)


def test_missing_values_use_the_defaults() -> None:
    s = _settings()
    assert (s.mongo_db_name, s.frontend_origin, s.admin_origin) == (
        DEFAULT_DB,
        DEFAULT_FRONTEND,
        DEFAULT_ADMIN,
    )


def test_real_values_are_kept_and_stripped() -> None:
    s = _settings(
        MONGO_DB_NAME="  my_db_name  ",
        FRONTEND_ORIGIN="  http://localhost:3000 ",
        ADMIN_ORIGIN="\thttp://localhost:3001\n",
    )
    assert s.mongo_db_name == "my_db_name"
    assert s.cors_origins == ["http://localhost:3000", "http://localhost:3001"]


def test_origin_trailing_slash_is_left_alone() -> None:
    """Only whitespace is stripped; no new rules are invented."""
    assert _settings(FRONTEND_ORIGIN="http://localhost:3000/").frontend_origin == (
        "http://localhost:3000/"
    )


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_mongo_uri_still_fails_with_a_clear_message(blank: str) -> None:
    with pytest.raises(ValidationError) as exc:
        _settings(MONGO_URI=blank)
    assert "MONGO_URI" in str(exc.value)


def test_missing_required_values_still_fail() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, JWT_SECRET=FAKE_SECRET)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        Settings(_env_file=None, MONGO_URI=FAKE_URI)  # type: ignore[call-arg]


@pytest.mark.parametrize("secret", ["", "short", "x" * 31])
def test_blank_or_short_jwt_secret_still_fails(secret: str) -> None:
    with pytest.raises(ValidationError):
        _settings(JWT_SECRET=secret)


def test_env_example_template_gives_the_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Load the shipped template itself (a copy of it, with only the two required values filled
    in through the process environment). The real backend/.env is never opened."""
    template = Path(__file__).resolve().parents[2] / ".env.example"
    assert template.name == ".env.example" and template.exists()
    monkeypatch.setenv("MONGO_URI", FAKE_URI)
    monkeypatch.setenv("JWT_SECRET", FAKE_SECRET)
    s = Settings(_env_file=template)  # type: ignore[call-arg]
    assert s.mongo_db_name == DEFAULT_DB
    assert s.frontend_origin == DEFAULT_FRONTEND
    assert s.admin_origin == DEFAULT_ADMIN
    assert all(origin for origin in s.cors_origins)


@pytest.mark.parametrize("blank", ["", "  ", "\t"])
def test_audit_retention_blank_means_365(blank: str) -> None:
    assert _settings(AUDIT_LOG_RETENTION_DAYS=blank).audit_log_retention_days == 365
    assert _settings().audit_log_retention_days == 365


@pytest.mark.parametrize("raw,expected", [("0", 0), ("30", 30), (" 3650 ", 3650), (90, 90)])
def test_audit_retention_valid_values(raw: object, expected: int) -> None:
    assert _settings(AUDIT_LOG_RETENTION_DAYS=raw).audit_log_retention_days == expected


@pytest.mark.parametrize("bad", ["-1", "3651", "1.5", "abc", "1e3", "٣"])
def test_audit_retention_invalid_values_are_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        _settings(AUDIT_LOG_RETENTION_DAYS=bad)
