"""Google sign-in linking to an EXISTING password account must remove the password.

Attack this closes: a stranger signs up with a victim's email + their own password, the admin
approves, the victim later signs in with Google and the accounts link - the stranger's password
must not keep working. Linking now drops the password, ends every old session and closes any
open password-reset request; already-Google accounts are untouched.
"""

import asyncio
from typing import Any

import pytest
from google.oauth2 import id_token as google_id_token

from app.features.auth import router as auth_router

GOOGLE = "/api/auth/google"
LOGIN = "/api/auth/login"
ME = "/api/auth/me"


def _google(monkeypatch: pytest.MonkeyPatch, email: str, sub: str = "g-link") -> None:
    monkeypatch.setattr(
        google_id_token,
        "verify_oauth2_token",
        lambda *_a, **_k: {"email": email, "email_verified": True, "sub": sub},
    )


async def _sign_in(client: Any) -> Any:
    return await client.post(GOOGLE, json={"idToken": "fake"})


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _links(db: Any, user_id: Any) -> int:
    return await db.auditlogs.count_documents(
        {"userId": user_id, "action": "google_account_linked"}
    )


@pytest.mark.parametrize("role", ["user", "admin"])
async def test_link_removes_password_and_google_login_works(
    client: Any, db: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch, role: str
) -> None:
    u = await make_user(role=role)
    _google(monkeypatch, u.email)

    r = await _sign_in(client)
    assert r.status_code == 200, r.text
    assert (await client.get(ME, headers=_bearer(r.json()["token"]))).status_code == 200

    doc = await db.users.find_one({"_id": u.id})
    assert doc["authProvider"] == "google" and doc["googleId"] == "g-link"
    assert "passwordHash" not in doc and doc["mustChangePassword"] is False
    assert doc["tokenVersion"] == 1
    assert await _links(db, u.id) == 1

    # the attacker's password no longer logs in (same generic 401 as a wrong password)
    old = await client.post(LOGIN, json={"email": u.email, "password": u.password})
    assert old.status_code == 401, old.text
    wrong = await client.post(LOGIN, json={"email": u.email, "password": "Wr0ng!passw0rd"})
    assert wrong.status_code == 401 and wrong.json() == old.json()


