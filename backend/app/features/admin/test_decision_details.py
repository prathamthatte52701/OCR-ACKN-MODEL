"""Approve / reject / revoke now record WHAT was decided, WHEN and WHY, and the login 403 shows it
(only after the password is verified). Runs on the *_test database only (conftest.py)."""

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest


async def _login(client: Any, u: Any, password: str | None = None) -> Any:
    return await client.post(
        "/api/auth/login", json={"email": u.email, "password": password or u.password}
    )


async def _reject(client: Any, admin: Any, u: Any, body: Any = None) -> Any:
    kwargs: dict[str, Any] = {"headers": admin.headers}
    if body is not None:
        kwargs["json"] = body
    return await client.post(f"/api/admin/users/{u.id}/reject", **kwargs)


async def _approve(client: Any, admin: Any, u: Any) -> Any:
    return await client.post(f"/api/admin/users/{u.id}/approve", headers=admin.headers)


async def test_reject_with_reason_is_stored_and_shown_on_login(
    client: Any, make_user: Any, db: Any
) -> None:
    admin, u = await make_user(role="admin"), await make_user(status="pending")
    r = await _reject(client, admin, u, {"reason": "  Not an employee  "})
    assert r.status_code == 200
    body = r.json()["user"]
    assert body["decision"] == "rejected" and body["decisionReason"] == "Not an employee"
    assert body["decidedAt"] is not None
    doc = await db.users.find_one({"_id": u.id})
    assert doc["decision"] == "rejected" and doc["decisionReason"] == "Not an employee"

    login = await _login(client, u)
    assert login.status_code == 403
    detail = login.json()["detail"]
    assert detail["code"] == "ACCOUNT_REJECTED"
    assert detail["message"] == "Your request was not approved. Contact the admin."
    assert detail["reason"] == "Not an employee"
    assert detail["requestedAt"].endswith("Z") and detail["decidedAt"].endswith("Z")
    log = await db.auditlogs.find_one({"action": "user_rejected"})
    assert (
        log["context"]["reason"] == "Not an employee" and log["context"]["decision"] == "rejected"
    )


async def test_pending_login_has_code_and_requested_date_only(client: Any, make_user: Any) -> None:
    u = await make_user(status="pending")
    detail = (await _login(client, u)).json()["detail"]
    assert detail["code"] == "ACCOUNT_PENDING"
    assert detail["message"] == "Waiting for admin approval."
    assert detail["requestedAt"] and detail["decidedAt"] is None and detail["reason"] is None


@pytest.mark.parametrize(
    "body", [None, {}, {"reason": None}, {"reason": ""}, {"reason": "   \n\t "}]
)
async def test_reject_without_a_usable_reason_stores_none(
    client: Any, make_user: Any, db: Any, body: Any
) -> None:
    admin, u = await make_user(role="admin"), await make_user(status="pending")
    assert (await _reject(client, admin, u, body)).status_code == 200
    assert (await db.users.find_one({"_id": u.id}))["decisionReason"] is None
    assert (await _login(client, u)).json()["detail"]["reason"] is None


async def test_reason_length_limit(client: Any, make_user: Any, db: Any) -> None:
    admin = await make_user(role="admin")
    ok = await make_user(status="pending")
    assert (await _reject(client, admin, ok, {"reason": "x" * 300})).status_code == 200
    too_long = await make_user(status="pending")
    r = await _reject(client, admin, too_long, {"reason": "x" * 301})
    assert r.status_code == 422
    assert (await db.users.find_one({"_id": too_long.id}))["status"] == "pending"  # nothing changed
    huge = await make_user(status="pending")
    assert (await _reject(client, admin, huge, {"reason": "x" * 5_000_000})).status_code in (
        413,
        422,
    )


async def test_reason_is_stored_as_safe_plain_text(client: Any, make_user: Any, db: Any) -> None:
    admin, u = await make_user(role="admin"), await make_user(status="pending")
    nasty = "<script>alert(1)</script> नमस्ते\x00 ok\x07\r\nnext\tline"
    assert (await _reject(client, admin, u, {"reason": nasty})).status_code == 200
    stored = (await db.users.find_one({"_id": u.id}))["decisionReason"]
    assert "\x00" not in stored and "\x07" not in stored and "\n" not in stored
    assert "नमस्ते" in stored and "<script>alert(1)</script>" in stored  # kept as inert text
    shown = (await _login(client, u)).json()["detail"]["reason"]
    assert shown == stored


