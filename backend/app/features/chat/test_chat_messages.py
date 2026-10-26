"""Messages: shape, edit window, unread/read semantics, polling by `since`, pagination."""

from datetime import timedelta
from typing import Any

import pytest
from bson import ObjectId

from app.features.chat import chat_testkit as kit
from app.features.chat.chat_testkit import BASE, admin_send, assert_created, seed, thread, user_send

# ----------------------------------------------------------------------- shape


async def test_sent_message_shape_and_names(client: Any, make_user: Any) -> None:
    u = await make_user(username="alice")
    adm = await make_user(role="admin", username="boss")
    m = assert_created(await user_send(client, u, adm, "hello"))
    assert m["text"] == "hello" and m["mine"] is True and m["canEdit"] is True
    assert m["fromId"] == str(u.id) and m["fromRole"] == "user"
    assert m["fromName"] == "alice" and m["toAdminId"] == str(adm.id)
    assert m["toAdminName"] == "boss" and m["editedAt"] is None and m["readAt"] is None
    r = await thread(client, adm, u)
    got = r.json()["messages"][0]
    assert got["mine"] is False and got["canEdit"] is False and got["fromName"] == "alice"
    assert r.json()["serverTime"]


async def test_removed_admin_name_placeholder(client: Any, make_user: Any, db: Any) -> None:
    u = await make_user()
    gone, other = await make_user(role="admin"), await make_user(role="admin")
    await seed(db, u, "q", to_admin=gone)
    await seed(db, u, "a", sender=gone, role="admin")
    await db.users.delete_one({"_id": gone.id})
    msgs = (await thread(client, other, u)).json()["messages"]
    by_text = {m["text"]: m for m in msgs}
    assert by_text["q"]["toAdminName"] == "Removed admin"
    assert by_text["a"]["fromName"] == "Removed admin"


async def test_thread_ordered_ascending(client: Any, make_user: Any, db: Any) -> None:
    u, adm = await make_user(), await make_user(role="admin")
    for i, mins in enumerate((5, 30, 1, 10)):
        await seed(db, u, f"m{i}", to_admin=adm, created=kit.minutes_ago(mins))
    texts = [m["text"] for m in (await thread(client, u)).json()["messages"]]
    assert texts == ["m1", "m3", "m0", "m2"]


async def test_other_admin_still_sees_message_sent_to_admin_a(client: Any, make_user: Any) -> None:
    u, a, b = await make_user(), await make_user(role="admin"), await make_user(role="admin")
    assert_created(await user_send(client, u, a, "for A"))
    assert [m["text"] for m in (await thread(client, b, u)).json()["messages"]] == ["for A"]


# ------------------------------------------------------------------------ edit


async def test_edit_own_message_sets_edited_at(client: Any, make_user: Any) -> None:
    u, adm = await make_user(), await make_user(role="admin")
    mid = assert_created(await user_send(client, u, adm, "old"))["id"]
    r = await client.patch(f"{BASE}/messages/{mid}", headers=u.headers, json={"text": "  new "})
    assert r.status_code == 200, r.text
    m = r.json().get("message", r.json())
    assert m["text"] == "new" and m["editedAt"]
    stored = (await thread(client, u)).json()["messages"][0]
    assert stored["text"] == "new" and stored["editedAt"]


async def test_admin_can_edit_own_reply(client: Any, make_user: Any) -> None:
    u, adm = await make_user(), await make_user(role="admin")
    mid = assert_created(await admin_send(client, adm, u, "old"))["id"]
    r = await client.patch(f"{BASE}/messages/{mid}", headers=adm.headers, json={"text": "new"})
    assert r.status_code == 200


async def test_edit_visible_via_since_polling(client: Any, make_user: Any, db: Any) -> None:
    u, adm = await make_user(), await make_user(role="admin")
    mid = assert_created(await user_send(client, u, adm, "v1"))["id"]
    await db.chatmessages.update_one(
        {"_id": ObjectId(mid)},
        {"$set": {"createdAt": kit.minutes_ago(3), "updatedAt": kit.minutes_ago(3)}},
    )
    later = (kit.ms_now() - timedelta(seconds=1)).isoformat()
    assert (await thread(client, adm, u, since=later)).json()["messages"] == []
    r = await client.patch(f"{BASE}/messages/{mid}", headers=u.headers, json={"text": "v2"})
    assert r.status_code == 200
    got = (await thread(client, adm, u, since=later)).json()["messages"]
    assert [m["text"] for m in got] == ["v2"] and got[0]["editedAt"]


