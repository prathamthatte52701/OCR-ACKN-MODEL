"""IST (UTC+05:30) calendar boundaries: admin purge-by-month and dashboard series day grouping.
Runs on the *_test database only (conftest.py)."""

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

IST = timezone(timedelta(hours=5, minutes=30))


def _utc(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


def _body(admin: Any, year: int, months: list[int], phrase: str) -> dict[str, Any]:
    return {
        "year": year,
        "months": months,
        "password": admin.password,
        "confirmPassword": admin.password,
        "confirmationPhrase": phrase,
    }


async def _seed(db: Any, owner: Any, iso: str, number: str = "1") -> Any:
    doc_id = (
        await db.documents.insert_one(
            {
                "userId": owner.id,
                "uploadStatus": "processed",
                "documentType": "Tax Invoice",
                "number": number,
                "isDeleted": False,
                "createdAt": _utc(iso),
            }
        )
    ).inserted_id
    await db.exportedrows.insert_one(
        {"userId": owner.id, "documentId": doc_id, "exportedAt": _utc(iso)}
    )
    return doc_id


async def _purge(client: Any, admin: Any, year: int, months: list[int], user: Any = None) -> Any:
    url = f"/api/admin/users/{user.id}/purge-months" if user else "/api/admin/purge-months"
    phrase = "NUKE USER MONTHS" if user else "NUKE ALL MONTHS"
    return await client.request(
        "DELETE", url, headers=admin.headers, json=_body(admin, year, months, phrase)
    )


CASES = [
    # (createdAt UTC, year, months, expected deleted)
    ("2026-01-31T19:00:00Z", 2026, [1], False),  # Feb 1 00:30 IST
    ("2026-01-31T19:00:00Z", 2026, [2], True),
    ("2025-12-31T19:00:00Z", 2026, [1], True),  # Jan 1 00:30 IST
    ("2025-12-31T19:00:00Z", 2025, [12], False),
    ("2026-01-31T17:00:00Z", 2026, [1], True),  # Jan 31 22:30 IST
    ("2026-01-31T18:29:59Z", 2026, [1], True),
    ("2026-01-31T18:29:59Z", 2026, [2], False),
    ("2026-01-31T18:30:00Z", 2026, [1], False),
    ("2026-01-31T18:30:00Z", 2026, [2], True),
    ("2025-12-31T18:29:59Z", 2025, [12], True),
    ("2025-12-31T18:29:59Z", 2026, [1], False),
    ("2025-12-31T18:30:00Z", 2026, [1], True),
    ("2025-12-31T18:30:00Z", 2025, [12], False),
    ("2028-02-29T10:00:00Z", 2028, [2], True),  # leap day
    ("2028-02-29T10:00:00Z", 2028, [3], False),
]


@pytest.mark.parametrize("glob", [True, False])
@pytest.mark.parametrize("iso,year,months,deleted", CASES)
async def test_month_boundaries(
    client: Any,
    make_user: Any,
    db: Any,
    glob: bool,
    iso: str,
    year: int,
    months: list[int],
    deleted: bool,
) -> None:
    admin, u = await make_user(role="admin"), await make_user()
    doc_id = await _seed(db, u, iso)
    r = await _purge(client, admin, year, months, None if glob else u)
    assert r.status_code == 200, r.text
    expected = 0 if deleted else 1
    assert await db.documents.count_documents({"_id": doc_id}) == expected
    assert await db.exportedrows.count_documents({"documentId": doc_id}) == expected


@pytest.mark.parametrize("glob", [True, False])
async def test_multi_month_and_dec_vs_jan(client: Any, make_user: Any, db: Any, glob: bool) -> None:
    admin, u = await make_user(role="admin"), await make_user()
    await _seed(db, u, "2025-12-31T19:00:00Z")  # IST Jan 1 2026
    await _seed(db, u, "2026-01-15T10:00:00Z")
    feb = await _seed(db, u, "2026-02-15T10:00:00Z")
    await _seed(db, u, "2026-03-15T10:00:00Z")
    r = await _purge(client, admin, 2026, [1, 3], None if glob else u)
    assert r.status_code == 200, r.text
    left = {d["_id"] async for d in db.documents.find({})}
    assert left == {feb}
    assert await db.exportedrows.count_documents({}) == 1


async def test_user_purge_spares_other_user_and_global_hits_all(
    client: Any, make_user: Any, db: Any
) -> None:
    admin, a, b = await make_user(role="admin"), await make_user(), await make_user()
    da = await _seed(db, a, "2026-01-10T10:00:00Z")
    await _seed(db, a, "2026-02-10T10:00:00Z")
    dbb = await _seed(db, b, "2026-01-10T10:00:00Z")
    r = await _purge(client, admin, 2026, [1], a)
    assert r.status_code == 200, r.text
    assert await db.documents.count_documents({"_id": da}) == 0
    assert await db.documents.count_documents({"_id": dbb}) == 1
    assert await db.documents.count_documents({"userId": a.id}) == 1
    assert await db.exportedrows.count_documents({"documentId": dbb}) == 1
    r = await _purge(client, admin, 2026, [1])
    assert r.status_code == 200, r.text
    assert await db.documents.count_documents({"_id": dbb}) == 0
    assert await db.documents.count_documents({"userId": a.id}) == 1  # Feb survives


@pytest.mark.parametrize("glob", [True, False])
async def test_duplicate_months_delete_once(
    client: Any, make_user: Any, db: Any, glob: bool
) -> None:
    admin, u = await make_user(role="admin"), await make_user()
    await _seed(db, u, "2026-01-10T10:00:00Z")
    await _seed(db, u, "2026-02-10T10:00:00Z")
    r = await _purge(client, admin, 2026, [1, 1, 1], None if glob else u)
    assert r.status_code == 200, r.text
    assert r.json()["documentsDeleted"] == 1
    assert await db.documents.count_documents({}) == 1


@pytest.mark.parametrize("glob", [True, False])
@pytest.mark.parametrize(
    "year,months",
    [(1999, [1]), (2101, [1]), (2026, []), (2026, [0]), (2026, [13]), (2026, [1] * 5000)],
)
async def test_invalid_input_never_500(
    client: Any, make_user: Any, db: Any, glob: bool, year: int, months: list[int]
) -> None:
    admin, u = await make_user(role="admin"), await make_user()
    await _seed(db, u, "2026-02-10T10:00:00Z")  # Feb: never matched by these inputs
    r = await _purge(client, admin, year, months, None if glob else u)
    assert r.status_code in (200, 400, 422), r.text
    assert await db.documents.count_documents({}) == 1


async def test_dashboard_series_groups_by_ist_day(client: Any, make_user: Any, db: Any) -> None:
    admin, u = await make_user(role="admin"), await make_user()
    today = datetime.now(IST).date()
    prev = today - timedelta(days=1)
    t_new = datetime(today.year, today.month, today.day, 0, 30, tzinfo=IST).astimezone(UTC)
    t_old = datetime(prev.year, prev.month, prev.day, 23, 30, tzinfo=IST).astimezone(UTC)
    # move make_user accounts out of the 30-day window so only the seeded ones count
    far = datetime.now(UTC) - timedelta(days=400)
    await db.users.update_many({}, {"$set": {"createdAt": far}})
    await db.users.update_one({"_id": u.id}, {"$set": {"createdAt": t_new}})
    await db.users.update_one({"_id": admin.id}, {"$set": {"createdAt": t_old}})
    for t in (t_new, t_old, t_old):
        await db.documents.insert_one(
            {
                "userId": u.id,
                "uploadStatus": "processed",
                "documentType": "Tax Invoice",
                "isDeleted": False,
                "createdAt": t,
            }
        )
    await db.exportedrows.insert_many(
        [{"userId": u.id, "exportedAt": t_new}, {"userId": u.id, "exportedAt": t_old}]
    )
    r = await client.get("/api/admin/telemetry", headers=admin.headers)
    assert r.status_code == 200, r.text
    s = r.json()["series"]
    assert len(s["days"]) == 30 and s["days"][-1] == today.isoformat()
    assert s["days"][-2] == prev.isoformat()
    assert s["documents"][-1] == 1 and s["documents"][-2] == 2
    assert s["users"][-1] == 1 and s["users"][-2] == 1
    assert s["exports"][-1] == 1 and s["exports"][-2] == 1
