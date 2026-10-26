"""Chat access rules: thread isolation, role gates, and the usual account-state refusals."""

from typing import Any

import pytest

from app.features.chat.chat_testkit import BASE, admin_send, assert_created, seed, thread, user_send

PENDING = "Waiting for admin approval."
REJECTED = "Your request was not approved. Contact the admin."

ROUTES = [
    ("GET", "/admins", None),
    ("GET", "/threads", None),
    ("GET", "/messages", None),
    ("GET", "/unread", None),
    ("GET", "/settings", None),
    ("POST", "/messages", {"toAdminId": "000000000000000000000000", "text": "x"}),
]


async def _call(client: Any, who: Any, method: str, path: str, body: Any) -> Any:
    return await client.request(method, BASE + path, headers=who.headers, json=body)


async def test_user_cannot_read_another_users_thread(client: Any, make_user: Any, db: Any) -> None:
    a, b, adm = await make_user(), await make_user(), await make_user(role="admin")
    await seed(db, b, "b-secret", to_admin=adm)
    r = await thread(client, a, b)
    assert r.status_code == 403
    assert "b-secret" not in r.text
    own = await thread(client, a)
    assert own.status_code == 200 and own.json()["messages"] == []


async def test_user_passing_own_user_id_reads_own_thread(
    client: Any, make_user: Any, db: Any
) -> None:
    a, adm = await make_user(), await make_user(role="admin")
    await seed(db, a, "mine", to_admin=adm)
    r = await thread(client, a, a)
    assert r.status_code == 200 and [m["text"] for m in r.json()["messages"]] == ["mine"]


async def test_user_cannot_write_to_a_non_admin(client: Any, make_user: Any, db: Any) -> None:
    a, b = await make_user(), await make_user()
    r = await user_send(client, a, b, "hi")
    assert r.status_code in (400, 404, 422)
    assert await db.chatmessages.count_documents({}) == 0


async def test_user_cannot_send_as_or_into_others_via_user_id(
    client: Any, make_user: Any, db: Any
) -> None:
    a, b, adm = await make_user(), await make_user(), await make_user(role="admin")
    r = await client.post(
        f"{BASE}/messages",
        headers=a.headers,
        json={"userId": str(b.id), "toAdminId": str(adm.id), "text": "spoof"},
    )
    assert r.status_code == 422
    r = await client.post(
        f"{BASE}/messages", headers=a.headers, json={"userId": str(b.id), "text": "spoof"}
    )
    assert r.status_code == 422
    assert await db.chatmessages.count_documents({}) == 0


async def test_admin_cannot_send_with_to_admin_id(client: Any, make_user: Any, db: Any) -> None:
    adm, adm2, u = await make_user(role="admin"), await make_user(role="admin"), await make_user()
    r = await client.post(
        f"{BASE}/messages",
        headers=adm.headers,
        json={"userId": str(u.id), "toAdminId": str(adm2.id), "text": "x"},
    )
    assert r.status_code == 422
    assert await db.chatmessages.count_documents({}) == 0


async def test_admin_cannot_message_another_admin_or_missing_user(
    client: Any, make_user: Any, db: Any
) -> None:
    adm, adm2 = await make_user(role="admin"), await make_user(role="admin")
    assert (await admin_send(client, adm, adm2, "x")).status_code in (400, 404, 422)
    r = await client.post(
        f"{BASE}/messages",
        headers=adm.headers,
        json={"userId": "0" * 24, "text": "x"},
    )
    assert r.status_code in (400, 404, 422)
    assert await db.chatmessages.count_documents({}) == 0


async def test_admin_cannot_message_pending_user(client: Any, make_user: Any, db: Any) -> None:
    adm, u = await make_user(role="admin"), await make_user(status="pending")
    assert (await admin_send(client, adm, u, "x")).status_code in (400, 404, 422)
    assert await db.chatmessages.count_documents({}) == 0


async def test_user_cannot_message_pending_admin(client: Any, make_user: Any) -> None:
    adm, u = await make_user(role="admin", status="pending"), await make_user()
    assert (await user_send(client, u, adm, "x")).status_code in (400, 404, 422)


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/threads", None),
        ("POST", "/clear", {"userId": "0" * 24, "olderThan": "all", "dryRun": True}),
        (
            "POST",
            "/clear-all",
            {"password": "x", "confirm": "DELETE", "dryRun": True},
        ),
    ],
)
async def test_user_gets_403_on_admin_only_endpoints(
    client: Any, make_user: Any, method: str, path: str, body: Any
) -> None:
    u = await make_user()
    assert (await _call(client, u, method, path, body)).status_code == 403