async def test_since_returns_only_updated_at_gte(client: Any, make_user: Any, db: Any) -> None:
    u, adm = await make_user(), await make_user(role="admin")
    await seed(db, u, "old", to_admin=adm, created=kit.minutes_ago(60))
    await seed(db, u, "new", to_admin=adm, created=kit.minutes_ago(1))
    since = kit.minutes_ago(10).isoformat()
    got = (await thread(client, u, since=since)).json()["messages"]
    assert [m["text"] for m in got] == ["new"]


async def test_cannot_edit_others_message(client: Any, make_user: Any, db: Any) -> None:
    u, other, adm = await make_user(), await make_user(), await make_user(role="admin")
    mid = assert_created(await user_send(client, u, adm, "mine"))["id"]
    r = await client.patch(f"{BASE}/messages/{mid}", headers=other.headers, json={"text": "pwn"})
    assert r.status_code in (403, 404)
    r = await client.patch(f"{BASE}/messages/{mid}", headers=adm.headers, json={"text": "pwn"})
    assert r.status_code == 403
    assert (await thread(client, u)).json()["messages"][0]["text"] == "mine"


async def test_admin_cannot_edit_users_message(client: Any, make_user: Any) -> None:
    u, adm = await make_user(), await make_user(role="admin")
    mid = assert_created(await user_send(client, u, adm, "mine"))["id"]
    adm2 = await make_user(role="admin")
    r = await client.patch(f"{BASE}/messages/{mid}", headers=adm2.headers, json={"text": "x"})
    assert r.status_code == 403


@pytest.mark.parametrize("bad", ["abc", "z" * 24, "0" * 23, "0" * 25])
async def test_edit_with_bad_id_rejected(client: Any, make_user: Any, bad: str) -> None:
    u = await make_user()
    r = await client.patch(f"{BASE}/messages/{bad}", headers=u.headers, json={"text": "x"})
    assert r.status_code in (404, 422, 400)


async def test_edit_missing_message_404(client: Any, make_user: Any) -> None:
    u = await make_user()
    r = await client.patch(f"{BASE}/messages/{'a' * 24}", headers=u.headers, json={"text": "x"})
    assert r.status_code in (403, 404)


async def test_edit_text_validation(client: Any, make_user: Any) -> None:
    u, adm = await make_user(), await make_user(role="admin")
    mid = assert_created(await user_send(client, u, adm, "ok"))["id"]
    for bad in ("", "   ", "a" * 1001, "x\x00y", 5, None, {"$ne": ""}, ["a"]):
        r = await client.patch(f"{BASE}/messages/{mid}", headers=u.headers, json={"text": bad})
        assert r.status_code == 422, bad
    r = await client.patch(
        f"{BASE}/messages/{mid}", headers=u.headers, json={"text": "ok2", "fromId": "x"}
    )
    assert r.status_code == 422


async def test_edit_window_exactly_15_minutes_ok_one_microsecond_later_refused(
    client: Any, make_user: Any, db: Any, monkeypatch: Any
) -> None:
    from app.features.chat import service  # lazy: only needed here

    u, adm = await make_user(), await make_user(role="admin")
    created = kit.ms_now()
    mid = await seed(db, u, "t", to_admin=adm, created=created)

    monkeypatch.setattr(service, "utcnow", lambda: created + timedelta(minutes=15))
    ok = await client.patch(f"{BASE}/messages/{mid}", headers=u.headers, json={"text": "in time"})
    assert ok.status_code == 200, ok.text

    mid2 = await seed(db, u, "t2", to_admin=adm, created=created)
    monkeypatch.setattr(service, "utcnow", lambda: created + timedelta(minutes=15, microseconds=1))
    late = await client.patch(f"{BASE}/messages/{mid2}", headers=u.headers, json={"text": "late"})
    assert late.status_code == 403
    assert (await db.chatmessages.find_one({"_id": mid2}))["text"] == "t2"


