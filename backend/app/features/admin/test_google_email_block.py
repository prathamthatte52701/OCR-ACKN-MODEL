"""A Google user's email cannot be changed by an admin (their next Google sign-in looks the account
up by email, so a change would spawn a NEW pending account). Same email - even differently cased
or padded - is not a change. Password users are unaffected. Runs on the *_test DB only."""

from typing import Any

import pytest

MSG = "This user signs in with Google, so the email cannot be changed."


async def _target(db: Any, make_user: Any, provider: str | None) -> Any:
    u = await make_user()
    if provider is not None:
        await db.users.update_one({"_id": u.id}, {"$set": {"authProvider": provider}})
    return u


async def _send(client: Any, admin: Any, method: str, u: Any, body: dict) -> Any:
    url = f"/api/admin/users/{u.id}" + ("/email" if method == "PUT" else "")
    return await client.request(method, url, headers=admin.headers, json=body)


@pytest.mark.parametrize("provider", ["google", "local+google"])
@pytest.mark.parametrize("method", ["PATCH", "PUT"])
async def test_google_email_change_refused(
    client: Any, make_user: Any, db: Any, provider: str, method: str
) -> None:
    admin, u = await make_user(role="admin"), await _target(db, make_user, provider)
    r = await _send(client, admin, method, u, {"email": "other@looptest.local"})
    assert r.status_code == 400 and r.json()["detail"] == MSG
    after = await db.users.find_one({"_id": u.id})
    assert after["email"] == u.email and after["tokenVersion"] == 0
    assert await db.auditlogs.count_documents({"action": "user_email_changed"}) == 0


async def test_google_different_address_in_other_case_is_a_change(
    client: Any, make_user: Any, db: Any
) -> None:
    admin, u = await make_user(role="admin"), await _target(db, make_user, "google")
    r = await _send(client, admin, "PATCH", u, {"email": "  OTHER@Looptest.Local "})
    assert r.status_code == 400 and r.json()["detail"] == MSG


@pytest.mark.parametrize("method", ["PATCH", "PUT"])
async def test_google_same_email_is_allowed_even_padded_or_recased(
    client: Any, make_user: Any, db: Any, method: str
) -> None:
    admin, u = await make_user(role="admin"), await _target(db, make_user, "google")
    for sent in (u.email, f"  {u.email.upper()} "):
        r = await _send(client, admin, method, u, {"email": sent})
        assert r.status_code == 200, r.text
    after = await db.users.find_one({"_id": u.id})
    assert after["email"] == u.email and after["tokenVersion"] == 0
    assert await db.auditlogs.count_documents({"action": "user_email_changed"}) == 0


async def test_google_username_edit_still_works_with_unchanged_email(
    client: Any, make_user: Any, db: Any
) -> None:
    admin, u = await make_user(role="admin"), await _target(db, make_user, "google")
    r = await _send(client, admin, "PATCH", u, {"username": "renamed", "email": u.email})
    assert r.status_code == 200 and r.json()["user"]["username"] == "renamed"
    r = await _send(client, admin, "PATCH", u, {"username": "again"})  # no email at all
    assert r.status_code == 200 and r.json()["user"]["username"] == "again"
    assert (await db.users.find_one({"_id": u.id}))["tokenVersion"] == 0


@pytest.mark.parametrize("provider", [None, "local"])
@pytest.mark.parametrize("method", ["PATCH", "PUT"])
async def test_password_user_email_change_unchanged(
    client: Any, make_user: Any, db: Any, provider: str | None, method: str
) -> None:
    admin, u = await make_user(role="admin"), await _target(db, make_user, provider)
    r = await _send(client, admin, method, u, {"email": "New.Addr@looptest.local"})
    assert r.status_code == 200 and r.json()["user"]["email"] == "new.addr@looptest.local"
    after = await db.users.find_one({"_id": u.id})
    assert after["tokenVersion"] == 1
    assert await db.auditlogs.count_documents({"action": "user_email_changed"}) == 1


async def test_admin_self_edit_rule_unchanged(client: Any, make_user: Any, db: Any) -> None:
    a, b = await make_user(role="admin"), await make_user(role="admin")
    await db.users.update_one({"_id": b.id}, {"$set": {"authProvider": "google"}})
    r = await _send(client, a, "PATCH", b, {"email": "x@looptest.local"})
    assert r.status_code == 403  # another admin: still the admin-only-self message, not Google's