async def test_token_issued_before_link_dies(
    client: Any, db: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    u = await make_user()
    assert (await client.get(ME, headers=u.headers)).status_code == 200
    _google(monkeypatch, u.email)
    assert (await _sign_in(client)).status_code == 200
    assert (await client.get(ME, headers=u.headers)).status_code == 401


async def test_link_user_without_password_hash(
    client: Any, db: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    u = await make_user(password=None)
    _google(monkeypatch, u.email)
    r = await _sign_in(client)
    assert r.status_code == 200, r.text
    doc = await db.users.find_one({"_id": u.id})
    assert doc["authProvider"] == "google" and "passwordHash" not in doc
    assert (await client.get(ME, headers=_bearer(r.json()["token"]))).status_code == 200


async def test_google_only_user_password_login_is_generic_401(
    client: Any, db: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    u = await make_user(password=None)
    await db.users.update_one({"_id": u.id}, {"$set": {"authProvider": "google"}})
    r = await client.post(LOGIN, json={"email": u.email, "password": "Wr0ng!passw0rd"})
    assert r.status_code == 401 and r.json()["detail"] == "Invalid email or password."


async def test_already_google_user_is_unchanged(
    client: Any, db: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    u = await make_user(password=None)
    await db.users.update_one(
        {"_id": u.id}, {"$set": {"authProvider": "google", "googleId": "g-link"}}
    )
    _google(monkeypatch, u.email)
    for _ in range(2):
        r = await _sign_in(client)
        assert r.status_code == 200, r.text
        assert (await client.get(ME, headers=_bearer(r.json()["token"]))).status_code == 200
    assert (await db.users.find_one({"_id": u.id}))["tokenVersion"] == 0
    assert await _links(db, u.id) == 0
    assert await db.auditlogs.count_documents({"userId": u.id, "action": "login"}) == 2


async def test_existing_local_plus_google_account_is_not_migrated(
    client: Any, db: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    u = await make_user()
    await db.users.update_one(
        {"_id": u.id}, {"$set": {"authProvider": "local+google", "googleId": "g-old"}}
    )
    _google(monkeypatch, u.email, "g-old")
    assert (await _sign_in(client)).status_code == 200
    doc = await db.users.find_one({"_id": u.id})
    assert (
        doc["authProvider"] == "local+google" and doc["passwordHash"] and doc["tokenVersion"] == 0
    )
    assert await _links(db, u.id) == 0


async def test_concurrent_links_link_once(
    client: Any, db: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    u = await make_user()
    _google(monkeypatch, u.email)
    rs = await asyncio.gather(*[_sign_in(client) for _ in range(2)])
    assert [r.status_code for r in rs] == [200, 200], [r.text for r in rs]
    for r in rs:
        assert (await client.get(ME, headers=_bearer(r.json()["token"]))).status_code == 200
    doc = await db.users.find_one({"_id": u.id})
    assert doc["authProvider"] == "google" and doc["tokenVersion"] == 1
    assert await _links(db, u.id) == 1


class _StaleFirstRead:
    """Proxy over the real db: the FIRST users.find_one returns a pre-link snapshot of the user
    (the read of a request that lost the link race); everything else is real."""

    def __init__(self, real: Any, stale: dict) -> None:
        self._real = real
        self.users = _UsersProxy(real.users, stale)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


class _UsersProxy:
    def __init__(self, real: Any, stale: dict) -> None:
        self._real = real
        self._stale: dict | None = stale

    async def find_one(self, *args: Any, **kwargs: Any) -> Any:
        if self._stale is not None:
            stale, self._stale = self._stale, None
            return stale
        return await self._real.find_one(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


async def test_lost_link_race_falls_through_to_normal_google_login(
    client: Any, db: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    u = await make_user()
    stale = await db.users.find_one({"_id": u.id})  # still a password account
    _google(monkeypatch, u.email)
    assert (await _sign_in(client)).status_code == 200  # the "winner" links
    monkeypatch.setattr(auth_router, "get_database", lambda: _StaleFirstRead(db, stale))
    r = await _sign_in(client)  # the loser: conditional update matches nothing
    assert r.status_code == 200, r.text
    assert (await client.get(ME, headers=_bearer(r.json()["token"]))).status_code == 200
    assert (await db.users.find_one({"_id": u.id}))["tokenVersion"] == 1
    assert await _links(db, u.id) == 1


async def test_account_rejected_between_read_and_link_is_not_linked(
    client: Any, db: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    u = await make_user()
    stale = await db.users.find_one({"_id": u.id})  # approved, password account
    await db.users.update_one(
        {"_id": u.id}, {"$set": {"status": "rejected", "decision": "rejected"}}
    )  # the admin rejects it after that read
    _google(monkeypatch, u.email)
    monkeypatch.setattr(auth_router, "get_database", lambda: _StaleFirstRead(db, stale))
    r = await _sign_in(client)
    assert r.status_code == 403 and "token" not in r.text, r.text
    after = await db.users.find_one({"_id": u.id})
    assert "passwordHash" in after and after["tokenVersion"] == 0 and "googleId" not in after
    assert await _links(db, u.id) == 0


@pytest.mark.parametrize(
    "fields",
    [{"status": "pending"}, {"status": "rejected"}, {"status": "rejected", "decision": "revoked"}],
)
async def test_unapproved_accounts_are_blocked_before_any_link(
    client: Any, db: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch, fields: dict
) -> None:
    u = await make_user(status=fields["status"])
    if "decision" in fields:
        await db.users.update_one({"_id": u.id}, {"$set": {"decision": fields["decision"]}})
    before = await db.users.find_one({"_id": u.id})
    _google(monkeypatch, u.email)
    r = await _sign_in(client)
    assert r.status_code == 403, r.text
    after = await db.users.find_one({"_id": u.id})
    assert after["passwordHash"] == before["passwordHash"] and after["tokenVersion"] == 0
    assert "googleId" not in after and await _links(db, u.id) == 0


async def test_link_closes_open_password_reset_request(
    client: Any, db: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    u = await make_user()
    r = await client.post("/api/auth/password-reset-request", json={"email": u.email, "note": "x"})
    assert r.status_code == 200
    assert await db.passwordresetrequests.count_documents({"status": "open"}) == 1
    _google(monkeypatch, u.email)
    assert (await _sign_in(client)).status_code == 200
    row = await db.passwordresetrequests.find_one({"userId": u.id})
    assert row["status"] == "done" and row["resolution"] == "google_linked"
    assert row["resolvedAt"] and row["resolvedBy"] is None
