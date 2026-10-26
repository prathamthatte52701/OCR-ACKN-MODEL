"""Admin clear / clear-all: range cutoffs, dry runs, confirmation, password, audit."""

import json
from datetime import timedelta
from typing import Any

import pytest

from app.features.chat import chat_testkit as kit
from app.features.chat.chat_testkit import BASE, limiter_on, seed  # noqa: F401

DURATIONS = {
    "24h": timedelta(hours=24),
    "3d": timedelta(days=3),
    "1w": timedelta(days=7),
    "1m": timedelta(days=30),
    "3m": timedelta(days=90),
    "6m": timedelta(days=180),
    "1y": timedelta(days=365),
}
SECRET = "super-secret-chat-body-xyz"


async def _clear(client: Any, adm: Any, user: Any, older: str, **kw: Any) -> Any:
    body = {"userId": str(user.id), "olderThan": older, **kw}
    return await client.post(f"{BASE}/clear", headers=adm.headers, json=body)


async def _clear_all(client: Any, adm: Any, **kw: Any) -> Any:
    body = {"password": adm.password, "confirm": "DELETE", "dryRun": False, **kw}
    return await client.post(f"{BASE}/clear-all", headers=adm.headers, json=body)


async def _texts(db: Any, user: Any) -> list[str]:
    docs = await db.chatmessages.find({"threadUserId": user.id}).sort("createdAt", 1).to_list(None)
    return [d["text"] for d in docs]


@pytest.mark.parametrize("rng", list(DURATIONS))
async def test_range_boundary_just_inside_kept_just_outside_deleted(
    client: Any, make_user: Any, db: Any, rng: str
) -> None:
    adm, u, other = await make_user(role="admin"), await make_user(), await make_user()
    d, margin = DURATIONS[rng], timedelta(minutes=2)
    now = kit.ms_now()
    await seed(db, u, "outside", to_admin=adm, created=now - d - margin)
    await seed(db, u, "inside", to_admin=adm, created=now - d + margin)
    await seed(db, other, "other-old", to_admin=adm, created=now - d - margin)

    dry = await _clear(client, adm, u, rng, dryRun=True)
    assert dry.status_code == 200 and dry.json() == {"count": 1}
    assert await _texts(db, u) == ["outside", "inside"]

    real = await _clear(client, adm, u, rng, confirm="DELETE")
    assert real.status_code == 200 and real.json() == {"deleted": 1}
    assert await _texts(db, u) == ["inside"]
    assert await _texts(db, other) == ["other-old"]


async def test_all_clears_whole_thread_only(client: Any, make_user: Any, db: Any) -> None:
    adm, u, other = await make_user(role="admin"), await make_user(), await make_user()
    for i in range(3):
        await seed(db, u, f"m{i}", to_admin=adm, created=kit.minutes_ago(i))
    await seed(db, other, "keep", to_admin=adm)
    assert (await _clear(client, adm, u, "all", dryRun=True)).json() == {"count": 3}
    assert (await _clear(client, adm, u, "all", confirm="DELETE")).json() == {"deleted": 3}
    assert await _texts(db, u) == [] and await _texts(db, other) == ["keep"]


async def test_dry_run_deletes_nothing_and_needs_no_confirm(
    client: Any, make_user: Any, db: Any
) -> None:
    adm, u = await make_user(role="admin"), await make_user()
    await seed(db, u, "a", to_admin=adm)
    r = await _clear(client, adm, u, "all", dryRun=True)
    assert r.status_code == 200 and r.json() == {"count": 1}
    assert await db.chatmessages.count_documents({}) == 1
    assert await db.auditlogs.count_documents({"action": "chat_cleared"}) == 0


@pytest.mark.parametrize("confirm", [None, "", "delete", "DELETE ", "yes", 1, True])
async def test_real_clear_requires_exact_confirm(
    client: Any, make_user: Any, db: Any, confirm: Any
) -> None:
    adm, u = await make_user(role="admin"), await make_user()
    await seed(db, u, "a", to_admin=adm)
    kw: dict[str, Any] = {"dryRun": False}
    if confirm is not None:
        kw["confirm"] = confirm
    r = await _clear(client, adm, u, "all", **kw)
    assert r.status_code == 422
    assert await db.chatmessages.count_documents({}) == 1


async def test_unknown_range_and_bad_user_id_rejected(client: Any, make_user: Any) -> None:
    adm, u = await make_user(role="admin"), await make_user()
    for bad in ("2d", "", "ALL", "forever", 5, None, {"$ne": ""}):
        r = await client.post(
            f"{BASE}/clear",
            headers=adm.headers,
            json={"userId": str(u.id), "olderThan": bad, "dryRun": True},
        )
        assert r.status_code == 422, bad
    for bad in ("abc", "", {"$ne": ""}, None):
        r = await client.post(
            f"{BASE}/clear",
            headers=adm.headers,
            json={"userId": bad, "olderThan": "all", "dryRun": True},
        )
        assert r.status_code == 422, bad


