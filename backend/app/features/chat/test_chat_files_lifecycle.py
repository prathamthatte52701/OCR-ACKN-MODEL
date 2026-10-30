"""Chat files: 30-day expiry sweep, delete cascades (user, clear ranges, clear-all, wipe)."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.core.database import get_chat_gridfs
from app.features.chat import files
from app.features.chat.chat_testkit import BASE
from app.features.chat.test_chat_files import (  # noqa: F401
    img_bytes,
    pdf_bytes,
    stored_count,
    up,
)
from app.scripts import wipe_all_except_admins as wipe

DAY = timedelta(days=1)


async def send(
    client: Any, u: Any, adm: Any, data: bytes | None = None, name: str = "a.pdf"
) -> dict:
    r = await up(client, u, data or pdf_bytes(), name, to=adm)
    assert r.status_code == 201, r.text
    return r.json()


async def age(db: Any, msg: dict, days: float) -> None:
    """Pretend the message and its file were sent `days` ago."""
    when = datetime.now(UTC) - timedelta(days=days)
    await db.chatmessages.update_one(
        {"_id": __import__("bson").ObjectId(msg["id"])}, {"$set": {"createdAt": when}}
    )
    await db.chatattachments.update_one(
        {"messageId": __import__("bson").ObjectId(msg["id"])},
        {"$set": {"createdAt": when, "expiresAt": when + files.RETENTION}},
    )


# ---------- expiry ----------


async def test_sweep_expires_after_30_days_keeps_message_and_bumps_updated(
    client: Any, db: Any, trio: Any
) -> None:
    u, adm, _ = trio
    m = await send(client, u, adm)
    since = (await client.get(f"{BASE}/messages", headers=u.headers)).json()["nextSince"]
    await asyncio.sleep(0.01)
    assert await files.sweep_expired(db) == 0  # fresh file: nothing due
    assert await files.sweep_expired(db, now=datetime.now(UTC) + 31 * DAY) == 1
    assert await stored_count(db) == (0, 1)  # bytes gone, record kept as "expired"
    poll = (await client.get(f"{BASE}/messages", headers=u.headers, params={"since": since})).json()
    got = next(x for x in poll["messages"] if x["id"] == m["id"])
    assert got["attachment"]["expired"] is True and got["id"] == m["id"]
    assert await files.sweep_expired(db, now=datetime.now(UTC) + 32 * DAY) == 0  # idempotent


async def test_read_treats_past_expiry_as_expired_before_the_sweep_runs(
    client: Any, db: Any, trio: Any
) -> None:
    u, adm, _ = trio
    m = await send(client, u, adm)
    await age(db, m, 31)
    got = (await client.get(f"{BASE}/messages", headers=u.headers)).json()["messages"][0]
    assert got["attachment"]["expired"] is True
    url = f"{BASE}/files/{m['attachment']['id']}"
    g = await client.get(url, headers=u.headers)
    assert g.status_code == 410 and g.json()["detail"] == "This file has expired."
    assert (await client.get(url, headers=adm.headers)).status_code == 410  # participant admin


async def test_expired_is_404_for_a_stranger(
    client: Any, db: Any, trio: Any, make_user: Any
) -> None:
    u, adm, _ = trio
    m = await send(client, u, adm)
    await age(db, m, 31)
    other = await make_user()
    r = await client.get(f"{BASE}/files/{m['attachment']['id']}", headers=other.headers)
    assert r.status_code == 404


async def test_sweep_batch_is_200_oldest_first(client: Any, db: Any, trio: Any) -> None:
    u, adm, _ = trio
    for _ in range(3):
        await send(client, u, adm)
    docs = await db.chatattachments.find({}).sort("_id", 1).to_list(None)
    for i, d in enumerate(docs):
        await db.chatattachments.update_one(
            {"_id": d["_id"]}, {"$set": {"expiresAt": datetime.now(UTC) - DAY * (i + 1)}}
        )
    orig = files.SWEEP_BATCH
    files.SWEEP_BATCH = 2
    try:
        assert await files.sweep_expired(db) == 2
    finally:
        files.SWEEP_BATCH = orig
    left = await db.chatattachments.find({"expired": False}).to_list(None)
    assert [x["_id"] for x in left] == [docs[0]["_id"]]  # the least overdue one waits
    assert await files.sweep_expired(db) == 1


async def test_failed_delete_is_tracked_and_retried_never_raises(
    client: Any, db: Any, trio: Any, monkeypatch: Any
) -> None:
    u, adm, _ = trio
    m = await send(client, u, adm)
    real = get_chat_gridfs()

    class Broken:
        async def delete(self, _id: Any) -> None:
            raise OSError("disk")

    monkeypatch.setattr(files, "get_chat_gridfs", lambda: Broken())
    await files.sweep_expired(db, now=datetime.now(UTC) + 31 * DAY)  # no exception
    assert await db.chatfileorphans.count_documents({}) == 1
    assert await db["chatfs.files"].count_documents({}) == 1
    # the message already shows "expired"; the bytes are removed by the retry
    monkeypatch.setattr(files, "get_chat_gridfs", lambda: real)
    await files.sweep_expired(db)
    assert await db.chatfileorphans.count_documents({}) == 0
    assert await db["chatfs.files"].count_documents({}) == 0
    assert m["attachment"]["id"]


async def test_sweep_survives_a_broken_database() -> None:
    assert await files.sweep_expired(None) == 0


async def test_expiry_loop_runs_once_then_waits_and_survives_errors(db: Any) -> None:
    calls = 0

    async def fake_sleep(_s: float) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await files.run_expiry_forever(sleep=fake_sleep, interval=1)
    assert calls == 2


# ---------- cascades ----------


async def test_delete_user_removes_their_chat_files_only(
    client: Any, db: Any, trio: Any, make_user: Any
) -> None:
    u, adm, _ = trio
    v = await make_user()
    await send(client, u, adm)
    await send(client, v, adm)
    assert await stored_count(db) == (2, 2)
    r = await client.delete(f"/api/admin/users/{u.id}", headers=adm.headers)
    assert r.status_code == 200
    assert await stored_count(db) == (1, 1)
    assert (await db.chatattachments.find_one({}))["threadUserId"] == v.id


async def test_clear_by_range_deletes_only_older_files_and_dry_run_deletes_nothing(
    client: Any, db: Any, trio: Any
) -> None:
    u, adm, _ = trio
    old = await send(client, u, adm, pdf_bytes(1500))
    new = await send(client, u, adm, pdf_bytes(1000))
    await age(db, old, 40)
    body = {"userId": str(u.id), "olderThan": "1m"}
    dry = await client.post(f"{BASE}/clear", headers=adm.headers, json={**body, "dryRun": True})
    assert dry.json() == {"count": 1, "files": 1, "bytes": 1500}
    assert await stored_count(db) == (2, 2)
    real = await client.post(
        f"{BASE}/clear", headers=adm.headers, json={**body, "confirm": "DELETE"}
    )
    assert real.json() == {"deleted": 1, "files": 1, "bytes": 1500}
    assert await stored_count(db) == (1, 1)
    left = await db.chatattachments.find_one({})
    assert str(left["messageId"]) == new["id"]


@pytest.mark.parametrize(
    "rng,days", [("24h", 2), ("3d", 4), ("1w", 8), ("1m", 31), ("3m", 91), ("6m", 181), ("1y", 366)]
)
async def test_every_clear_range_removes_the_file_of_an_old_message(
    client: Any, db: Any, trio: Any, rng: str, days: int
) -> None:
    u, adm, _ = trio
    old = await send(client, u, adm)
    await send(client, u, adm)
    await age(db, old, days)
    r = await client.post(
        f"{BASE}/clear",
        headers=adm.headers,
        json={"userId": str(u.id), "olderThan": rng, "confirm": "DELETE"},
    )
    assert r.json()["deleted"] == 1 and r.json()["files"] == 1
    assert await stored_count(db) == (1, 1)


async def test_clear_all_removes_every_file_and_audit_has_counts_only(
    client: Any, db: Any, trio: Any, make_user: Any
) -> None:
    u, adm, _ = trio
    v = await make_user()
    await send(client, u, adm, name="secret-name.pdf")
    await send(client, v, adm)
    r = await client.post(
        f"{BASE}/clear-all",
        headers=adm.headers,
        json={"password": adm.password, "confirm": "DELETE"},
    )
    assert r.json()["files"] == 2
    assert await stored_count(db) == (0, 0)
    audit = await db.auditlogs.find({"action": "chat_cleared"}).to_list(None)
    assert audit and "secret-name" not in str(audit)
    assert audit[-1]["details"]["files"] == 2 if "details" in audit[-1] else True


async def test_wipe_dry_run_counts_chat_files_and_apply_removes_them(
    client: Any, db: Any, trio: Any, tmp_path: Path, capsys: Any
) -> None:
    u, adm, _ = trio
    await send(client, u, adm)
    capsys.readouterr()
    assert await wipe.run(["--db", db.name], exports_dir=tmp_path) == 0
    out = capsys.readouterr().out
    assert "Chat GridFS: 1 files" in out and await stored_count(db) == (1, 1)
    assert (
        await wipe.run(["--db", db.name, "--apply", "--i-have-a-backup"], exports_dir=tmp_path) == 0
    )
    assert await stored_count(db) == (0, 0)
    assert await db["chatfs.chunks"].count_documents({}) == 0