@pytest.mark.parametrize("bad", [["a"], 123, {"a": 1}, True])
async def test_non_string_reason_is_422(client: Any, make_user: Any, db: Any, bad: Any) -> None:
    admin, u = await make_user(role="admin"), await make_user(status="pending")
    r = await _reject(client, admin, u, {"reason": bad})
    assert r.status_code == 422
    assert (await db.users.find_one({"_id": u.id}))["status"] == "pending"


async def test_approve_after_reject_clears_reason_and_first_login_is_just_approved(
    client: Any, make_user: Any, db: Any
) -> None:
    admin, u = await make_user(role="admin"), await make_user(status="pending")
    await _reject(client, admin, u, {"reason": "Wrong email"})
    r = await _approve(client, admin, u)
    body = r.json()["user"]
    assert body["decision"] == "approved" and body["decisionReason"] is None
    assert (await db.users.find_one({"_id": u.id}))["decisionReason"] is None
    first = await _login(client, u)
    assert first.status_code == 200
    data = first.json()
    assert data["justApproved"] is True
    assert data["approvedAt"] and data["approvedAt"].endswith("Z")
    assert "reason" not in first.text.lower()
    assert (await _login(client, u)).json()["justApproved"] is False


async def test_revoking_an_approved_user_gives_the_revoked_code(
    client: Any, make_user: Any
) -> None:
    admin, u = await make_user(role="admin"), await make_user(status="approved")
    r = await _reject(client, admin, u, {"reason": "Left the company"})
    assert r.json()["user"]["decision"] == "revoked"
    detail = (await _login(client, u)).json()["detail"]
    assert detail["code"] == "ACCOUNT_REVOKED" and detail["reason"] == "Left the company"


async def test_legacy_user_without_status_can_be_revoked(client: Any, make_user: Any) -> None:
    admin, u = await make_user(role="admin"), await make_user(status=None)  # pre-gate account
    assert (await _reject(client, admin, u)).json()["user"]["decision"] == "revoked"


async def test_wrong_password_never_reveals_reason_or_dates(client: Any, make_user: Any) -> None:
    admin, u = await make_user(role="admin"), await make_user(status="pending")
    await _reject(client, admin, u, {"reason": "Secret reason"})
    r = await _login(client, u, "Wr0ng!pass9")
    assert r.status_code == 401 and r.json()["detail"] == "Invalid email or password."
    assert "Secret" not in r.text and "decidedAt" not in r.text and "requestedAt" not in r.text
    unknown = await client.post(
        "/api/auth/login", json={"email": "nobody@looptest.local", "password": "Wr0ng!pass9"}
    )
    assert unknown.status_code == 401 and unknown.json() == r.json()


async def test_old_user_document_without_the_new_fields_still_works(
    client: Any, make_user: Any, db: Any
) -> None:
    pending = await make_user(status="pending")
    rejected = await make_user(status="rejected")  # rejected before decision tracking existed
    d1 = (await _login(client, pending)).json()["detail"]
    d2 = (await _login(client, rejected)).json()["detail"]
    assert d1["code"] == "ACCOUNT_PENDING" and d1["decidedAt"] is None and d1["reason"] is None
    assert d2["code"] == "ACCOUNT_REJECTED" and d2["decidedAt"] is None and d2["reason"] is None
    assert d2["requestedAt"]
    await db.users.update_one({"_id": rejected.id}, {"$unset": {"createdAt": ""}})
    assert (await _login(client, rejected)).json()["detail"]["requestedAt"] is None  # no 500


async def test_old_token_of_a_rejected_user_is_401_and_a_gate_hit_is_structured(
    client: Any, make_user: Any, db: Any
) -> None:
    admin, u = await make_user(role="admin"), await make_user(status="approved")
    await _reject(client, admin, u, {"reason": "Because"})
    assert (await client.get("/api/auth/me", headers=u.headers)).status_code == 401  # tokenVersion
    # a status flipped without a tokenVersion bump (e.g. edited in the DB) hits the gate itself
    other = await make_user(status="approved")
    await db.users.update_one(
        {"_id": other.id},
        {"$set": {"status": "rejected", "decision": "rejected", "decisionReason": "Gate"}},
    )
    r = await client.get("/api/auth/me", headers=other.headers)
    assert r.status_code == 403
    assert (
        r.json()["detail"]["code"] == "ACCOUNT_REJECTED" and r.json()["detail"]["reason"] == "Gate"
    )


