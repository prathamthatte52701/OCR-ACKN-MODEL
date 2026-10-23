"""Real-integration tests for POST /auth/google (Google OAuth login) plus the
side effects it introduces elsewhere in auth/router.py: local-account
linking and token
revocation via tokenVersion.

No test-db mocking infra exists in this repo (see CLAUDE.md) - this hits the
real dev MongoDB (backend/.env MONGO_URI) through the FastAPI app in-process
via httpx.ASGITransport, using throwaway `googletest-*@example.com` emails
that are deleted in the per-test teardown.

The db-connect/close fixture is function-scoped (not module-scoped) on
purpose: pytest-asyncio gives each async test function its own event loop
by default, and Motor's AsyncIOMotorClient is bound to the loop it was
created on - a module-scoped connection opened on test #1's loop raises
"Future attached to a different loop" once test #2 runs on a fresh one.

Run: pytest app/features/auth/test_google_auth.py
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from google.oauth2 import id_token as google_id_token
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.database import close_mongo_connection, connect_to_mongo, get_database
from app.core.security import hash_password, sign_token
from app.main import app

LOCAL_PASSWORD = "OriginalPass1!"
NEW_PASSWORD = "ChangedPass1!"

_test_emails: list[str] = []


def _unique_email(tag: str) -> str:
    email = f"googletest-{tag}-{uuid.uuid4().hex[:8]}@example.com"
    _test_emails.append(email)
    return email


@pytest_asyncio.fixture(autouse=True)
async def _db_lifecycle() -> AsyncIterator[None]:
    await connect_to_mongo()
    try:
        yield
    finally:
        db = get_database()
        if _test_emails:
            await db.users.delete_many({"email": {"$in": _test_emails}})
            _test_emails.clear()
        await close_mongo_connection()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _mock_google_payload(monkeypatch: pytest.MonkeyPatch, payload: dict) -> None:
    def _fake_verify(_token: str, _request: object, _audience: str) -> dict:
        return payload

    monkeypatch.setattr(google_id_token, "verify_oauth2_token", _fake_verify)


async def _insert_admin(db: AsyncIOMotorDatabase) -> str:
    email = _unique_email("admin")
    now = datetime.now(UTC)
    await db.users.insert_one(
        {
            "username": "gtadmin",
            "email": email,
            "passwordHash": hash_password("AdminPass1!"),
            "role": "admin",
            "tokenVersion": 0,
            "createdAt": now,
            "updatedAt": now,
        }
    )
    user = await db.users.find_one({"email": email})
    assert user is not None
    return str(user["_id"])


# ---------------------------------------------------------------------------
# 1. New user via Google
# ---------------------------------------------------------------------------


async def test_new_user_created_via_google(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = _unique_email("new")
    _mock_google_payload(
        monkeypatch, {"email": email, "email_verified": True, "sub": "google-sub-new"}
    )

    resp = await client.post("/api/auth/google", json={"idToken": "fake-token"})
    assert resp.status_code == 403, resp.text
    assert "token" not in resp.text

    db = get_database()
    user = await db.users.find_one({"email": email})
    assert user is not None
    assert user["status"] == "pending"
    assert user["authProvider"] == "google"
    assert user["role"] == "user"
    assert user["tokenVersion"] == 0
    assert "passwordHash" not in user
    assert user["googleId"] == "google-sub-new"


async def test_unverified_email_rejected(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = _unique_email("unverified")
    _mock_google_payload(
        monkeypatch, {"email": email, "email_verified": False, "sub": "google-sub-unverified"}
    )
    resp = await client.post("/api/auth/google", json={"idToken": "fake-token"})
    assert resp.status_code == 401

    db = get_database()
    assert await db.users.find_one({"email": email}) is None


# ---------------------------------------------------------------------------
# 2. Existing local-password account links via Google
# ---------------------------------------------------------------------------


async def test_existing_local_account_links_via_google(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = _unique_email("link")
    username = "gtlink"

    signup_resp = await client.post(
        "/api/auth/signup",
        json={"username": username, "email": email, "password": LOCAL_PASSWORD},
    )
    assert signup_resp.status_code == 201, signup_resp.text

    db = get_database()
    # signup now creates a pending account; approve it so the password login below is allowed
    await db.users.update_one({"email": email}, {"$set": {"status": "approved"}})
    original = await db.users.find_one({"email": email})
    assert original is not None
    original_id = original["_id"]
    original_hash = original["passwordHash"]

    _mock_google_payload(
        monkeypatch, {"email": email, "email_verified": True, "sub": "google-sub-link"}
    )
    google_resp = await client.post("/api/auth/google", json={"idToken": "fake-token"})
    assert google_resp.status_code == 200, google_resp.text
    assert google_resp.json()["user"]["id"] == str(original_id)

    # No duplicate doc - still exactly one user with this email.
    assert await db.users.count_documents({"email": email}) == 1

    linked = await db.users.find_one({"_id": original_id})
    assert linked is not None
    assert linked["authProvider"] == "local+google"
    assert linked["googleId"] == "google-sub-link"
    assert linked["passwordHash"] == original_hash  # untouched

    # Original password still works via the normal /login path.
    login_resp = await client.post(
        "/api/auth/login", json={"email": email, "password": LOCAL_PASSWORD}
    )
    assert login_resp.status_code == 200, login_resp.text


# ---------------------------------------------------------------------------
# 3. Token revocation for the linked local+google account
# ---------------------------------------------------------------------------


async def test_password_change_revokes_prior_token(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = _unique_email("revoke")
    username = "gtrevok"

    signup_resp = await client.post(
        "/api/auth/signup",
        json={"username": username, "email": email, "password": LOCAL_PASSWORD},
    )
    assert signup_resp.status_code == 201, signup_resp.text
    await get_database().users.update_one({"email": email}, {"$set": {"status": "approved"}})

    _mock_google_payload(
        monkeypatch, {"email": email, "email_verified": True, "sub": "google-sub-revoke"}
    )
    google_resp = await client.post("/api/auth/google", json={"idToken": "fake-token"})
    assert google_resp.status_code == 200, google_resp.text
    old_token = google_resp.json()["token"]

    # The pre-change token works right now.
    me_resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {old_token}"})
    assert me_resp.status_code == 200, me_resp.text

    change_resp = await client.post(
        "/api/auth/change-password",
        json={
            "currentPassword": LOCAL_PASSWORD,
            "newPassword": NEW_PASSWORD,
            "confirmNewPassword": NEW_PASSWORD,
        },
        headers={"Authorization": f"Bearer {old_token}"},
    )
    assert change_resp.status_code == 200, change_resp.text

    stale_resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {old_token}"})
    assert stale_resp.status_code == 401


# ---------------------------------------------------------------------------
# 5. Admin serialization surfaces authProvider
# ---------------------------------------------------------------------------


async def test_admin_users_list_includes_auth_provider(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = _unique_email("adminview")
    _mock_google_payload(
        monkeypatch, {"email": email, "email_verified": True, "sub": "google-sub-adminview"}
    )
    resp = await client.post("/api/auth/google", json={"idToken": "fake-token"})
    assert resp.status_code == 403, resp.text

    db = get_database()
    created = await db.users.find_one({"email": email})
    assert created is not None
    user_id = str(created["_id"])
    admin_id = await _insert_admin(db)
    admin_token = sign_token(admin_id, 0, "admin")

    users_resp = await client.get(
        "/api/admin/users",
        params={"limit": 1000},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert users_resp.status_code == 200, users_resp.text
    users = {u["id"]: u for u in users_resp.json()["users"]}
    assert user_id in users
    assert users[user_id]["authProvider"] == "google"


# ---------------------------------------------------------------------------
# 6. Approval gate applies to existing users signing in with Google
# ---------------------------------------------------------------------------


async def _existing(email: str, **fields: object) -> None:
    now = datetime.now(UTC)
    await get_database().users.insert_one(
        {
            "username": "gtexist",
            "email": email,
            "role": "user",
            "tokenVersion": 0,
            "authProvider": "google",
            "googleId": "g-existing",
            "createdAt": now,
            "updatedAt": now,
            **fields,
        }
    )


@pytest.mark.parametrize(
    "fields,code",
    [
        ({"status": "pending"}, "ACCOUNT_PENDING"),
        ({"status": "rejected"}, "ACCOUNT_REJECTED"),
        ({"status": "rejected", "decision": "revoked"}, "ACCOUNT_REVOKED"),
    ],
)
async def test_existing_unapproved_google_user_gets_403(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, fields: dict, code: str
) -> None:
    email = _unique_email("gate")
    await _existing(email, **fields)
    _mock_google_payload(monkeypatch, {"email": email, "email_verified": True, "sub": "g-existing"})
    resp = await client.post("/api/auth/google", json={"idToken": "fake-token"})
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["code"] == code
    assert "token" not in resp.text


async def test_existing_approved_google_user_logs_in(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = _unique_email("okexist")
    await _existing(email, status="approved")
    _mock_google_payload(monkeypatch, {"email": email, "email_verified": True, "sub": "g-existing"})
    resp = await client.post("/api/auth/google", json={"idToken": "fake-token"})
    assert resp.status_code == 200 and resp.json()["token"]


NEW_PENDING_MESSAGE = "Your request was sent. Sign in again after the admin approves."


async def test_new_google_user_is_pending_without_token(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = _unique_email("autoappr")
    _mock_google_payload(monkeypatch, {"email": email, "email_verified": True, "sub": "g-new2"})
    resp = await client.post("/api/auth/google", json={"idToken": "fake-token"})
    assert resp.status_code == 403, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "ACCOUNT_PENDING" and detail["message"] == NEW_PENDING_MESSAGE
    assert detail["requestedAt"] and detail["decidedAt"] is None and detail["reason"] is None
    assert "token" not in resp.text
    user = await get_database().users.find_one({"email": email})
    assert user is not None and user["status"] == "pending" and "passwordHash" not in user
    assert user["authProvider"] == "google" and user["role"] == "user"
    # second sign-in while pending: the normal pending 403, still no second account
    again = await client.post("/api/auth/google", json={"idToken": "fake-token"})
    assert again.status_code == 403 and again.json()["detail"]["code"] == "ACCOUNT_PENDING"
    assert await get_database().users.count_documents({"email": email}) == 1


async def test_concurrent_first_google_logins_create_one_account(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = _unique_email("race")
    _mock_google_payload(monkeypatch, {"email": email, "email_verified": True, "sub": "g-race"})
    rs = await asyncio.gather(
        *[client.post("/api/auth/google", json={"idToken": "fake-token"}) for _ in range(2)]
    )
    assert [r.status_code for r in rs] == [403, 403], [r.text for r in rs]
    assert all(r.json()["detail"]["code"] == "ACCOUNT_PENDING" for r in rs)
    assert await get_database().users.count_documents({"email": email}) == 1


class _FirstLookupMisses:
    """Proxy over the real db: the FIRST users.find_one returns None (the "no account yet" read of
    a request that lost the race); the rest is real, so the insert really hits E11000."""

    def __init__(self, real: AsyncIOMotorDatabase) -> None:
        self._real = real
        self.users = _UsersProxy(real.users)

    def __getattr__(self, name: str) -> object:
        return getattr(self._real, name)


class _UsersProxy:
    def __init__(self, real: object) -> None:
        self._real = real
        self._missed = False

    async def find_one(self, *args: object, **kwargs: object) -> object:
        if not self._missed:
            self._missed = True
            return None
        return await self._real.find_one(*args, **kwargs)  # type: ignore[attr-defined]

    def __getattr__(self, name: str) -> object:
        return getattr(self._real, name)


async def test_lost_race_and_winner_already_approved_signs_in(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.features.auth import router as auth_router

    email = _unique_email("raceok")
    await _existing(email, status="approved")
    _mock_google_payload(monkeypatch, {"email": email, "email_verified": True, "sub": "g-existing"})
    real = get_database()
    monkeypatch.setattr(auth_router, "get_database", lambda: _FirstLookupMisses(real))
    r = await client.post("/api/auth/google", json={"idToken": "fake-token"})
    assert r.status_code == 200 and r.json()["token"], r.text
    assert await real.users.count_documents({"email": email}) == 1


async def test_lost_race_and_winner_still_pending_gets_403(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.features.auth import router as auth_router

    email = _unique_email("racepend")
    await _existing(email, status="pending")
    _mock_google_payload(monkeypatch, {"email": email, "email_verified": True, "sub": "g-existing"})
    real = get_database()
    monkeypatch.setattr(auth_router, "get_database", lambda: _FirstLookupMisses(real))
    r = await client.post("/api/auth/google", json={"idToken": "fake-token"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "ACCOUNT_PENDING", r.text
    assert "token" not in r.text


async def test_approved_google_login_consumes_approval_notice_once(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = _unique_email("notice")
    decided = datetime.now(UTC)
    await _existing(
        email,
        status="approved",
        decision="approved",
        decidedAt=decided,
        approvalNoticePending=True,
    )
    _mock_google_payload(monkeypatch, {"email": email, "email_verified": True, "sub": "g-existing"})
    first = (await client.post("/api/auth/google", json={"idToken": "fake-token"})).json()
    assert first["justApproved"] is True and first["approvedAt"]
    second = (await client.post("/api/auth/google", json={"idToken": "fake-token"})).json()
    assert second["justApproved"] is False


async def test_pending_local_account_cannot_link_via_google(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = _unique_email("pendlink")
    r = await client.post(
        "/api/auth/signup",
        json={"username": "gtpend", "email": email, "password": LOCAL_PASSWORD},
    )
    assert r.status_code == 201, r.text  # signup leaves it pending
    _mock_google_payload(monkeypatch, {"email": email, "email_verified": True, "sub": "g-pend"})
    resp = await client.post("/api/auth/google", json={"idToken": "fake-token"})
    assert resp.status_code == 403 and resp.json()["detail"]["code"] == "ACCOUNT_PENDING"
    user = await get_database().users.find_one({"email": email})
    assert user is not None and "googleId" not in user  # not linked
