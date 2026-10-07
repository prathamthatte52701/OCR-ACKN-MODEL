"""T1/T2: admin-approval gate on signup/login/every protected route, plus the
login robustness fixes. Runs against the *_test database only (conftest.py)."""

import time
from typing import Any

import pytest

from app.scripts.migrate_user_status import migrate

PENDING = "Waiting for admin approval."
REJECTED = "Your request was not approved. Contact the admin."


async def test_signup_creates_pending_user(client: Any, db: Any, new_password: str) -> None:
    r = await client.post(
        "/api/auth/signup",
        json={"username": "newbie", "email": "newbie@looptest.local", "password": new_password},
    )
    assert r.status_code == 201
    assert r.json()["message"] == "Account created. Waiting for admin approval."
    assert (await db.users.find_one({"email": "newbie@looptest.local"}))["status"] == "pending"


async def test_pending_login_blocked_without_token(client: Any, make_user: Any) -> None:
    u = await make_user(status="pending")
    r = await client.post("/api/auth/login", json={"email": u.email, "password": u.password})
    assert r.status_code == 403 and r.json()["detail"] == PENDING
    assert "token" not in r.text


async def test_rejected_login_blocked(client: Any, make_user: Any) -> None:
    u = await make_user(status="rejected")
    r = await client.post("/api/auth/login", json={"email": u.email, "password": u.password})
    assert r.status_code == 403 and r.json()["detail"] == REJECTED


async def test_wrong_password_never_reveals_status(client: Any, make_user: Any) -> None:
    u = await make_user(status="pending")
    r = await client.post("/api/auth/login", json={"email": u.email, "password": "Wr0ng!pass9"})
    assert r.status_code == 401 and r.json()["detail"] == "Invalid email or password."


async def test_approved_and_legacy_users_login(client: Any, make_user: Any) -> None:
    for status in ("approved", None):  # None = legacy doc with no status field
        u = await make_user(status=status)
        r = await client.post("/api/auth/login", json={"email": u.email, "password": u.password})
        assert r.status_code == 200 and r.json()["token"]


@pytest.mark.parametrize("status,msg", [("pending", PENDING), ("rejected", REJECTED)])
async def test_old_token_blocked_on_protected_routes(
    client: Any, make_user: Any, status: str, msg: str
) -> None:
    u = await make_user(status=status)
    for path in ("/api/auth/me", "/api/documents", "/api/documents/export-history"):
        r = await client.get(path, headers=u.headers)
        assert r.status_code == 403 and r.json()["detail"] == msg, path


async def test_status_change_takes_effect_on_existing_token(
    client: Any, make_user: Any, db: Any
) -> None:
    u = await make_user(status="approved")
    assert (await client.get("/api/auth/me", headers=u.headers)).status_code == 200
    await db.users.update_one({"_id": u.id}, {"$set": {"status": "rejected"}})
    assert (await client.get("/api/auth/me", headers=u.headers)).status_code == 403


async def test_migration_is_idempotent_and_dry_run_safe(db: Any, make_user: Any) -> None:
    await make_user(status=None)
    await make_user(status="pending")
    assert await migrate(dry_run=True) == 1
    assert await db.users.count_documents({"status": {"$exists": False}}) == 1
    assert await migrate() == 1
    assert await migrate() == 0
    assert await db.users.count_documents({"status": "pending"}) == 1  # untouched


async def test_google_style_user_password_login_is_401_not_500(client: Any, make_user: Any) -> None:
    u = await make_user(password=None)  # no passwordHash
    r = await client.post("/api/auth/login", json={"email": u.email, "password": "Any0ne!pass1"})
    assert r.status_code == 401 and r.json()["detail"] == "Invalid email or password."


async def test_unknown_email_and_wrong_password_take_similar_time(
    client: Any, make_user: Any
) -> None:
    u = await make_user()

    async def timed(email: str) -> float:
        t = time.perf_counter()
        r = await client.post("/api/auth/login", json={"email": email, "password": "Wr0ng!pass9"})
        assert r.status_code == 401
        return time.perf_counter() - t

    unknown = min([await timed(f"nobody{i}@looptest.local") for i in range(3)])
    wrong = min([await timed(u.email) for _ in range(3)])
    assert unknown > wrong * 0.5, (unknown, wrong)  # unknown must not be the fast path
