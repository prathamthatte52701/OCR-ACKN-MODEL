"""Shared pytest setup. SAFETY: every test run is forced onto a database whose
name ends in "_test" (set BEFORE app.core.config is imported, because settings
are read once at import time) and aborts if that ever stops being true - the
tests insert and delete users/documents freely and must never touch the real
Atlas data."""

import os
import re
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

SESSION_TEST_DB = os.environ.get("ACKN_TEST_DB", "ackn_AI_model_test")
os.environ["MONGO_DB_NAME"] = SESSION_TEST_DB
# Test-only signing secret: lets a pre-generated token fixture (made with the old
# python-jose) be verified forever, and never involves the real secret.
os.environ["JWT_SECRET"] = "test-only-jwt-secret-for-pytest-0123456789abcdef"

from app.core.config import DEFAULT_DB_NAME, settings  # noqa: E402

if not settings.mongo_db_name.endswith("_test"):  # pragma: no cover - hard stop
    raise SystemExit(f"Refusing to run tests against DB '{settings.mongo_db_name}'")

from app.core.database import (  # noqa: E402
    close_mongo_connection,
    connect_to_mongo,
    get_database,
)
from app.core.rate_limit import limiter  # noqa: E402
from app.core.security import hash_password, sign_token  # noqa: E402
from app.main import app  # noqa: E402

limiter.enabled = False

_NEVER_DROP = {"admin", "local", "config"}


def safe_to_drop(name: Any, real_name: Any) -> bool:
    """True only for a plain "<something>_test" name that is not the real DB. Any doubt -> False."""
    if not isinstance(name, str) or not isinstance(real_name, str):
        return False
    if not re.fullmatch(r"[A-Za-z0-9_]+", name) or not name.endswith("_test") or name == "_test":
        return False
    if not name.startswith("ackn_"):  # only this project's own test databases, never another app's
        return False
    return name.lower() not in _NEVER_DROP and name.lower() != real_name.lower()


def drop_session_db(
    expected: str, current: Any, real_name: str, drop: Callable[[str], Any]
) -> bool:
    """Drops `expected` (the name this session set up) through `drop`, but only if the live
    setting and the environment still say the same thing and the guard accepts it."""
    if not (expected == current == os.environ.get("MONGO_DB_NAME")):
        return False
    if not safe_to_drop(expected, real_name):
        return False
    drop(expected)
    return True


def pytest_sessionfinish(session: Any, exitstatus: Any) -> None:
    """The db fixture only empties collections, so each session would leave its (now empty)
    test database on Atlas. Drop exactly the one this session used."""
    try:
        from pymongo import MongoClient

        client: Any = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=10000)
        try:
            drop_session_db(
                SESSION_TEST_DB, settings.mongo_db_name, DEFAULT_DB_NAME, client.drop_database
            )
        finally:
            client.close()
    except Exception:  # noqa: BLE001 - cleanup is best effort, never fails the run
        pass


# Strong enough to pass every password rule (length, classes, identity).
TEST_PASSWORD = "Xq7!mZv#4Lp2"


@pytest_asyncio.fixture
async def db() -> AsyncIterator[Any]:
    assert settings.mongo_db_name.endswith("_test")
    await connect_to_mongo()
    database = get_database()
    try:
        yield database
    finally:
        assert database.name.endswith("_test")
        for name in await database.list_collection_names():
            await database[name].delete_many({})
        await close_mongo_connection()


@pytest_asyncio.fixture
async def client(db: Any) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


class Account:
    def __init__(self, doc: dict[str, Any], password: str) -> None:
        self.id = doc["_id"]
        self.email = doc["email"]
        self.username = doc["username"]
        self.password = password

    @property
    def headers(self) -> dict[str, str]:
        # token is minted from the stored tokenVersion/role at creation time
        return {"Authorization": f"Bearer {self._token}"}

    _token: str = ""


@pytest_asyncio.fixture
async def make_user(db: Any) -> Any:
    async def _make(
        role: str = "user",
        status: str | None = "approved",
        password: str | None = TEST_PASSWORD,
        email: str | None = None,
        username: str | None = None,
    ) -> Account:
        tag = uuid.uuid4().hex[:6]
        now = datetime.now(UTC)
        doc: dict[str, Any] = {
            "username": username or f"u{tag}",
            "email": email or f"u{tag}@looptest.local",
            "role": role,
            "tokenVersion": 0,
            "createdAt": now,
            "updatedAt": now,
        }
        if status is not None:
            doc["status"] = status
        if password is not None:
            doc["passwordHash"] = hash_password(password)
        res = await db.users.insert_one(doc)
        doc["_id"] = res.inserted_id
        acct = Account(doc, password or "")
        acct._token = sign_token(str(res.inserted_id), 0, role)
        return acct

    return _make


@pytest.fixture
def new_password() -> str:
    return TEST_PASSWORD
