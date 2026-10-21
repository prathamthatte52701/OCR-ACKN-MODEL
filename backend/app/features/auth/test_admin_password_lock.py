"""An admin's password changes only via their own change-password (or the reset script)."""

from typing import Any

from app.core.security import verify_password

NEW = "Nw8#kLp2!Tz9"


async def _snap(db: Any, acct: Any) -> tuple:
    u = await db.users.find_one({"_id": acct.id})
    return u["passwordHash"], u["tokenVersion"]


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