async def test_can_edit_flag_false_after_window(
    client: Any, make_user: Any, db: Any, monkeypatch: Any
) -> None:
    from app.features.chat import service

    u, adm = await make_user(), await make_user(role="admin")
    created = kit.ms_now()
    await seed(db, u, "t", to_admin=adm, created=created)
    monkeypatch.setattr(service, "utcnow", lambda: created + timedelta(minutes=14))
    assert (await thread(client, u)).json()["messages"][0]["canEdit"] is True
    monkeypatch.setattr(service, "utcnow", lambda: created + timedelta(minutes=16))
    assert (await thread(client, u)).json()["messages"][0]["canEdit"] is False


# ----------------------------------------------------------------- unread/read


async def test_user_message_counts_for_addressed_admin_only(client: Any, make_user: Any) -> None:
    u, a, b = await make_user(), await make_user(role="admin"), await make_user(role="admin")
    assert_created(await user_send(client, u, a, "for A"))
    ra = (await client.get(f"{BASE}/unread", headers=a.headers)).json()
    assert ra["count"] == 1 and ra["byUser"] == [{"userId": str(u.id), "count": 1}]
    rb = (await client.get(f"{BASE}/unread", headers=b.headers)).json()
    assert rb["count"] == 0 and rb["byUser"] == []
    assert [m["text"] for m in (await thread(client, b, u)).json()["messages"]] == ["for A"]


async def test_admin_reply_counts_for_user_and_read_clears(client: Any, make_user: Any) -> None:
    u, a = await make_user(), await make_user(role="admin")
    assert_created(await admin_send(client, a, u, "r1"))
    assert_created(await admin_send(client, a, u, "r2"))
    assert (await client.get(f"{BASE}/unread", headers=u.headers)).json() == {"count": 2}
    r = await client.post(f"{BASE}/read", headers=u.headers)
    assert r.status_code == 200 and r.json() == {"marked": 2}
    assert (await client.get(f"{BASE}/unread", headers=u.headers)).json() == {"count": 0}
    assert (await client.post(f"{BASE}/read", headers=u.headers)).json() == {"marked": 0}
    msgs = (await thread(client, u)).json()["messages"]
    assert all(m["readAt"] for m in msgs)


async def test_own_messages_never_count_as_unread(client: Any, make_user: Any) -> None:
    u, a = await make_user(), await make_user(role="admin")
    assert_created(await user_send(client, u, a, "mine"))
    assert (await client.get(f"{BASE}/unread", headers=u.headers)).json() == {"count": 0}
    assert_created(await admin_send(client, a, u, "mine too"))
    assert (await client.get(f"{BASE}/unread", headers=a.headers)).json()["count"] == 1


async def test_admin_read_marks_only_messages_addressed_to_me(
    client: Any, make_user: Any, db: Any
) -> None:
    u, a, b = await make_user(), await make_user(role="admin"), await make_user(role="admin")
    await seed(db, u, "toA1", to_admin=a)
    await seed(db, u, "toA2", to_admin=a)
    await seed(db, u, "toB", to_admin=b)
    r = await client.post(f"{BASE}/read", headers=b.headers, json={"userId": str(u.id)})
    assert r.json() == {"marked": 1}
    assert (await client.get(f"{BASE}/unread", headers=a.headers)).json()["count"] == 2
    assert (await client.get(f"{BASE}/unread", headers=b.headers)).json()["count"] == 0
    r = await client.post(f"{BASE}/read", headers=a.headers, json={"userId": str(u.id)})
    assert r.json() == {"marked": 2}


async def test_user_read_does_not_touch_user_messages_or_other_threads(
    client: Any, make_user: Any, db: Any
) -> None:
    u, v, a = await make_user(), await make_user(), await make_user(role="admin")
    mine = await seed(db, u, "from u", to_admin=a)
    theirs = await seed(db, v, "to v", sender=a, role="admin")
    r = await client.post(f"{BASE}/read", headers=u.headers)
    assert r.json() == {"marked": 0}
    assert (await db.chatmessages.find_one({"_id": mine}))["readAt"] is None
    assert (await db.chatmessages.find_one({"_id": theirs}))["readAt"] is None


async def test_admin_read_requires_valid_user_id(client: Any, make_user: Any) -> None:
    a = await make_user(role="admin")
    for body in (None, {}, {"userId": "bad"}, {"userId": {"$ne": ""}}):
        r = await client.post(f"{BASE}/read", headers=a.headers, json=body)
        assert r.status_code == 422, body


