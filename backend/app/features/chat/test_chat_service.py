"""Chat service logic (db fixture) plus a few HTTP smoke tests and the two send limits."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from bson import ObjectId

from app.core.rate_limit import limiter
from app.features.chat import service
from app.features.chat.service import ChatError

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _now(monkeypatch: Any, when: datetime) -> None:
    monkeypatch.setattr(service, "utcnow", lambda: when)


@pytest.fixture
def limits_on() -> Iterator[None]:
    old = limiter.enabled
    limiter.enabled = True
    limiter.reset()
    try:
        yield
    finally:
        limiter.reset()
        limiter.enabled = old


async def _msg(db: Any, user: Any, text: str, at: datetime, *, admin: Any = None, **kw: Any) -> Any:
    doc = {
        "threadUserId": user.id,
        "fromId": admin.id if kw.get("from_admin") else user.id,
        "fromRole": "admin" if kw.get("from_admin") else "user",
        "toAdminId": None if kw.get("from_admin") else admin.id,
        "text": text,
        "createdAt": at,
        "updatedAt": at,
        "editedAt": None,
        "readAt": None,
    }
    return (await db.chatmessages.insert_one(doc)).inserted_id


# ---- pure helpers -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [None, 5, [], "", "   \n\t", "a\x00b", "x" * 1001])
def test_clean_text_rejects(bad: Any) -> None:
    with pytest.raises(ChatError) as e:
        service.clean_text(bad)
    assert e.value.status == 422 and e.value.detail


def test_clean_text_ok() -> None:
    assert service.clean_text("  hi  ") == "hi"
    assert len(service.clean_text("x" * 1000)) == 1000
    assert service.clean_text("  " + "é" * 1000 + "  ") == "é" * 1000


def test_parse_object_id() -> None:
    assert service.parse_object_id(str(ObjectId()), "id")
    for bad in (None, 12, "nope", ObjectId()):
        with pytest.raises(ChatError):
            service.parse_object_id(bad, "id")


# ---- edit window --------------------------------------------------------------------------


async def test_edit_window_edge(db: Any, make_user: Any, monkeypatch: Any) -> None:
    u, a = await make_user(), await make_user(role="admin")
    _now(monkeypatch, T0)
    sent = await service.send_user_message(db, u.id, str(a.id), "hello")
    mid = ObjectId(sent["id"])
    _now(monkeypatch, T0 + timedelta(minutes=15))
    out = await service.edit_message(db, u.id, mid, "edited")
    assert out["text"] == "edited" and out["editedAt"]
    # created_at is stored with millisecond precision, so step by 1 ms
    _now(monkeypatch, T0 + timedelta(minutes=15, milliseconds=1))
    with pytest.raises(ChatError) as e:
        await service.edit_message(db, u.id, mid, "late")
    assert e.value.status == 403
    with pytest.raises(ChatError) as e2:
        await service.edit_message(db, a.id, mid, "not yours")
    assert e2.value.status == 403
    with pytest.raises(ChatError) as e3:
        await service.edit_message(db, u.id, ObjectId(), "x")
    assert e3.value.status == 404


# ---- unread / read between two admins -----------------------------------------------------


async def test_unread_read_two_admins(db: Any, make_user: Any) -> None:
    u = await make_user()
    a1, a2 = await make_user(role="admin"), await make_user(role="admin")
    await service.send_user_message(db, u.id, str(a1.id), "to one")
    await service.send_user_message(db, u.id, str(a2.id), "to two")
    await service.send_admin_message(db, a1.id, str(u.id), "reply")
    assert (await service.unread_admin(db, a1.id))["count"] == 1
    assert (await service.unread_admin(db, a2.id))["byUser"] == [{"userId": str(u.id), "count": 1}]
    assert await service.unread_user(db, u.id) == {"count": 1}
    newest = (await db.chatmessages.find_one({}, sort=[("createdAt", -1), ("_id", -1)]))["_id"]
    assert await service.mark_read_admin(db, a1.id, u.id, newest) == 1
    assert await service.mark_read_admin(db, a1.id, u.id, newest) == 0  # idempotent
    assert (await service.unread_admin(db, a2.id))["count"] == 1  # other admin untouched
    assert await service.mark_read_user(db, u.id, newest) == 1
    assert await service.unread_user(db, u.id) == {"count": 0}
    threads = await service.list_threads(db, a2.id)
    assert [t["userId"] for t in threads] == [str(u.id)] and threads[0]["unreadCount"] == 1


async def test_threads_sort(db: Any, make_user: Any) -> None:
    a = await make_user(role="admin")
    quiet, old, unread, empty = [await make_user(username=n) for n in ("q", "o", "un", "e")]
    await _msg(db, old, "m", T0, admin=a)
    await db.chatmessages.update_one({"threadUserId": old.id}, {"$set": {"readAt": T0}})
    await _msg(db, quiet, "m", T0 + timedelta(hours=1), admin=a)
    await db.chatmessages.update_one({"threadUserId": quiet.id}, {"$set": {"readAt": T0}})
    await _msg(db, unread, "m", T0 - timedelta(days=1), admin=a)
    order = [t["name"] for t in await service.list_threads(db, a.id)]
    assert order == ["un", "q", "o", "e"]


# ---- clear --------------------------------------------------------------------------------


async def test_clear_ranges_and_dry_run(db: Any, make_user: Any, monkeypatch: Any) -> None:
    u, other = await make_user(), await make_user()
    a = await make_user(role="admin")
    _now(monkeypatch, T0)
    cutoff = T0 - timedelta(hours=24)
    await _msg(db, u, "inside", cutoff + timedelta(milliseconds=1), admin=a)
    await _msg(db, u, "exactly", cutoff, admin=a)
    await _msg(db, u, "outside", cutoff - timedelta(milliseconds=1), admin=a)
    await _msg(db, other, "other", cutoff - timedelta(days=9), admin=a)
    assert await service.clear_thread(db, a.id, u.id, "24h", True) == 1
    assert await db.chatmessages.count_documents({}) == 4
    assert await service.clear_thread(db, a.id, u.id, "24h", False) == 1
    left = {m["text"] async for m in db.chatmessages.find({"threadUserId": u.id})}
    assert left == {"inside", "exactly"}
    with pytest.raises(ChatError):
        await service.clear_thread(db, a.id, u.id, "2d", False)
    assert await service.clear_thread(db, a.id, u.id, "all", False) == 2
    assert await service.clear_all(db, a.id, True) == 1
    assert await service.clear_all(db, a.id, False) == 1


# ---- pagination ---------------------------------------------------------------------------


async def test_pagination_stable_with_equal_created_at(db: Any, make_user: Any) -> None:
    u, a = await make_user(), await make_user(role="admin")
    ids = [await _msg(db, u, f"m{i}", T0, admin=a) for i in range(5)]
    ids.append(await _msg(db, u, "m5", T0 + timedelta(seconds=1), admin=a))
    got = await service.fetch_messages(db, u.id, "user", u.id, limit=4)
    assert [m["id"] for m in got] == [str(i) for i in ids[2:]]
    older = await service.fetch_messages(db, u.id, "user", u.id, before=ids[2], limit=4)
    assert [m["id"] for m in older] == [str(i) for i in ids[:2]]
    since = await service.fetch_messages(db, u.id, "user", u.id, since=T0 + timedelta(seconds=1))
    assert [m["text"] for m in since] == ["m5"]
    with pytest.raises(ChatError) as e:
        await service.fetch_messages(db, u.id, "user", ObjectId())
    assert e.value.status == 403


async def test_removed_names(db: Any, make_user: Any) -> None:
    u, a = await make_user(), await make_user(role="admin")
    await service.send_user_message(db, u.id, str(a.id), "q")
    await service.send_admin_message(db, a.id, str(u.id), "a")
    await db.users.delete_one({"_id": a.id})
    msgs = await service.fetch_messages(db, u.id, "user", u.id)
    assert [m["fromName"] for m in msgs] == [u.username, "Removed admin"]
    assert msgs[0]["toAdminName"] == "Removed admin" and msgs[1]["toAdminName"] is None
    assert msgs[0]["mine"] and msgs[0]["canEdit"] and not msgs[1]["canEdit"]


async def test_send_validation(db: Any, make_user: Any) -> None:
    u, a = await make_user(), await make_user(role="admin")
    u2 = await make_user()
    pending = await make_user(role="admin", status="pending")
    for target in (str(u.id), str(pending.id), "bad", None):
        with pytest.raises(ChatError) as e:
            await service.send_user_message(db, u.id, target, "hi")
        assert e.value.status == 422
    for target in (str(a.id), str(ObjectId())):
        with pytest.raises(ChatError) as e:
            await service.send_admin_message(db, a.id, target, "hi")
        assert e.value.status == 404
    assert (await service.send_admin_message(db, a.id, str(u2.id), "hi"))["toAdminId"] is None


# ---- HTTP smoke ---------------------------------------------------------------------------


async def test_http_flow(client: Any, make_user: Any, db: Any) -> None:
    u, a = await make_user(), await make_user(role="admin")
    assert (await client.get("/api/chat/admins", headers=a.headers)).status_code == 403
    admins = (await client.get("/api/chat/admins", headers=u.headers)).json()
    assert admins == [{"id": str(a.id), "name": a.username}]
    sent = await client.post(
        "/api/chat/messages", headers=u.headers, json={"toAdminId": str(a.id), "text": "hello"}
    )
    assert sent.status_code == 201 and sent.json()["canEdit"] is True
    bad = await client.post(
        "/api/chat/messages", headers=u.headers, json={"userId": str(u.id), "text": "x"}
    )
    assert bad.status_code == 422
    bad = await client.post(
        "/api/chat/messages", headers=u.headers, json={"toAdminId": str(a.id), "text": 5}
    )
    assert bad.status_code == 422
    assert (await client.get("/api/chat/unread", headers=a.headers)).json()["count"] == 1
    assert (await client.get("/api/chat/threads", headers=u.headers)).status_code == 403
    msgs = await client.get("/api/chat/messages", params={"userId": str(u.id)}, headers=a.headers)
    assert msgs.status_code == 200 and msgs.json()["serverTime"].endswith("Z")
    assert (await client.get("/api/chat/messages", headers=a.headers)).status_code == 422
    other = await client.get("/api/chat/messages", params={"userId": str(a.id)}, headers=u.headers)
    assert other.status_code == 403
    assert (await client.get("/api/chat/messages?limit=0", headers=u.headers)).status_code == 422
    assert (await client.get("/api/chat/messages?limit=999", headers=u.headers)).status_code == 200
    assert (await client.get("/api/chat/messages?since=zzz", headers=u.headers)).status_code == 422
    last = (await db.chatmessages.find_one({}, sort=[("createdAt", -1), ("_id", -1)]))["_id"]
    read = await client.post(
        "/api/chat/read", headers=a.headers, json={"userId": str(u.id), "upToId": str(last)}
    )
    assert read.json() == {"marked": 1}
    put = await client.put("/api/chat/settings/color", headers=u.headers, json={"color": "rose"})
    assert put.json() == {"chatColor": "rose"}
    assert (await client.get("/api/chat/settings", headers=a.headers)).json() == {
        "chatColor": "blue"
    }
    assert (
        await client.put("/api/chat/settings/color", headers=u.headers, json={"color": "pink"})
    ).status_code == 422
    body = {"userId": str(u.id), "olderThan": "all"}
    no_confirm = await client.post("/api/chat/clear", headers=a.headers, json=body)
    assert no_confirm.status_code == 422
    dry = await client.post("/api/chat/clear", headers=a.headers, json={**body, "dryRun": True})
    assert dry.json() == {"count": 1}
    done = await client.post(
        "/api/chat/clear", headers=a.headers, json={**body, "confirm": "DELETE"}
    )
    assert done.json() == {"deleted": 1}
    log = await db.auditlogs.find_one({"action": "chat_cleared"})
    assert log["context"] == {"scope": str(u.id), "range": "all", "deleted": 1}


async def test_http_clear_all_password(client: Any, make_user: Any, new_password: str) -> None:
    a = await make_user(role="admin")
    wrong = await client.post(
        "/api/chat/clear-all", headers=a.headers, json={"password": "nope", "confirm": "DELETE"}
    )
    assert wrong.status_code == 400 and wrong.json()["detail"] == "Incorrect password."
    ok = await client.post(
        "/api/chat/clear-all",
        headers=a.headers,
        json={"password": new_password, "confirm": "DELETE"},
    )
    assert ok.status_code == 200 and ok.json() == {"deleted": 0}


async def test_send_limits_per_account(client: Any, make_user: Any, limits_on: None) -> None:
    u, u2, a = await make_user(), await make_user(), await make_user(role="admin")

    async def user_send(who: Any) -> int:
        r = await client.post(
            "/api/chat/messages", headers=who.headers, json={"toAdminId": str(a.id), "text": "x"}
        )
        return r.status_code

    for _ in range(60):
        assert await user_send(u) == 201
    assert await user_send(u) == 429
    assert await user_send(u2) == 201  # another account, same IP, own budget
    for i in range(200):
        r = await client.post(
            "/api/chat/messages", headers=a.headers, json={"userId": str(u.id), "text": "x"}
        )
        assert r.status_code == 201, i
    r = await client.post(
        "/api/chat/messages", headers=a.headers, json={"userId": str(u.id), "text": "x"}
    )
    assert r.status_code == 429


async def test_clear_all_limit_counts_wrong_passwords(
    client: Any, make_user: Any, limits_on: None
) -> None:
    a = await make_user(role="admin")
    codes = []
    for _ in range(6):
        r = await client.post(
            "/api/chat/clear-all", headers=a.headers, json={"password": "bad", "confirm": "DELETE"}
        )
        codes.append(r.status_code)
    assert codes == [400] * 5 + [429]
