"""Admin side of password reset: list, temp password, dismiss, races, secrecy,
login/change-password flow, auto-close, and the central forced-change gate.
Written from the contract."""

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import pytest
from bson import ObjectId
from google.oauth2 import id_token as google_id_token
from loguru import logger

REQ = "/api/auth/password-reset-request"
LIST = "/api/admin/password-requests"
TEMP = "Tm9#pQw2!Zx7"
NEWPW = "Nw8#kLp2!Tz9"


async def _open_request(client: Any, user: Any, note: str = "pls") -> None:
    r = await client.post(REQ, json={"email": user.email, "note": note})
    assert r.status_code == 200


async def _rid(db: Any, user: Any) -> str:
    row = await db.passwordresetrequests.find_one({"userId": user.id})
    return str(row["_id"])


async def _set_temp(client: Any, admin: Any, rid: str, pw: str = TEMP) -> Any:
    return await client.post(
        f"{LIST}/{rid}/temp-password", headers=admin.headers, json={"password": pw}
    )


async def _login(client: Any, email: str, pw: str) -> Any:
    return await client.post("/api/auth/login", json={"email": email, "password": pw})


async def _flagged_login(client: Any, db: Any, admin: Any, user: Any) -> dict:
    await _open_request(client, user)
    assert (await _set_temp(client, admin, await _rid(db, user))).status_code == 200
    r = await _login(client, user.email, TEMP)
    assert r.status_code == 200
    return r.json()


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------- list ----------


async def test_list_requires_admin(client: Any, make_user: Any) -> None:
    u = await make_user()
    assert (await client.get(LIST)).status_code == 401
    assert (await client.get(LIST, headers=u.headers)).status_code == 403


async def test_list_default_open_status_all_and_open_count(
    client: Any, db: Any, make_user: Any
) -> None:
    admin = await make_user(role="admin")
    a, b, c = await make_user(), await make_user(), await make_user()
    for u in (a, b, c):
        await _open_request(client, u, note=f"note-{u.username}")
    ra = await _rid(db, a)
    assert (await client.post(f"{LIST}/{ra}/dismiss", headers=admin.headers)).status_code == 200
    body = (await client.get(LIST, headers=admin.headers)).json()
    assert body["openCount"] == 2
    assert {r["userId"] for r in body["requests"]} == {str(b.id), str(c.id)}
    assert all(r["status"] == "open" for r in body["requests"])
    allr = (await client.get(f"{LIST}?status=all", headers=admin.headers)).json()
    assert allr["openCount"] == 2
    assert len(allr["requests"]) == 3
    assert [r["status"] for r in allr["requests"]] == ["open", "open", "dismissed"]
    row = next(r for r in allr["requests"] if r["userId"] == str(a.id))
    keys = ["id", "userId", "username", "email", "note", "status", "createdAt"]
    keys += ["updatedAt", "resolvedAt", "resolution"]
    assert set(row) >= set(keys)
    assert row["id"] == ra and row["resolution"] == "dismissed" and row["resolvedAt"]
    assert row["note"] == f"note-{a.username}" and row["email"] == a.email


async def test_counts_added_to_existing_admin_responses(
    client: Any, db: Any, make_user: Any
) -> None:
    admin = await make_user(role="admin")
    await make_user(status="pending")
    u = await make_user()
    await _open_request(client, u)
    users = (await client.get("/api/admin/users", headers=admin.headers)).json()
    assert users["passwordRequestCount"] == 1
    assert users["pendingCount"] == 1 and "statusCounts" in users


# ---------- temp password ----------


async def test_weak_temp_password_422_string_detail_no_echo(
    client: Any, db: Any, make_user: Any
) -> None:
    admin, u = await make_user(role="admin"), await make_user()
    await _open_request(client, u)
    rid = await _rid(db, u)
    for weak in ("qwerty12345", "short1!", f"Zq9!{u.username}!X"):
        r = await _set_temp(client, admin, rid, weak)
        assert r.status_code == 422
        assert isinstance(r.json()["detail"], str)
        assert weak not in r.text
    row = await db.passwordresetrequests.find_one({"_id": ObjectId(rid)})
    assert row["status"] == "open"
    assert not (await db.users.find_one({"_id": u.id})).get("mustChangePassword")


