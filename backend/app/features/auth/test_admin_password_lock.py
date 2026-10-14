"""An admin's password changes only via their own change-password (or the reset script)."""

from typing import Any

from app.core.security import verify_password

NEW = "Nw8#kLp2!Tz9"
V, R = "/api/auth/forgot-password/verify", "/api/auth/forgot-password/reset"


def _reset(who: dict) -> dict:
    return {**who, "newPassword": NEW, "confirmNewPassword": NEW}


async def _snap(db: Any, acct: Any) -> tuple:
    u = await db.users.find_one({"_id": acct.id})
    return u["passwordHash"], u["tokenVersion"]


async def test_admin_forgot_password_generic_400_and_nothing_written(
    client: Any, db: Any, make_user: Any
) -> None:
    admin = await make_user(role="admin")
    before = await _snap(db, admin)
    who = {"username": admin.username, "email": admin.email}
    ghost = {"username": "ghost1", "email": "ghost@looptest.local"}
    v_admin, v_ghost = await client.post(V, json=who), await client.post(V, json=ghost)
    r_admin, r_ghost = await client.post(R, json=_reset(who)), await client.post(
        R, json=_reset(ghost)
    )
    for a, g in ((v_admin, v_ghost), (r_admin, r_ghost)):
        assert a.status_code == g.status_code == 400
        assert a.json() == g.json() == {"detail": "Username and email do not match our records."}
    assert await _snap(db, admin) == before
    assert await db.auditlogs.count_documents({"userId": admin.id}) == 0


async def test_admin_variants_blocked(client: Any, db: Any, make_user: Any) -> None:
    admin = await make_user(role="admin")
    google_admin = await make_user(role="admin", password=None)
    await db.users.update_one({"_id": admin.id}, {"$set": {"authProvider": "local+google"}})
    await db.users.update_one({"_id": google_admin.id}, {"$set": {"authProvider": "google"}})
    before = await _snap(db, admin)
    for a, email in ((admin, f"  {admin.email.upper()}  "), (google_admin, google_admin.email)):
        who = {"username": f" {a.username} ", "email": email}
        for url, body in ((V, who), (R, _reset(who))):
            r = await client.post(url, json=body)
            assert r.status_code == 400
            assert r.json()["detail"] == "Username and email do not match our records."
    assert await _snap(db, admin) == before


async def test_normal_user_forgot_password_still_works(
    client: Any, db: Any, make_user: Any
) -> None:
    u = await make_user()
    who = {"username": u.username, "email": f" {u.email.upper()} "}
    assert (await client.post(V, json=who)).json() == {"verified": True}
    assert (await client.post(R, json=_reset(who))).status_code == 200
    doc = await db.users.find_one({"_id": u.id})
    assert verify_password(NEW, doc["passwordHash"]) and doc["tokenVersion"] == 1


async def test_admin_change_password_rules(client: Any, db: Any, make_user: Any) -> None:
    admin = await make_user(role="admin")
    other = await make_user(role="admin")
    other_before = await _snap(db, other)
    body = {"currentPassword": admin.password, "newPassword": NEW, "confirmNewPassword": NEW}
    url = "/api/auth/change-password"
    assert (await client.post(url, json=body)).status_code == 401  # no token
    wrong = await client.post(
        url, headers=admin.headers, json={**body, "currentPassword": "Wr0ng!pass"}
    )
    assert wrong.status_code == 400
    assert (await _snap(db, admin))[1] == 0
    # an id in the body/query is ignored: it only ever touches the caller
    sneaky = {**body, "id": str(other.id), "userId": str(other.id)}
    ok = await client.post(f"{url}?userId={other.id}", headers=admin.headers, json=sneaky)
    assert ok.status_code == 200
    doc = await db.users.find_one({"_id": admin.id})
    assert verify_password(NEW, doc["passwordHash"]) and doc["tokenVersion"] == 1
    assert await _snap(db, other) == other_before
    assert (await client.get("/api/auth/me", headers=admin.headers)).status_code == 401  # old token
