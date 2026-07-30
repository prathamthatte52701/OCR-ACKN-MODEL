"""Real-integration tests for POST /auth/google (Google OAuth login) plus the
side effects it introduces elsewhere in auth/router.py: local-account
linking, the forgot-password guard for Google-only accounts, and token
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

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from bson import ObjectId
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
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["email"] == email
    assert body["user"]["role"] == "user"
    assert body["token"]

    db = get_database()
    user = await db.users.find_one({"_id": ObjectId(body["user"]["id"])})
    assert user is not None
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
# 3. Google-only account blocked from forgot-password
# ---------------------------------------------------------------------------


async def test_google_only_account_blocked_from_forgot_password(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = _unique_email("googleonly")
    _mock_google_payload(
        monkeypatch, {"email": email, "email_verified": True, "sub": "google-sub-only"}
    )
    resp = await client.post("/api/auth/google", json={"idToken": "fake-token"})
    assert resp.status_code == 200, resp.text
    username = resp.json()["user"]["username"]

    verify_resp = await client.post(
        "/api/auth/forgot-password/verify", json={"username": username, "email": email}
    )
    assert verify_resp.status_code == 400
    detail = verify_resp.json()["detail"]
    assert "Google Sign-In" in detail
    assert detail != "Username and email do not match our records."

    # A genuinely non-matching account still gets the generic anti-enumeration message.
    generic_resp = await client.post(
        "/api/auth/forgot-password/verify",
        json={"username": "nobody12", "email": "nobody@example.com"},
    )
    assert generic_resp.status_code == 400
    assert generic_resp.json()["detail"] == "Username and email do not match our records."


# ---------------------------------------------------------------------------
# 4. Token revocation for the linked local+google account
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
    assert resp.status_code == 200, resp.text
    user_id = resp.json()["user"]["id"]

    db = get_database()
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