async def test_strong_temp_password_flow(client: Any, db: Any, make_user: Any) -> None:
    admin, u = await make_user(role="admin"), await make_user()
    await _open_request(client, u)
    rid = await _rid(db, u)
    r = await _set_temp(client, admin, rid)
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert TEMP not in r.text
    row = await db.passwordresetrequests.find_one({"_id": ObjectId(rid)})
    assert row["status"] == "done" and row["resolution"] == "temp_password"
    assert row["resolvedAt"] and row["resolvedBy"] == admin.id
    user = await db.users.find_one({"_id": u.id})
    assert user["mustChangePassword"] is True and user["tokenVersion"] == 1
    assert (await client.get("/api/auth/me", headers=u.headers)).status_code == 401
    assert (await _login(client, u.email, u.password)).status_code == 401
    lg = await _login(client, u.email, TEMP)
    assert lg.status_code == 200 and lg.json()["user"]["mustChangePassword"] is True
    row = await db.passwordresetrequests.find_one({"_id": ObjectId(rid)})
    assert row["resolution"] == "temp_password" and row["status"] == "done"
    logs = await db.auditlogs.find({"action": "PASSWORD_RESET_TEMP_SET"}).to_list(None)
    assert len(logs) == 1 and logs[0]["userId"] == admin.id
    assert str(logs[0]["context"].get("targetUserId")) == str(u.id)


async def test_admin_target_self_and_non_approved_403(client: Any, db: Any, make_user: Any) -> None:
    admin, other_admin = await make_user(role="admin"), await make_user(role="admin")
    pending, rejected = await make_user(), await make_user()
    await db.users.update_one({"_id": pending.id}, {"$set": {"status": "pending"}})
    await db.users.update_one({"_id": rejected.id}, {"$set": {"status": "rejected"}})
    now = datetime.now(UTC)
    rows = []
    for acct in (other_admin, admin, pending, rejected):
        res = await db.passwordresetrequests.insert_one(
            {
                "userId": acct.id,
                "email": acct.email,
                "username": acct.username,
                "note": "",
                "status": "open",
                "resolution": None,
                "createdAt": now,
                "updatedAt": now,
                "resolvedAt": None,
                "resolvedBy": None,
            }
        )
        rows.append(str(res.inserted_id))
    accts = (other_admin, admin, pending, rejected)
    before = {a.id: await db.users.find_one({"_id": a.id}) for a in accts}
    for rid in rows:
        r = await _set_temp(client, admin, rid)
        assert r.status_code == 403, rid
        assert TEMP not in r.text
    for uid, doc in before.items():
        now_doc = await db.users.find_one({"_id": uid})
        assert now_doc["passwordHash"] == doc["passwordHash"]
        assert now_doc["tokenVersion"] == doc["tokenVersion"]
        assert not now_doc.get("mustChangePassword")
    # no half-done state: every request is still open
    assert await db.passwordresetrequests.count_documents({"status": "open"}) == 4


async def test_temp_password_requires_admin_and_404_409(
    client: Any, db: Any, make_user: Any
) -> None:
    admin, u, other = await make_user(role="admin"), await make_user(), await make_user()
    await _open_request(client, u)
    rid = await _rid(db, u)
    anon = await client.post(f"{LIST}/{rid}/temp-password", json={"password": TEMP})
    assert anon.status_code == 401
    r = await client.post(
        f"{LIST}/{rid}/temp-password", headers=other.headers, json={"password": TEMP}
    )
    assert r.status_code == 403
    assert (await _set_temp(client, admin, str(ObjectId()))).status_code == 404
    assert (await _set_temp(client, admin, rid)).status_code == 200
    assert (await _set_temp(client, admin, rid, "Zz8#kLp2!Tq1")).status_code == 409
    assert (await client.post(f"{LIST}/{rid}/dismiss", headers=admin.headers)).status_code == 409


async def test_resolve_race_exactly_one_wins(client: Any, db: Any, make_user: Any) -> None:
    a1, a2, u = await make_user(role="admin"), await make_user(role="admin"), await make_user()
    await _open_request(client, u)
    rid = await _rid(db, u)
    rs = await asyncio.gather(
        _set_temp(client, a1, rid, "Aa1#bcdEfgh9"), _set_temp(client, a2, rid, "Bb2#cdeFghi8")
    )
    assert sorted(r.status_code for r in rs) == [200, 409]
    assert (await db.users.find_one({"_id": u.id}))["tokenVersion"] == 1


