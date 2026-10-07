"""T9: a user cannot change their own email; only an admin can (and it signs
the user out + is audited)."""

from typing import Any


async def test_user_cannot_change_own_email(client: Any, make_user: Any, db: Any) -> None:
    u = await make_user()
    r = await client.patch("/api/auth/me", headers=u.headers, json={"email": "new@looptest.local"})
    assert r.status_code == 403
    assert (await db.users.find_one({"_id": u.id}))["email"] == u.email


async def test_user_can_still_edit_username_and_resend_same_email(
    client: Any, make_user: Any
) -> None:
    u = await make_user()
    r = await client.patch(
        "/api/auth/me", headers=u.headers, json={"username": "renamed", "email": u.email.upper()}
    )
    assert r.status_code == 200 and r.json()["user"]["username"] == "renamed"
    assert r.json()["user"]["email"] == u.email


async def test_admin_changes_email_bumps_token_and_audits(
    client: Any, make_user: Any, db: Any
) -> None:
    admin = await make_user(role="admin")
    u = await make_user()
    r = await client.put(
        f"/api/admin/users/{u.id}/email",
        headers=admin.headers,
        json={"email": "Fresh@LoopTest.local"},
    )
    assert r.status_code == 200 and r.json()["user"]["email"] == "fresh@looptest.local"
    assert (await client.get("/api/auth/me", headers=u.headers)).status_code == 401  # signed out
    log = await db.auditlogs.find_one({"action": "user_email_changed"})
    assert (
        log["context"]["oldEmail"] == u.email
        and log["context"]["newEmail"] == "fresh@looptest.local"
    )
    ok = await client.post(
        "/api/auth/login", json={"email": "fresh@looptest.local", "password": u.password}
    )
    assert ok.status_code == 200


async def test_admin_email_validation_and_uniqueness(client: Any, make_user: Any) -> None:
    admin = await make_user(role="admin")
    u, other = await make_user(), await make_user()
    for bad in ("not-an-email", "a" * 300 + "@x.com", ""):
        r = await client.put(
            f"/api/admin/users/{u.id}/email", headers=admin.headers, json={"email": bad}
        )
        assert r.status_code in (400, 422), bad
    dup = await client.put(
        f"/api/admin/users/{u.id}/email", headers=admin.headers, json={"email": other.email}
    )
    assert dup.status_code == 400
    missing = await client.put(
        "/api/admin/users/000000000000000000000000/email",
        headers=admin.headers,
        json={"email": "a@b.co"},
    )
    assert missing.status_code == 404


async def test_non_admin_cannot_use_admin_email_route(client: Any, make_user: Any) -> None:
    u, other = await make_user(), await make_user()
    r = await client.put(
        f"/api/admin/users/{other.id}/email", headers=u.headers, json={"email": "z@looptest.local"}
    )
    assert r.status_code == 403


async def test_admin_patch_email_also_bumps_token(client: Any, make_user: Any) -> None:
    admin = await make_user(role="admin")
    u = await make_user()
    r = await client.patch(
        f"/api/admin/users/{u.id}", headers=admin.headers, json={"email": "viapatch@looptest.local"}
    )
    assert r.status_code == 200
    assert (await client.get("/api/auth/me", headers=u.headers)).status_code == 401
