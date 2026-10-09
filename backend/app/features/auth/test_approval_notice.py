"""Stage 1: the one-time "you're approved" notice (users.approvalNoticePending ->
TokenResponse.justApproved on the first successful password login)."""

import asyncio
from typing import Any


async def _login(client: Any, u: Any, password: str | None = None) -> Any:
    return await client.post(
        "/api/auth/login", json={"email": u.email, "password": password or u.password}
    )


async def _approve(client: Any, admin: Any, u: Any) -> None:
    r = await client.post(f"/api/admin/users/{u.id}/approve", headers=admin.headers)
    assert r.status_code == 200


async def _reject(client: Any, admin: Any, u: Any) -> None:
    r = await client.post(f"/api/admin/users/{u.id}/reject", headers=admin.headers)
    assert r.status_code == 200


async def test_pending_then_approve_sets_flag_first_login_true_second_false(
    client: Any, make_user: Any, db: Any
) -> None:
    admin, u = await make_user(role="admin"), await make_user(status="pending")
    await _approve(client, admin, u)
    assert (await db.users.find_one({"_id": u.id}))["approvalNoticePending"] is True
    first = await _login(client, u)
    assert first.status_code == 200 and first.json()["justApproved"] is True
    second = await _login(client, u)
    assert second.status_code == 200 and second.json()["justApproved"] is False
    assert (await db.users.find_one({"_id": u.id}))["approvalNoticePending"] is False


async def test_rejected_then_approve_sets_flag(client: Any, make_user: Any) -> None:
    admin, u = await make_user(role="admin"), await make_user(status="rejected")
    await _approve(client, admin, u)
    assert (await _login(client, u)).json()["justApproved"] is True


async def test_approving_an_already_approved_user_sets_no_flag(
    client: Any, make_user: Any, db: Any
) -> None:
    admin, u = await make_user(role="admin"), await make_user(status="approved")
    await _approve(client, admin, u)
    assert not (await db.users.find_one({"_id": u.id})).get("approvalNoticePending")
    assert (await _login(client, u)).json()["justApproved"] is False


async def test_legacy_user_without_status_gets_no_flag(
    client: Any, make_user: Any, db: Any
) -> None:
    admin, u = await make_user(role="admin"), await make_user(status=None)
    await _approve(client, admin, u)  # a no-op for them: missing status already counts as approved
    assert not (await db.users.find_one({"_id": u.id})).get("approvalNoticePending")
    assert (await _login(client, u)).json()["justApproved"] is False


async def test_approve_reject_approve_sets_the_flag_again(
    client: Any, make_user: Any, db: Any
) -> None:
    admin, u = await make_user(role="admin"), await make_user(status="pending")
    await _approve(client, admin, u)
    assert (await _login(client, u)).json()["justApproved"] is True
    assert (await _login(client, u)).json()["justApproved"] is False
    await _reject(client, admin, u)
    assert (await db.users.find_one({"_id": u.id}))["approvalNoticePending"] is False
    await _approve(client, admin, u)
    assert (await _login(client, u)).json()["justApproved"] is True
    assert (await _login(client, u)).json()["justApproved"] is False


async def test_reject_clears_an_unconsumed_flag(client: Any, make_user: Any, db: Any) -> None:
    admin, u = await make_user(role="admin"), await make_user(status="pending")
    await _approve(client, admin, u)
    await _reject(client, admin, u)
    assert (await db.users.find_one({"_id": u.id}))["approvalNoticePending"] is False
    login = await _login(client, u)
    assert login.status_code == 403 and "justApproved" not in login.text


async def test_wrong_password_and_pending_account_never_consume_the_flag(
    client: Any, make_user: Any, db: Any
) -> None:
    admin, u = await make_user(role="admin"), await make_user(status="pending")
    pending_try = await _login(client, u)
    assert pending_try.status_code == 403
    await _approve(client, admin, u)
    for _ in range(3):
        assert (await _login(client, u, "Wr0ng!pass9")).status_code == 401
    assert (await db.users.find_one({"_id": u.id}))["approvalNoticePending"] is True
    assert (await _login(client, u)).json()["justApproved"] is True

    # a flag sitting on a user who is (again) pending is not consumable either
    other = await make_user(status="pending")
    await db.users.update_one({"_id": other.id}, {"$set": {"approvalNoticePending": True}})
    assert (await _login(client, other)).status_code == 403
    assert (await db.users.find_one({"_id": other.id}))["approvalNoticePending"] is True


async def test_two_concurrent_logins_give_exactly_one_true(client: Any, make_user: Any) -> None:
    admin = await make_user(role="admin")
    for _ in range(5):  # repeat: a race would show up as 0 or 2 sometimes
        u = await make_user(status="pending")
        await _approve(client, admin, u)
        results = await asyncio.gather(*[_login(client, u) for _ in range(2)])
        assert all(r.status_code == 200 for r in results)
        assert sorted(r.json()["justApproved"] for r in results) == [False, True]


async def test_flag_never_leaks_in_any_user_payload(client: Any, make_user: Any) -> None:
    admin, u = await make_user(role="admin"), await make_user(status="pending")
    await _approve(client, admin, u)  # flag now set
    me = await client.get("/api/auth/me", headers=u.headers)
    assert "approvalNoticePending" not in me.text and "justApproved" not in me.text
    lst = await client.get("/api/admin/users?limit=50", headers=admin.headers)
    one = await client.get(f"/api/admin/users/{u.id}", headers=admin.headers)
    assert "approvalNoticePending" not in lst.text and "approvalNoticePending" not in one.text
    login = (await _login(client, u)).json()
    assert "approvalNoticePending" not in login["user"] and "approvalNoticePending" not in str(
        login
    )
    assert login["justApproved"] is True  # the transient response field is the only exposure
    after = await client.get("/api/auth/me", headers=u.headers)
    assert "approvalNoticePending" not in after.text


async def test_password_change_and_normal_users_unaffected(client: Any, make_user: Any) -> None:
    u = await make_user()
    login = await _login(client, u)
    assert login.status_code == 200 and login.json()["justApproved"] is False
    change = await client.post(
        "/api/auth/change-password",
        headers=u.headers,
        json={
            "currentPassword": u.password,
            "newPassword": "Nw8#kLp2!Tz9",
            "confirmNewPassword": "Nw8#kLp2!Tz9",
        },
    )
    assert change.status_code == 200 and change.json()["justApproved"] is False