async def test_threads_unread_first_then_latest_activity(
    client: Any, make_user: Any, db: Any
) -> None:
    a = await make_user(role="admin")
    u1 = await make_user(username="quiet")
    u2 = await make_user(username="old")
    u3 = await make_user(username="noisy")
    await seed(db, u1, "x", to_admin=a, created=kit.minutes_ago(1), read=kit.minutes_ago(0.5))
    await seed(db, u2, "x", to_admin=a, created=kit.minutes_ago(50))
    await seed(db, u3, "x", to_admin=a, created=kit.minutes_ago(20))
    await seed(db, u3, "y", to_admin=a, created=kit.minutes_ago(19))
    rows = (await client.get(f"{BASE}/threads", headers=a.headers)).json()
    assert [r["userId"] for r in rows] == [str(u3.id), str(u2.id), str(u1.id)]
    by = {r["userId"]: r for r in rows}
    assert by[str(u3.id)]["unreadCount"] == 2 and by[str(u1.id)]["unreadCount"] == 0
    assert by[str(u3.id)]["name"] == "noisy" and by[str(u3.id)]["lastMessageAt"]


# ------------------------------------------------------------------ pagination


async def _seed_n(db: Any, u: Any, adm: Any, n: int) -> list[Any]:
    return [
        await seed(db, u, f"m{i}", to_admin=adm, created=kit.minutes_ago(n - i + 1))
        for i in range(n)
    ]


async def test_limit_returns_latest_window_ascending(client: Any, make_user: Any, db: Any) -> None:
    u, adm = await make_user(), await make_user(role="admin")
    await _seed_n(db, u, adm, 5)
    got = (await thread(client, u, limit=2)).json()["messages"]
    assert [m["text"] for m in got] == ["m3", "m4"]


async def test_before_cursor_returns_older_messages(client: Any, make_user: Any, db: Any) -> None:
    u, adm = await make_user(), await make_user(role="admin")
    ids = await _seed_n(db, u, adm, 5)
    got = (await thread(client, u, before=str(ids[3]), limit=2)).json()["messages"]
    assert [m["text"] for m in got] == ["m1", "m2"]
    got = (await thread(client, u, before=str(ids[1]), limit=10)).json()["messages"]
    assert [m["text"] for m in got] == ["m0"]
    assert (await thread(client, u, before=str(ids[0]))).json()["messages"] == []


async def test_default_limit_100_and_clamp_to_200(client: Any, make_user: Any, db: Any) -> None:
    u, adm = await make_user(), await make_user(role="admin")
    base = kit.minutes_ago(500)
    await db.chatmessages.insert_many(
        [
            {
                "threadUserId": u.id,
                "fromId": u.id,
                "fromRole": "user",
                "toAdminId": adm.id,
                "text": f"m{i}",
                "createdAt": base + timedelta(seconds=i),
                "updatedAt": base + timedelta(seconds=i),
                "editedAt": None,
                "readAt": None,
            }
            for i in range(230)
        ]
    )
    assert len((await thread(client, u)).json()["messages"]) == 100
    clamped = (await thread(client, u, limit=500)).json()["messages"]
    assert len(clamped) == 200 and clamped[-1]["text"] == "m229"
    assert len((await thread(client, u, limit=200)).json()["messages"]) == 200
    assert (await thread(client, u, limit=0)).status_code == 422


async def test_stable_order_when_messages_share_created_at(
    client: Any, make_user: Any, db: Any
) -> None:
    u, adm = await make_user(), await make_user(role="admin")
    same = kit.minutes_ago(5)
    ids = [await seed(db, u, f"s{i}", to_admin=adm, created=same) for i in range(4)]
    order = [m["text"] for m in (await thread(client, u)).json()["messages"]]
    assert order == ["s0", "s1", "s2", "s3"]
    seen: list[str] = []
    cursor = None
    for _ in range(4):
        params: dict[str, Any] = {"limit": 1}
        if cursor:
            params["before"] = cursor
        page = (await thread(client, u, **params)).json()["messages"]
        assert len(page) == 1
        seen.append(page[0]["text"])
        cursor = page[0]["id"]
    assert seen == ["s3", "s2", "s1", "s0"]
    assert cursor == str(ids[0])
    assert (await thread(client, u, before=cursor, limit=1)).json()["messages"] == []
