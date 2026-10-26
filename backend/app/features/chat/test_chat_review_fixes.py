"""Fixes that came out of the independent review of the chat backend."""

from datetime import UTC, datetime, timedelta
from typing import Any

from app.features.chat import chat_testkit as kit
from app.features.chat.chat_testkit import BASE, admin_send, limiter_on, seed, thread, user_send

__all__ = ["limiter_on"]  # pytest fixture re-exported for this module


async def test_lowercase_bearer_scheme_cannot_multiply_the_send_limit(
    client: Any, make_user: Any, limiter_on: None
) -> None:
    u, adm = await make_user(), await make_user(role="admin")
    token = u.headers["Authorization"].split(" ", 1)[1]
    schemes = ["Bearer", "bearer", "BEARER", "bEarer"]
    for i in range(60):
        headers = {"Authorization": f"{schemes[i % 4]} {token}"}
        r = await client.post(
            f"{BASE}/messages", headers=headers, json={"toAdminId": str(adm.id), "text": f"m{i}"}
        )
        assert r.status_code == 201, (i, r.text)
    r = await client.post(
        f"{BASE}/messages",
        headers={"Authorization": f"bearer {token}"},
        json={"toAdminId": str(adm.id), "text": "one too many"},
    )
    assert r.status_code == 429


async def test_since_never_skips_changes_when_more_than_limit_changed(
    client: Any, make_user: Any, db: Any
) -> None:
    u, adm = await make_user(), await make_user(role="admin")
    base = kit.ms_now() - timedelta(minutes=5)
    ids = []
    for i in range(5):
        ids.append(
            str(await seed(db, u, f"m{i}", to_admin=adm, created=base + timedelta(seconds=i)))
        )
    since = (base - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    seen: list[str] = []
    for _ in range(10):
        page = (await thread(client, u, since=since, limit=2)).json()
        seen += [m["id"] for m in page["messages"]]
        assert len(page["messages"]) <= 2
        if not page["hasMore"]:
            break
        since = page["nextSince"]
    assert sorted(set(seen)) == sorted(ids)


async def test_next_since_is_a_safe_look_back_not_serverTime(client: Any, make_user: Any) -> None:
    u = await make_user()
    body = (await thread(client, u)).json()
    server = datetime.fromisoformat(body["serverTime"].replace("Z", "+00:00"))
    nxt = datetime.fromisoformat(body["nextSince"].replace("Z", "+00:00"))
    assert body["hasMore"] is False and body["threadCount"] == 0
    assert timedelta(seconds=1) < server - nxt < timedelta(seconds=10)


async def test_has_more_and_thread_count_follow_the_thread(
    client: Any, make_user: Any, db: Any
) -> None:
    u, adm = await make_user(), await make_user(role="admin")
    for i in range(3):
        await seed(db, u, f"m{i}", to_admin=adm, created=kit.minutes_ago(10 - i))
    page = (await thread(client, u, limit=2)).json()
    assert page["hasMore"] is True and page["threadCount"] == 3 and len(page["messages"]) == 2
    await db.chatmessages.delete_many({"threadUserId": u.id})
    assert (await thread(client, u)).json()["threadCount"] == 0


async def test_unread_badge_ignores_threads_the_admin_cannot_open(
    client: Any, make_user: Any, db: Any
) -> None:
    adm = await make_user(role="admin")
    good, bad = await make_user(), await make_user()
    await seed(db, good, "hi", to_admin=adm)
    await seed(db, bad, "hello", to_admin=adm)
    await db.users.update_one({"_id": bad.id}, {"$set": {"status": "rejected"}})
    r = await client.get(f"{BASE}/unread", headers=adm.headers)
    assert r.json()["count"] == 1
    assert [x["userId"] for x in r.json()["byUser"]] == [str(good.id)]


async def test_extreme_since_value_is_a_422_not_a_500(client: Any, make_user: Any) -> None:
    u = await make_user()
    r = await thread(client, u, since="0001-01-01T00:00:00+05:00")
    assert r.status_code == 422


async def test_editable_until_only_on_own_messages(client: Any, make_user: Any, db: Any) -> None:
    u, adm = await make_user(), await make_user(role="admin")
    created = kit.ms_now() - timedelta(minutes=2)
    await seed(db, u, "mine", to_admin=adm, created=created)
    await seed(db, u, "theirs", sender=adm, role="admin", created=created + timedelta(seconds=1))
    msgs = (await thread(client, u)).json()["messages"]
    mine = next(m for m in msgs if m["text"] == "mine")
    theirs = next(m for m in msgs if m["text"] == "theirs")
    until = datetime.fromisoformat(mine["editableUntil"].replace("Z", "+00:00"))
    assert until == created.astimezone(UTC) + timedelta(minutes=15)
    assert theirs["editableUntil"] is None


async def test_reply_and_send_helpers_still_work(client: Any, make_user: Any) -> None:
    u, adm = await make_user(), await make_user(role="admin")
    assert (await user_send(client, u, adm, "q")).status_code == 201
    assert (await admin_send(client, adm, u, "a")).status_code == 201
