"""T11 through the real endpoints: signup, change-password, forgot-password."""

from typing import Any


async def test_signup_rejects_common_and_identity_passwords(client: Any) -> None:
    base = {"username": "tester", "email": "tester@looptest.local"}
    for pw in ("Password1!", "Welcome@123", "Zq9!tester!Xk77"):
        r = await client.post("/api/auth/signup", json={**base, "password": pw})
        assert r.status_code == 400, pw


async def test_signup_accepts_64_char_password_and_login_works(client: Any, db: Any) -> None:
    pw = ("Xq7!mZv#4Lp2" * 6)[:64]
    r = await client.post(
        "/api/auth/signup",
        json={"username": "longpw", "email": "longpw@looptest.local", "password": pw},
    )
    assert r.status_code == 201
    await db.users.update_one({"email": "longpw@looptest.local"}, {"$set": {"status": "approved"}})
    r = await client.post(
        "/api/auth/login", json={"email": "longpw@looptest.local", "password": pw}
    )
    assert r.status_code == 200


async def test_signup_rejects_65_chars_and_multibyte_overflow(client: Any) -> None:
    base = {"username": "tester", "email": "t2@looptest.local"}
    assert (
        await client.post("/api/auth/signup", json={**base, "password": "Xq7!" * 16 + "a"})
    ).status_code == 400
    assert (
        await client.post("/api/auth/signup", json={**base, "password": "Aa1!" + "é" * 40})
    ).status_code == 400


async def test_change_password_applies_rules_and_keeps_old_password_valid_for_login(
    client: Any, make_user: Any
) -> None:
    u = await make_user()
    bad = await client.post(
        "/api/auth/change-password",
        headers=u.headers,
        json={
            "currentPassword": u.password,
            "newPassword": "Password1!",
            "confirmNewPassword": "Password1!",
        },
    )
    assert bad.status_code == 400
    # existing (legacy-style) password still logs in: rules are for NEW passwords only
    ok = await client.post("/api/auth/login", json={"email": u.email, "password": u.password})
    assert ok.status_code == 200
    good = await client.post(
        "/api/auth/change-password",
        headers=u.headers,
        json={
            "currentPassword": u.password,
            "newPassword": "Nw8#kLp2!Tz9",
            "confirmNewPassword": "Nw8#kLp2!Tz9",
        },
    )
    assert good.status_code == 200


async def test_forgot_password_reset_applies_rules(client: Any, make_user: Any) -> None:
    u = await make_user()
    payload = {"username": u.username, "email": u.email}
    weak = await client.post(
        "/api/auth/forgot-password/reset",
        json={**payload, "newPassword": "Qwerty!2345", "confirmNewPassword": "Qwerty!2345"},
    )
    assert weak.status_code == 400
    ident = await client.post(
        "/api/auth/forgot-password/reset",
        json={
            **payload,
            "newPassword": f"Zq9!{u.username}!X",
            "confirmNewPassword": f"Zq9!{u.username}!X",
        },
    )
    assert ident.status_code == 400
    ok = await client.post(
        "/api/auth/forgot-password/reset",
        json={**payload, "newPassword": "Nw8#kLp2!Tz9", "confirmNewPassword": "Nw8#kLp2!Tz9"},
    )
    assert ok.status_code == 200
