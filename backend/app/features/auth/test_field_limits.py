"""T12: oversize auth fields are rejected at parse time (422), never processed."""

from typing import Any

BIG = "x" * 5000


async def test_signup_oversize_fields_422(client: Any, new_password: str) -> None:
    ok = {"username": "okname", "email": "ok@looptest.local", "password": new_password}
    for field, value in [("username", BIG), ("email", BIG + "@x.com"), ("password", BIG)]:
        r = await client.post("/api/auth/signup", json={**ok, field: value})
        assert r.status_code == 422, field


async def test_login_oversize_fields_422(client: Any) -> None:
    for body in (
        {"email": BIG + "@x.com", "password": "Abc!1234"},
        {"email": "a@b.co", "password": BIG},
    ):
        assert (await client.post("/api/auth/login", json=body)).status_code == 422


async def test_google_token_and_forgot_password_oversize_422(client: Any) -> None:
    assert (await client.post("/api/auth/google", json={"idToken": BIG * 2})).status_code == 422
    r = await client.post(
        "/api/auth/forgot-password/verify", json={"username": BIG, "email": "a@b.co"}
    )
    assert r.status_code == 422
    r = await client.post(
        "/api/auth/forgot-password/reset",
        json={"username": "u", "email": "a@b.co", "newPassword": BIG, "confirmNewPassword": BIG},
    )
    assert r.status_code == 422


async def test_change_password_and_profile_oversize_422(client: Any, make_user: Any) -> None:
    u = await make_user()
    r = await client.post(
        "/api/auth/change-password",
        headers=u.headers,
        json={
            "currentPassword": BIG,
            "newPassword": "Nw8#kLp2!Tz9",
            "confirmNewPassword": "Nw8#kLp2!Tz9",
        },
    )
    assert r.status_code == 422
    assert (
        await client.patch("/api/auth/me", headers=u.headers, json={"username": BIG})
    ).status_code == 422


async def test_admin_user_update_oversize_422(client: Any, make_user: Any) -> None:
    admin, u = await make_user(role="admin"), await make_user()
    r = await client.patch(
        f"/api/admin/users/{u.id}", headers=admin.headers, json={"username": BIG}
    )
    assert r.status_code == 422


async def test_valid_boundary_values_still_accepted(client: Any, make_user: Any) -> None:
    u = await make_user()
    r = await client.post("/api/auth/login", json={"email": u.email, "password": u.password})
    assert r.status_code == 200
    # 128-char password is accepted by the schema and answered 401 (not 422/500)
    r = await client.post("/api/auth/login", json={"email": u.email, "password": "A" * 128})
    assert r.status_code == 401
    # 65-char new password passes the schema and gets the friendly 400 from the validator
    r = await client.post(
        "/api/auth/signup",
        json={"username": "bound", "email": "bound@looptest.local", "password": "Xq7!" * 16 + "a"},
    )
    assert r.status_code == 400