async def test_only_admins_see_decision_fields_and_nobody_else_gets_them(
    client: Any, make_user: Any
) -> None:
    admin, u = await make_user(role="admin"), await make_user(status="pending")
    await _reject(client, admin, u, {"reason": "Private note"})
    await _approve(client, admin, u)
    listing = (await client.get("/api/admin/users", headers=admin.headers)).json()["users"]
    mine = next(x for x in listing if x["id"] == str(u.id))
    assert mine["decision"] == "approved" and mine["decidedAt"] and mine["decisionReason"] is None
    login = await _login(client, u)  # reject bumped tokenVersion: old token is dead
    fresh = {"Authorization": f"Bearer {login.json()['token']}"}
    me = await client.get("/api/auth/me", headers=fresh)
    assert me.status_code == 200
    assert not {"decision", "decidedAt", "decisionReason", "reason"} & set(me.json()["user"])
    assert "decisionReason" not in login.text and "Private" not in login.text
    assert (await client.get("/api/admin/users", headers=fresh)).status_code == 403


async def test_reason_never_leaks_into_an_approved_users_login_or_me(
    client: Any, make_user: Any
) -> None:
    admin, u = await make_user(role="admin"), await make_user(status="pending")
    await _reject(client, admin, u, {"reason": "Leak check"})
    await _approve(client, admin, u)
    login = await _login(client, u)
    fresh = {"Authorization": f"Bearer {login.json()['token']}"}
    for text in (login.text, (await client.get("/api/auth/me", headers=fresh)).text):
        assert "Leak check" not in text


async def test_permissions_non_admin_admin_target_and_self(client: Any, make_user: Any) -> None:
    user, target = await make_user(), await make_user(status="pending")
    assert (await _reject(client, user, target, {"reason": "x"})).status_code == 403
    admin, other_admin = await make_user(role="admin"), await make_user(role="admin")
    assert (await _reject(client, admin, other_admin, {"reason": "x"})).status_code == 400
    assert (await _reject(client, admin, admin, {"reason": "x"})).status_code == 400
    assert (await client.get("/api/auth/me", headers=other_admin.headers)).status_code == 200


async def test_reject_twice_is_idempotent_and_keeps_revoked(
    client: Any, make_user: Any, db: Any
) -> None:
    admin, u = await make_user(role="admin"), await make_user(status="approved")
    first = await _reject(client, admin, u, {"reason": "one"})
    second = await _reject(client, admin, u, {"reason": "two"})
    assert first.status_code == 200 and second.status_code == 200
    doc = await db.users.find_one({"_id": u.id})
    assert doc["status"] == "rejected" and doc["decision"] == "revoked"  # not downgraded
    assert doc["decisionReason"] == "two"


async def test_two_concurrent_rejects_give_no_500(client: Any, make_user: Any, db: Any) -> None:
    admin = await make_user(role="admin")
    for _ in range(3):
        u = await make_user(status="pending")
        results = await asyncio.gather(
            _reject(client, admin, u, {"reason": "a"}), _reject(client, admin, u, {"reason": "b"})
        )
        assert [r.status_code for r in results] == [200, 200]
        assert (await db.users.find_one({"_id": u.id}))["status"] == "rejected"


async def test_reject_while_the_user_is_logging_in(client: Any, make_user: Any) -> None:
    admin = await make_user(role="admin")
    for _ in range(3):
        u = await make_user(status="approved")
        login, rej = await asyncio.gather(
            _login(client, u), _reject(client, admin, u, {"reason": "r"})
        )
        assert rej.status_code == 200 and login.status_code in (200, 403)
        after = await _login(client, u)  # whatever the race gave, the account is locked afterwards
        assert after.status_code == 403 and after.json()["detail"]["code"] == "ACCOUNT_REVOKED"


async def test_decided_at_is_recent_utc(client: Any, make_user: Any, db: Any) -> None:
    admin, u = await make_user(role="admin"), await make_user(status="pending")
    before = datetime.now(UTC).replace(tzinfo=None)
    await _reject(client, admin, u, {"reason": "t"})
    stored = (await db.users.find_one({"_id": u.id}))["decidedAt"]
    assert 0 <= (stored.replace(tzinfo=None) - before).total_seconds() < 30
