"""T3: admin approve / reject / revoke endpoints + status filter."""

from typing import Any

REJECTED = "Your request was not approved. Contact the admin."


async def _login(client: Any, u: Any) -> Any:
    return await client.post("/api/auth/login", json={"email": u.email, "password": u.password})


async def test_list_users_status_filter_and_pending_count(client: Any, make_user: Any) -> None:
    admin = await make_user(role="admin")
    await make_user(status="pending")
    await make_user(status="pending")
    await make_user(status="rejected")
    await make_user(status=None)  # legacy => approved
    r = await client.get("/api/admin/users?status=pending", headers=admin.headers)
    assert r.status_code == 200
    body = r.json()
    assert body["totalUsers"] == 2 and body["pendingCount"] == 2
    assert all(u["status"] == "pending" for u in body["users"])
    approved = (await client.get("/api/admin/users?status=approved", headers=admin.headers)).json()
    assert approved["totalUsers"] == 2  # admin + legacy user
    bad = await client.get("/api/admin/users?status=bogus", headers=admin.headers)
    assert bad.status_code == 422


async def test_approve_lets_user_in(client: Any, make_user: Any, db: Any) -> None:
    admin = await make_user(role="admin")
    u = await make_user(status="pending")
    assert (await _login(client, u)).status_code == 403
    r = await client.post(f"/api/admin/users/{u.id}/approve", headers=admin.headers)
    assert r.status_code == 200 and r.json()["user"]["status"] == "approved"
    assert (await _login(client, u)).status_code == 200
    log = await db.auditlogs.find_one({"action": "user_approved"})
    assert log and log["userId"] == admin.id and log["context"]["targetUserId"] == str(u.id)


async def test_reject_revokes_existing_token(client: Any, make_user: Any, db: Any) -> None:
    admin = await make_user(role="admin")
    u = await make_user(status="approved")
    assert (await client.get("/api/auth/me", headers=u.headers)).status_code == 200
    r = await client.post(f"/api/admin/users/{u.id}/reject", headers=admin.headers)
    assert r.status_code == 200 and r.json()["user"]["status"] == "rejected"
    # old token: tokenVersion bumped => 401 (revoked); fresh login => 403 rejected message
    assert (await client.get("/api/auth/me", headers=u.headers)).status_code == 401
    login = await _login(client, u)
    assert login.status_code == 403 and login.json()["detail"] == REJECTED
    assert await db.auditlogs.count_documents({"action": "user_rejected"}) == 1


async def test_admins_and_self_cannot_be_rejected(client: Any, make_user: Any) -> None:
    admin = await make_user(role="admin")
    other_admin = await make_user(role="admin")
    r = await client.post(f"/api/admin/users/{admin.id}/reject", headers=admin.headers)
    assert r.status_code == 400
    r = await client.post(f"/api/admin/users/{other_admin.id}/reject", headers=admin.headers)
    assert r.status_code == 400
    assert (await client.get("/api/auth/me", headers=other_admin.headers)).status_code == 200


async def test_reapprove_rejected_and_delete(client: Any, make_user: Any, db: Any) -> None:
    admin = await make_user(role="admin")
    u = await make_user(status="rejected")
    r = await client.post(f"/api/admin/users/{u.id}/approve", headers=admin.headers)
    assert r.status_code == 200
    r = await client.delete(f"/api/admin/users/{u.id}", headers=admin.headers)
    assert r.status_code == 200 and await db.users.count_documents({"_id": u.id}) == 0


async def test_rejected_email_cannot_resignup(
    client: Any, make_user: Any, new_password: str
) -> None:
    u = await make_user(status="rejected")
    r = await client.post(
        "/api/auth/signup",
        json={"username": "again", "email": u.email, "password": new_password},
    )
    assert r.status_code == 400


async def test_non_admin_cannot_use_approval_routes(client: Any, make_user: Any) -> None:
    user = await make_user()
    target = await make_user(status="pending")
    for action in ("approve", "reject"):
        r = await client.post(f"/api/admin/users/{target.id}/{action}", headers=user.headers)
        assert r.status_code == 403
    listing = await client.get("/api/admin/users?status=pending", headers=user.headers)
    assert listing.status_code == 403


async def test_unknown_user_and_bad_id(client: Any, make_user: Any) -> None:
    admin = await make_user(role="admin")
    zero = "000000000000000000000000"
    r = await client.post(f"/api/admin/users/{zero}/approve", headers=admin.headers)
    assert r.status_code == 404
    r = await client.post("/api/admin/users/not-an-id/approve", headers=admin.headers)
    assert r.status_code == 400