async def test_admin_gets_403_on_user_only_admins_list(client: Any, make_user: Any) -> None:
    adm = await make_user(role="admin")
    assert (await client.get(f"{BASE}/admins", headers=adm.headers)).status_code == 403


async def test_admin_messages_requires_user_id(client: Any, make_user: Any) -> None:
    adm = await make_user(role="admin")
    assert (await thread(client, adm)).status_code == 422


async def test_admin_endpoints_work_for_both_admins(client: Any, make_user: Any, db: Any) -> None:
    a1, a2, u = await make_user(role="admin"), await make_user(role="admin"), await make_user()
    await seed(db, u, "ping", to_admin=a1)
    for adm in (a1, a2):
        r = await client.get(f"{BASE}/threads", headers=adm.headers)
        assert r.status_code == 200
        assert [t["userId"] for t in r.json()] == [str(u.id)]
        assert (await thread(client, adm, u)).status_code == 200
        assert (await client.get(f"{BASE}/unread", headers=adm.headers)).status_code == 200
        assert_created(await admin_send(client, adm, u, f"from {adm.id}"))


async def test_user_sees_approved_admins_only(client: Any, make_user: Any) -> None:
    a1 = await make_user(role="admin", username="adminone")
    await make_user(role="admin", status="pending")
    await make_user(role="admin", status="rejected")
    u = await make_user()
    r = await client.get(f"{BASE}/admins", headers=u.headers)
    assert r.status_code == 200
    assert [x["id"] for x in r.json()] == [str(a1.id)]
    assert set(r.json()[0]) == {"id", "name"}


@pytest.mark.parametrize("method,path,body", ROUTES)
async def test_pending_user_refused(
    client: Any, make_user: Any, method: str, path: str, body: Any
) -> None:
    u = await make_user(status="pending")
    r = await _call(client, u, method, path, body)
    assert r.status_code == 403 and r.json()["detail"]["message"] == PENDING


@pytest.mark.parametrize("method,path,body", ROUTES)
async def test_rejected_user_refused(
    client: Any, make_user: Any, method: str, path: str, body: Any
) -> None:
    u = await make_user(status="rejected")
    r = await _call(client, u, method, path, body)
    assert r.status_code == 403 and r.json()["detail"]["message"] == REJECTED


@pytest.mark.parametrize("method,path,body", ROUTES)
async def test_revoked_token_refused(
    client: Any, make_user: Any, db: Any, method: str, path: str, body: Any
) -> None:
    u = await make_user()
    await db.users.update_one({"_id": u.id}, {"$inc": {"tokenVersion": 1}})
    assert (await _call(client, u, method, path, body)).status_code == 401


@pytest.mark.parametrize("method,path,body", ROUTES)
async def test_no_token_refused(client: Any, method: str, path: str, body: Any) -> None:
    r = await client.request(method, BASE + path, json=body)
    assert r.status_code in (401, 403)


@pytest.mark.parametrize("method,path,body", ROUTES)
async def test_must_change_password_gate(
    client: Any, make_user: Any, db: Any, method: str, path: str, body: Any
) -> None:
    u = await make_user()
    await db.users.update_one({"_id": u.id}, {"$set": {"mustChangePassword": True}})
    r = await _call(client, u, method, path, body)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "PASSWORD_CHANGE_REQUIRED"


async def test_user_cannot_edit_or_read_others_via_wrong_role_routes(
    client: Any, make_user: Any, db: Any
) -> None:
    """Admin-only POST /read body (userId) is not usable by a user to touch another thread."""
    a, b, adm = await make_user(), await make_user(), await make_user(role="admin")
    mid = await seed(db, b, "to b", sender=adm, role="admin")
    r = await client.post(
        f"{BASE}/read", headers=a.headers, json={"userId": str(b.id), "upToId": str(mid)}
    )
    assert r.status_code == 403
    assert (await db.chatmessages.find_one({"_id": mid}))["readAt"] is None
