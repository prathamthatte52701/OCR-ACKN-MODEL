"""POST /read needs `upToId`: only messages at or before it (by createdAt, _id) are marked."""

from datetime import timedelta
from typing import Any

import pytest
from bson import ObjectId

from app.features.chat.chat_testkit import BASE, ms_now, seed


async def _read(client: Any, who: Any, up_to: Any, thread_user: Any = None) -> Any:
    body: dict[str, Any] = {"upToId": up_to if isinstance(up_to, (dict, str)) else str(up_to)}
    if thread_user is not None:
        body["userId"] = str(thread_user.id)
    return await client.post(f"{BASE}/read", headers=who.headers, json=body)


async def _unread(client: Any, who: Any) -> Any:
    return (await client.get(f"{BASE}/unread", headers=who.headers)).json()


async def test_user_newer_message_stays_unread(client: Any, make_user: Any, db: Any) -> None:
    u, a = await make_user(), await make_user(role="admin")
    t = ms_now()
    seen = await seed(db, u, "seen", sender=a, role="admin", created=t - timedelta(seconds=2))
    await seed(db, u, "late", sender=a, role="admin", created=t)
    r = await _read(client, u, seen)
    assert r.status_code == 200 and r.json() == {"marked": 1}
    assert (await _unread(client, u)) == {"count": 1}
    assert (await _read(client, u, seen)).json() == {"marked": 0}  # idempotent


async def test_admin_newer_message_stays_unread_in_unread_and_threads(
    client: Any, make_user: Any, db: Any
) -> None:
    u, a = await make_user(), await make_user(role="admin")
    t = ms_now()
    seen = await seed(db, u, "seen", to_admin=a, created=t - timedelta(seconds=2))
    await seed(db, u, "late", to_admin=a, created=t)
    assert (await _read(client, a, seen, u)).json() == {"marked": 1}
    assert (await _unread(client, a))["byUser"] == [{"userId": str(u.id), "count": 1}]
    threads = (await client.get(f"{BASE}/threads", headers=a.headers)).json()
    assert [x["unreadCount"] for x in threads] == [1]
    assert (await _read(client, a, seen, u)).json() == {"marked": 0}


async def test_same_created_at_tiebreaks_on_id(client: Any, make_user: Any, db: Any) -> None:
    u, a = await make_user(), await make_user(role="admin")
    t = ms_now()
    lo = await seed(db, u, "lo", sender=a, role="admin", created=t)
    hi = await seed(db, u, "hi", sender=a, role="admin", created=t)
    assert lo < hi
    assert (await _read(client, u, lo)).json() == {"marked": 1}
    assert (await db.chatmessages.find_one({"_id": hi}))["readAt"] is None
    assert (await _read(client, u, hi)).json() == {"marked": 1}
    # admin side, fresh pair
    lo2 = await seed(db, u, "lo2", to_admin=a, created=t)
    hi2 = await seed(db, u, "hi2", to_admin=a, created=t)
    assert (await _read(client, a, lo2, u)).json() == {"marked": 1}
    assert (await db.chatmessages.find_one({"_id": hi2}))["readAt"] is None
    assert (await _read(client, a, hi2, u)).json() == {"marked": 1}


async def test_up_to_id_from_another_thread_or_missing_is_404(
    client: Any, make_user: Any, db: Any
) -> None:
    u, v, a = await make_user(), await make_user(), await make_user(role="admin")
    await seed(db, u, "mine", sender=a, role="admin")
    other = await seed(db, v, "theirs", sender=a, role="admin")
    for r in (
        await _read(client, u, other),
        await _read(client, u, ObjectId()),
        await _read(client, a, other, u),
        await _read(client, a, ObjectId(), u),
    ):
        assert r.status_code == 404 and r.json()["detail"] == "Message not found."


@pytest.mark.parametrize("role", ["user", "admin"])
async def test_missing_or_invalid_up_to_id_is_422(
    client: Any, make_user: Any, db: Any, role: str
) -> None:
    u, a = await make_user(), await make_user(role="admin")
    who = a if role == "admin" else u
    extra = {"userId": str(u.id)} if role == "admin" else {}
    for body in (
        extra,
        {**extra, "upToId": "bad"},
        {**extra, "upToId": {"$ne": ""}},
        {**extra, "upToId": None},
        {**extra, "upToId": 5},
    ):
        r = await client.post(f"{BASE}/read", headers=who.headers, json=body)
        assert r.status_code == 422, body
    assert (await client.post(f"{BASE}/read", headers=who.headers)).status_code == 422


async def test_admin_up_to_does_not_touch_other_admins_messages(
    client: Any, make_user: Any, db: Any
) -> None:
    u, a, b = await make_user(), await make_user(role="admin"), await make_user(role="admin")
    t = ms_now()
    for_a = await seed(db, u, "toA", to_admin=a, created=t - timedelta(seconds=2))
    for_b = await seed(db, u, "toB", to_admin=b, created=t - timedelta(seconds=1))
    last = await seed(db, u, "toA2", to_admin=a, created=t)
    assert (await _read(client, a, last, u)).json() == {"marked": 2}
    assert (await db.chatmessages.find_one({"_id": for_b}))["readAt"] is None
    assert (await db.chatmessages.find_one({"_id": for_a}))["readAt"] is not None


async def test_user_naming_another_thread_is_403(client: Any, make_user: Any, db: Any) -> None:
    u, v, a = await make_user(), await make_user(), await make_user(role="admin")
    mid = await seed(db, v, "to v", sender=a, role="admin")
    r = await _read(client, u, mid, v)
    assert r.status_code == 403
    assert (await db.chatmessages.find_one({"_id": mid}))["readAt"] is None
    assert (await _read(client, u, ObjectId(), u)).status_code == 404  # own id is accepted


async def test_unknown_extra_field_still_rejected(client: Any, make_user: Any, db: Any) -> None:
    u, a = await make_user(), await make_user(role="admin")
    mid = await seed(db, u, "x", sender=a, role="admin")
    r = await client.post(
        f"{BASE}/read", headers=u.headers, json={"upToId": str(mid), "toAdminId": "x"}
    )
    assert r.status_code == 422