async def test_user_cannot_clear_even_own_thread(client: Any, make_user: Any, db: Any) -> None:
    adm, u = await make_user(role="admin"), await make_user()
    await seed(db, u, "a", to_admin=adm)
    r = await client.post(
        f"{BASE}/clear",
        headers=u.headers,
        json={"userId": str(u.id), "olderThan": "all", "confirm": "DELETE"},
    )
    assert r.status_code == 403
    r = await client.post(
        f"{BASE}/clear-all",
        headers=u.headers,
        json={"password": u.password, "confirm": "DELETE", "dryRun": False},
    )
    assert r.status_code == 403
    assert (await client.get(f"{BASE}/threads", headers=u.headers)).status_code == 403
    assert await db.chatmessages.count_documents({}) == 1


async def test_clear_all_dry_run_counts_every_thread(client: Any, make_user: Any, db: Any) -> None:
    adm, u, v = await make_user(role="admin"), await make_user(), await make_user()
    await seed(db, u, "a", to_admin=adm)
    await seed(db, u, "b", to_admin=adm)
    await seed(db, v, "c", to_admin=adm)
    r = await _clear_all(client, adm, dryRun=True)
    assert r.status_code == 200 and r.json() == {"count": 3}
    assert await db.chatmessages.count_documents({}) == 3


async def test_clear_all_deletes_everything(client: Any, make_user: Any, db: Any) -> None:
    adm, u, v = await make_user(role="admin"), await make_user(), await make_user()
    await seed(db, u, "a", to_admin=adm)
    await seed(db, v, "c", to_admin=adm)
    r = await _clear_all(client, adm)
    assert r.status_code == 200 and r.json() == {"deleted": 2}
    assert await db.chatmessages.count_documents({}) == 0


async def test_clear_all_wrong_password_400_without_hint(
    client: Any, make_user: Any, db: Any
) -> None:
    adm, u = await make_user(role="admin"), await make_user()
    await seed(db, u, "a", to_admin=adm)
    for dry in (True, False):
        r = await _clear_all(client, adm, password="Wr0ng!pass9", dryRun=dry)
        assert r.status_code == 400
        assert adm.password not in r.text and "Wr0ng" not in r.text
    assert await db.chatmessages.count_documents({}) == 1
    assert await db.auditlogs.count_documents({"action": "chat_cleared"}) == 0


async def test_clear_all_requires_confirm_for_real_delete(
    client: Any, make_user: Any, db: Any
) -> None:
    adm, u = await make_user(role="admin"), await make_user()
    await seed(db, u, "a", to_admin=adm)
    assert (await _clear_all(client, adm, confirm="nope")).status_code == 422
    assert (await _clear_all(client, adm, confirm=None)).status_code == 422
    assert await db.chatmessages.count_documents({}) == 1


@pytest.mark.usefixtures("limiter_on")
async def test_clear_all_sixth_attempt_per_hour_is_429_before_password_check(
    client: Any, make_user: Any, db: Any
) -> None:
    adm, other, u = await make_user(role="admin"), await make_user(role="admin"), await make_user()
    await seed(db, u, "a", to_admin=adm)
    for i in range(5):
        r = await _clear_all(client, adm, password="Wr0ng!pass9", dryRun=True)
        assert r.status_code == 400, f"attempt {i + 1}: {r.status_code}"
    r = await _clear_all(client, adm, dryRun=True)  # correct password, still limited
    assert r.status_code == 429
    assert await db.chatmessages.count_documents({}) == 1
    assert (await _clear_all(client, other, dryRun=True)).status_code == 200  # per account


async def test_real_clear_writes_counts_only_audit_entry(
    client: Any, make_user: Any, db: Any
) -> None:
    adm, u = await make_user(role="admin"), await make_user()
    old = kit.minutes_ago(60 * 24 * 5)
    await seed(db, u, SECRET + " one", to_admin=adm, created=old)
    await seed(db, u, SECRET + " two", to_admin=adm, created=old)
    await seed(db, u, SECRET + " fresh", to_admin=adm)
    assert (await _clear(client, adm, u, "3d", confirm="DELETE")).json() == {"deleted": 2}
    entries = await db.auditlogs.find({"action": "chat_cleared"}).to_list(None)
    assert len(entries) == 1
    ctx = entries[0]["context"]
    assert {"scope", "range", "deleted"} <= set(ctx)
    assert ctx["deleted"] == 2 and ctx["range"] == "3d"
    assert SECRET not in json.dumps(entries[0], default=str)


async def test_clear_all_writes_audit_counts_only(client: Any, make_user: Any, db: Any) -> None:
    adm, u = await make_user(role="admin"), await make_user()
    await seed(db, u, SECRET, to_admin=adm)
    await seed(db, u, SECRET + "2", to_admin=adm)
    assert (await _clear_all(client, adm)).json() == {"deleted": 2}
    entries = await db.auditlogs.find({"action": "chat_cleared"}).to_list(None)
    assert len(entries) == 1
    ctx = entries[0]["context"]
    assert ctx["deleted"] == 2 and {"scope", "range"} <= set(ctx)
    dumped = json.dumps(entries[0], default=str)
    assert SECRET not in dumped and adm.password not in dumped
