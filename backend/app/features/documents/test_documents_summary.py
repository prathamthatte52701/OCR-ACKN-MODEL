"""GET /documents/summary: counts + 3 newest docs, checked against a brute-force pass."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.timezones import ist_midnight_utc, now_ist

KEYS = {"total", "processed", "failed", "processedToday", "byDocumentType", "recent"}
DAY = timedelta(days=1)


def _bounds() -> tuple[datetime, datetime]:
    start = ist_midnight_utc(now_ist())
    return start, start + DAY


def _doc(owner: Any, n: int, **kw: Any) -> dict[str, Any]:
    base = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=n)
    d: dict[str, Any] = {
        "userId": owner.id,
        "originalFilename": f"f{n}.pdf",
        "uploadStatus": "processed",
        "documentType": "Delivery Challan",
        "number": f"N{n}",
        "edited": False,
        "createdAt": base,
        "updatedAt": base,
    }
    d.update(kw)
    for k in [k for k, v in d.items() if isinstance(v, str) and v == "UNSET"]:
        del d[k]
    return d


async def _get(client: Any, user: Any) -> dict[str, Any]:
    res = await client.get("/api/documents/summary", headers=user.headers)
    assert res.status_code == 200, res.text
    return res.json()


def _expected(docs: list[dict[str, Any]]) -> dict[str, Any]:
    start, end = _bounds()
    live = [d for d in docs if d.get("isDeleted") is not True]
    today = 0
    for d in live:
        ts = d.get("processedAt") or d.get("reprocessedAt") or d.get("updatedAt")
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        if d["uploadStatus"] == "processed" and start <= ts < end:
            today += 1
    return {
        "total": len(live),
        "processed": sum(d["uploadStatus"] == "processed" for d in live),
        "failed": sum(d["uploadStatus"] == "failed" for d in live),
        "processedToday": today,
        "byDocumentType": {
            t: sum(d["documentType"] == t for d in live)
            for t in ("Tax Invoice", "Delivery Challan")
        },
    }


async def test_requires_auth(client: Any) -> None:
    assert (await client.get("/api/documents/summary")).status_code == 401


async def test_not_shadowed_by_doc_id_route(client: Any, make_user: Any) -> None:
    u = await make_user()
    res = await client.get("/api/documents/summary", headers=u.headers)
    assert res.status_code == 200
    assert set(res.json()) == KEYS


async def test_empty_user(client: Any, make_user: Any) -> None:
    got = await _get(client, await make_user())
    assert got == {
        "total": 0,
        "processed": 0,
        "failed": 0,
        "processedToday": 0,
        "byDocumentType": {"Tax Invoice": 0, "Delivery Challan": 0},
        "recent": [],
    }


async def test_mixed_matches_bruteforce(client: Any, db: Any, make_user: Any) -> None:
    a, b = await make_user(), await make_user()
    docs = [
        _doc(a, 1, uploadStatus="uploaded"),
        _doc(a, 2, documentType="Tax Invoice", taxInvoiceNo="G1", referenceNo="R1"),
        _doc(a, 3, uploadStatus="failed"),
        _doc(a, 4, documentType="Tax Invoice", uploadStatus="failed"),
        _doc(a, 5, documentType="Weird Type"),
        _doc(a, 6, isDeleted=True),
        _doc(a, 7, isDeleted=False),
        _doc(a, 8),  # isDeleted missing
        _doc(a, 9, uploadStatus="failed", isDeleted=True),
        _doc(b, 10),
        _doc(b, 11, documentType="Tax Invoice"),
    ]
    await db.documents.insert_many(docs)
    mine = [d for d in docs if d["userId"] == a.id]
    got = await _get(client, a)
    exp = _expected(mine)
    assert {k: got[k] for k in exp} == exp
    assert set(got) == KEYS
    by_type = got["byDocumentType"]
    assert by_type["Tax Invoice"] + by_type["Delivery Challan"] < got["total"]
    live = sorted(
        (d for d in mine if d.get("isDeleted") is not True),
        key=lambda d: (d["createdAt"], d["_id"]),
        reverse=True,
    )[:3]
    assert [r["_id"] for r in got["recent"]] == [str(d["_id"]) for d in live]
    other = {str(d["_id"]) for d in docs if d["userId"] == b.id}
    assert not other & {r["_id"] for r in got["recent"]}


async def test_fewer_than_three_recent(client: Any, db: Any, make_user: Any) -> None:
    u = await make_user()
    docs = [_doc(u, 1), _doc(u, 2)]
    await db.documents.insert_many(docs)
    got = await _get(client, u)
    assert [r["_id"] for r in got["recent"]] == [str(docs[1]["_id"]), str(docs[0]["_id"])]


async def test_recent_ties_tiebreak_id_desc(client: Any, db: Any, make_user: Any) -> None:
    u = await make_user()
    same = datetime(2026, 3, 3, tzinfo=UTC)
    docs = [_doc(u, i, createdAt=same) for i in range(6)]
    docs.append(_doc(u, 50, createdAt=same - DAY))
    await db.documents.insert_many(docs)
    got = await _get(client, u)
    ids = [r["_id"] for r in got["recent"]]
    assert len(ids) == 3
    tied = sorted(docs[:6], key=lambda d: d["_id"], reverse=True)
    assert ids == [str(d["_id"]) for d in tied][:3]


async def test_processed_today_boundaries(client: Any, db: Any, make_user: Any) -> None:
    u = await make_user()
    start, end = _bounds()
    mid = start + timedelta(hours=12)
    cases: list[tuple[dict[str, Any], bool]] = [
        (_doc(u, 1, processedAt=start - timedelta(seconds=1)), False),
        (_doc(u, 2, processedAt=start), True),
        (_doc(u, 3, processedAt=end - timedelta(milliseconds=1)), True),
        (_doc(u, 4, processedAt=end), False),
        (_doc(u, 5, reprocessedAt=mid), True),
        (_doc(u, 6, reprocessedAt=start - DAY), False),
        (_doc(u, 7, updatedAt=mid), True),
        (_doc(u, 8, updatedAt=start - DAY), False),
        (_doc(u, 9, uploadStatus="failed", processedAt=mid), False),
        (_doc(u, 10, uploadStatus="uploaded", processedAt=mid), False),
        # 00:01 IST today is still "yesterday" by the UTC calendar date
        (_doc(u, 11, processedAt=start + timedelta(minutes=1)), True),
        # 00:01 IST tomorrow shares today's UTC date but is not IST today
        (_doc(u, 12, processedAt=end + timedelta(minutes=1)), False),
        (_doc(u, 14, isDeleted=True, processedAt=mid), False),
    ]
    no_ts = _doc(u, 13)
    del no_ts["updatedAt"]
    cases.append((no_ts, False))
    await db.documents.insert_many([c[0] for c in cases])
    got = await _get(client, u)
    assert got["processedToday"] == sum(ok for _, ok in cases) == 5
    assert got["processedToday"] == _expected([c[0] for c in cases])["processedToday"]


async def test_isolation(client: Any, db: Any, make_user: Any) -> None:
    a, b = await make_user(), await make_user()
    mid = _bounds()[0] + timedelta(hours=12)
    await db.documents.insert_many([_doc(b, i, processedAt=mid) for i in range(5)])
    got = await _get(client, a)
    assert got["total"] == 0 and got["processedToday"] == 0 and got["recent"] == []
    assert (await _get(client, b))["total"] == 5


async def test_camel_case_shape(client: Any, db: Any, make_user: Any) -> None:
    u = await make_user()
    await db.documents.insert_one(_doc(u, 1))
    got = await _get(client, u)
    assert set(got) == KEYS
    assert set(got["byDocumentType"]) == {"Tax Invoice", "Delivery Challan"}


async def test_large_account_response_is_small(client: Any, db: Any, make_user: Any) -> None:
    u = await make_user()
    docs = [_doc(u, i) for i in range(3000)]
    for i in range(0, 3000, 1000):
        await db.documents.insert_many(docs[i : i + 1000])
    try:
        res = await client.get("/api/documents/summary", headers=u.headers)
        assert res.status_code == 200
        assert len(res.content) < 10_000
        body = json.loads(res.content)
        assert body["total"] == 3000
        assert len(body["recent"]) <= 3
    finally:
        await db.documents.delete_many({"userId": u.id})