async def test_dismiss_then_409_and_404(client: Any, db: Any, make_user: Any) -> None:
    admin, u = await make_user(role="admin"), await make_user()
    await _open_request(client, u)
    rid = await _rid(db, u)
    r = await client.post(f"{LIST}/{rid}/dismiss", headers=admin.headers)
    assert r.status_code == 200 and r.json() == {"ok": True}
    row = await db.passwordresetrequests.find_one({"_id": ObjectId(rid)})
    assert row["status"] == "dismissed" and row["resolution"] == "dismissed"
    assert (await client.post(f"{LIST}/{rid}/dismiss", headers=admin.headers)).status_code == 409
    nf = await client.post(f"{LIST}/{ObjectId()}/dismiss", headers=admin.headers)
    assert nf.status_code == 404
    assert (await client.post(f"{LIST}/{rid}/dismiss", headers=u.headers)).status_code == 403
    assert await db.auditlogs.count_documents({"action": "PASSWORD_RESET_DISMISSED"}) == 1
    await _open_request(client, u)  # a fresh request is possible afterwards
    assert await db.passwordresetrequests.count_documents({"status": "open"}) == 1


async def test_admin_delete_user_removes_requests(client: Any, db: Any, make_user: Any) -> None:
    admin, u, keep = await make_user(role="admin"), await make_user(), await make_user()
    await _open_request(client, u)
    await _open_request(client, keep)
    r = await client.delete(f"/api/admin/users/{u.id}", headers=admin.headers)
    assert r.status_code == 200, r.text
    assert await db.passwordresetrequests.count_documents({"userId": u.id}) == 0
    assert await db.passwordresetrequests.count_documents({"userId": keep.id}) == 1


# ---------- change-password / login lifecycle ----------


async def test_forced_change_password_flow(client: Any, db: Any, make_user: Any) -> None:
    admin, u = await make_user(role="admin"), await make_user()
    tok = (await _flagged_login(client, db, admin, u))["token"]
    h = _bearer(tok)
    me = await client.get("/api/auth/me", headers=h)
    assert me.status_code == 200 and me.json()["user"]["mustChangePassword"] is True
    url = "/api/auth/change-password"

    def body(new: str) -> dict:
        return {"currentPassword": TEMP, "newPassword": new, "confirmNewPassword": new}

    same = await client.post(url, headers=h, json=body(TEMP))
    assert same.status_code == 400 and isinstance(same.json()["detail"], str)
    weak = await client.post(url, headers=h, json=body("qwerty12345"))
    assert weak.status_code in (400, 422)
    assert (await db.users.find_one({"_id": u.id}))["mustChangePassword"] is True
    ok = await client.post(url, headers=h, json=body(NEWPW))
    assert ok.status_code == 200
    data = ok.json()
    assert data["user"]["mustChangePassword"] is False
    assert (await client.get("/api/auth/me", headers=h)).status_code == 401  # old token dead
    assert (await client.get("/api/auth/me", headers=_bearer(data["token"]))).status_code == 200
    user = await db.users.find_one({"_id": u.id})
    assert not user.get("mustChangePassword") and user["tokenVersion"] == 2
    assert (await _login(client, u.email, NEWPW)).json()["user"]["mustChangePassword"] is False
    assert (await _login(client, u.email, TEMP)).status_code == 401
    assert await db.auditlogs.count_documents({"action": "PASSWORD_CHANGED_FORCED"}) == 1
    assert await db.auditlogs.count_documents({"userId": u.id, "action": "password_change"}) == 1


async def test_normal_change_password_rejects_same_password(client: Any, make_user: Any) -> None:
    u = await make_user()
    r = await client.post(
        "/api/auth/change-password",
        headers=u.headers,
        json={
            "currentPassword": u.password,
            "newPassword": u.password,
            "confirmNewPassword": u.password,
        },
    )
    assert r.status_code == 400


async def test_patch_me_returns_must_change_flag(client: Any, make_user: Any) -> None:
    u = await make_user()
    r = await client.patch("/api/auth/me", headers=u.headers, json={"username": "newnm1"})
    assert r.status_code == 200
    assert r.json()["user"]["mustChangePassword"] is False


# ---------- auto-close ----------


async def test_normal_login_closes_open_request(client: Any, db: Any, make_user: Any) -> None:
    u = await make_user()
    await _open_request(client, u)
    assert (await _login(client, u.email, "Wr0ng!passw0rd")).status_code == 401
    assert await db.passwordresetrequests.count_documents({"status": "open"}) == 1
    ok = await _login(client, u.email, u.password)
    assert ok.status_code == 200 and ok.json()["user"]["mustChangePassword"] is False
    row = await db.passwordresetrequests.find_one({"userId": u.id})
    assert row["status"] == "done" and row["resolution"] == "user_logged_in"
    assert row["resolvedAt"] and row["resolvedBy"] is None


