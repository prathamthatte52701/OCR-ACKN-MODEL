"""Hardening found by the Issue 1 attackers: note sanitising, the per-email throttle, stale
requests after a forced change, and change-password vs a concurrent admin write."""

from typing import Any

from app.core import rate_limit
from app.features.auth import router as auth_router
from app.features.auth.password_requests import sanitize_note
from app.features.auth.test_password_requests_admin import (
    LIST,
    NEWPW,
    REQ,
    TEMP,
    _bearer,
    _login,
    _open_request,
    _rid,
    _set_temp,
)


def test_note_drops_invisible_and_bidi_characters() -> None:
    nasty = "a‮b c d​e⁦f⁩g\x85h\x9fi﻿j‏k"
    assert sanitize_note(nasty) == "abcdefghijk"
    assert sanitize_note("  plain note  ") == "plain note"
    assert len(sanitize_note("x" * 500)) == 200


async def test_strangers_cannot_exhaust_a_users_throttle(
    client: Any, db: Any, make_user: Any
) -> None:
    """Requests for an address that cannot create a row never use up that address's budget."""
    victim = await make_user()
    rate_limit._reset_limiter.clear(rate_limit._reset_email_limit, f"pwreset:{victim.email}")
    ghost = "ghost-" + victim.email
    for _ in range(6):  # more than the per-email limit, for an address that does not exist
        assert (await client.post(REQ, json={"email": ghost})).status_code == 200
    assert await db.passwordresetrequests.count_documents({}) == 0
    # a different address keeps its own budget: the real user's request still lands
    await client.post(REQ, json={"email": victim.email, "note": "mine"})
    row = await db.passwordresetrequests.find_one({"userId": victim.id})
    assert row is not None and row["note"] == "mine"


async def test_forced_change_closes_a_request_filed_after_the_temp_password(
    client: Any, db: Any, make_user: Any
) -> None:
    admin = await make_user(role="admin")
    user = await make_user()
    await _open_request(client, user)
    assert (await _set_temp(client, admin, await _rid(db, user))).status_code == 200
    # someone files a new request while the temp password is still unused
    rate_limit._reset_limiter.clear(rate_limit._reset_email_limit, f"pwreset:{user.email}")
    await client.post(REQ, json={"email": user.email, "note": "again"})
    assert (
        await db.passwordresetrequests.count_documents({"userId": user.id, "status": "open"}) == 1
    )
    token = (await _login(client, user.email, TEMP)).json()["token"]
    r = await client.post(
        "/api/auth/change-password",
        headers=_bearer(token),
        json={"currentPassword": TEMP, "newPassword": NEWPW, "confirmNewPassword": NEWPW},
    )
    assert r.status_code == 200
    assert (
        await db.passwordresetrequests.count_documents({"userId": user.id, "status": "open"}) == 0
    )
    closed = await db.passwordresetrequests.find({"userId": user.id}).to_list(None)
    assert {c["status"] for c in closed} == {"done"}


async def test_change_password_refuses_to_overwrite_a_concurrent_admin_write(
    client: Any, db: Any, make_user: Any, monkeypatch: Any
) -> None:
    user = await make_user()
    original_hash = auth_router.hash_password

    def hash_then_admin_writes(pw: str) -> str:
        """The admin's temp-password write lands while the user's change is being prepared."""
        import pymongo

        sync: Any = pymongo.MongoClient(auth_router.settings.mongo_uri)
        sync[db.name].users.update_one(
            {"_id": user.id},
            {"$set": {"passwordHash": "ADMIN-TEMP-HASH"}, "$inc": {"tokenVersion": 1}},
        )
        sync.close()
        return original_hash(pw)

    monkeypatch.setattr(auth_router, "hash_password", hash_then_admin_writes)
    r = await client.post(
        "/api/auth/change-password",
        headers=user.headers,
        json={"currentPassword": user.password, "newPassword": NEWPW, "confirmNewPassword": NEWPW},
    )
    assert r.status_code == 409
    stored = await db.users.find_one({"_id": user.id})
    assert stored is not None and stored["passwordHash"] == "ADMIN-TEMP-HASH"
    assert "Please log in again" in r.text and NEWPW not in r.text


async def test_deleting_a_user_leaves_no_request_rows(client: Any, db: Any, make_user: Any) -> None:
    admin = await make_user(role="admin")
    user = await make_user()
    await _open_request(client, user)
    r = await client.delete(f"/api/admin/users/{user.id}", headers=admin.headers)
    assert r.status_code == 200
    assert await db.passwordresetrequests.count_documents({"userId": user.id}) == 0
    assert (await client.get(LIST, headers=admin.headers)).json()["openCount"] == 0