async def test_login_without_request_creates_nothing(client: Any, db: Any, make_user: Any) -> None:
    u = await make_user()
    assert (await _login(client, u.email, u.password)).status_code == 200
    assert await db.passwordresetrequests.count_documents({}) == 0


async def test_google_login_keeps_flag_and_does_not_close(
    client: Any, db: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, u = await make_user(role="admin"), await make_user()
    await _flagged_login(client, db, admin, u)
    await db.passwordresetrequests.update_one({"userId": u.id}, {"$set": {"status": "open"}})
    monkeypatch.setattr(
        google_id_token,
        "verify_oauth2_token",
        lambda *_a, **_k: {"email": u.email, "email_verified": True, "sub": "g-flag"},
    )
    r = await client.post("/api/auth/google", json={"idToken": "fake"})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["mustChangePassword"] is True
    assert (await db.users.find_one({"_id": u.id}))["mustChangePassword"] is True
    assert (await db.passwordresetrequests.find_one({"userId": u.id}))["status"] == "open"


# ---------- secrecy ----------


async def test_passwords_never_in_logs_or_audit(client: Any, db: Any, make_user: Any) -> None:
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(str(m)), format="{message}", level="DEBUG")
    try:
        admin, u = await make_user(role="admin"), await make_user()
        await _open_request(client, u, note="my note text")
        rid = await _rid(db, u)
        weak = await _set_temp(client, admin, rid, "qwerty12345")
        assert weak.status_code == 422
        assert (await _set_temp(client, admin, rid)).status_code == 200
        tok = (await _login(client, u.email, TEMP)).json()["token"]
        r = await client.post(
            "/api/auth/change-password",
            headers=_bearer(tok),
            json={"currentPassword": TEMP, "newPassword": NEWPW, "confirmNewPassword": NEWPW},
        )
        assert r.status_code == 200
        assert NEWPW not in weak.text
    finally:
        logger.remove(sink)
    blob = "\n".join(lines)
    audit = json.dumps(await db.auditlogs.find({}).to_list(None), default=str)
    for secret in (TEMP, NEWPW, "qwerty12345", "my note text"):
        assert secret not in blob, secret
        assert secret not in audit, secret


# ---------- the central gate ----------

PUBLIC = {
    ("POST", "/api/auth/signup"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/google"),
    ("POST", "/api/auth/password-reset-request"),
    ("GET", "/api/health"),
    ("GET", "/health"),
}
ALLOWED = {("GET", "/api/auth/me"), ("POST", "/api/auth/change-password")}


def _all_routes() -> list[tuple[str, str]]:
    from app.main import app

    return [(m.upper(), p) for p, ops in app.openapi()["paths"].items() for m in ops]


async def test_every_other_route_is_gated_for_flagged_user(
    client: Any, db: Any, make_user: Any
) -> None:
    admin, u = await make_user(role="admin"), await make_user()
    tok = (await _flagged_login(client, db, admin, u))["token"]
    flagged_admin = await make_user(role="admin")
    await db.users.update_one({"_id": flagged_admin.id}, {"$set": {"mustChangePassword": True}})
    checked = 0
    for method, path in _all_routes():
        if (method, path) in PUBLIC or (method, path) in ALLOWED:
            continue
        filled = path
        while "{" in filled:
            s, e = filled.index("{"), filled.index("}")
            filled = filled[:s] + str(ObjectId()) + filled[e + 1 :]
        for headers in (_bearer(tok), flagged_admin.headers):
            r = await client.request(method, filled, headers=headers, json={})
            assert r.status_code == 403, (method, path, r.status_code)
            detail = r.json()["detail"]
            assert detail["code"] == "PASSWORD_CHANGE_REQUIRED", (method, path)
            assert detail["message"] == "You must set a new password before continuing."
        checked += 1
    assert checked >= 40  # the real route table was walked


async def test_flagged_admin_cannot_use_admin_routes(client: Any, db: Any, make_user: Any) -> None:
    admin = await make_user(role="admin")
    await db.users.update_one({"_id": admin.id}, {"$set": {"mustChangePassword": True}})
    for path in ("/api/admin/users", LIST, "/api/admin/ping"):
        r = await client.get(path, headers=admin.headers)
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "PASSWORD_CHANGE_REQUIRED"


async def test_unflagged_user_not_gated(client: Any, make_user: Any) -> None:
    u = await make_user()
    assert (await client.get("/api/documents", headers=u.headers)).status_code == 200
