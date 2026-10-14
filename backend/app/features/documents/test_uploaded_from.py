"""GET /documents?uploadedFrom= : createdAt >= an ISO-8601 instant computed by the client."""

from datetime import UTC, datetime, timedelta
from typing import Any

BOUNDARY = datetime(2026, 10, 12, 18, 30, 0, tzinfo=UTC)  # 00:00 IST on 13 Oct 2026
ISO = "2026-10-12T18:30:00.000Z"


async def _seed(
    db: Any, owner: Any, number: str, created: datetime, dtype: str = "Delivery Challan"
) -> None:
    doc: dict[str, Any] = {
        "userId": owner.id,
        "autoName": "n",
        "originalFilename": "x.pdf",
        "mimeType": "application/pdf",
        "size": 1,
        "uploadStatus": "processed",
        "documentType": dtype,
        "date": "05/10/2026",
        "edited": False,
        "exported": False,
        "isDeleted": False,
        "createdAt": created,
        "updatedAt": created,
    }
    doc["taxInvoiceNo" if dtype == "Tax Invoice" else "number"] = number
    await db.documents.insert_one(doc)


async def _numbers(client: Any, user: Any, **params: Any) -> set[str]:
    res = await client.get("/api/documents", headers=user.headers, params={"page": 1, **params})
    assert res.status_code == 200, res.text
    return {d.get("taxInvoiceNo") or d.get("number") for d in res.json()["documents"]}


async def test_boundary_is_inclusive_and_exact(db: Any, client: Any, make_user: Any) -> None:
    u = await make_user()
    await _seed(db, u, "BEFORE", BOUNDARY - timedelta(seconds=1))
    await _seed(db, u, "AT", BOUNDARY)
    await _seed(db, u, "AFTER", BOUNDARY + timedelta(seconds=1))
    assert await _numbers(client, u, uploadedFrom=ISO) == {"AT", "AFTER"}
    assert await _numbers(client, u) == {"BEFORE", "AT", "AFTER"}
    # an offset form of the same instant behaves the same
    assert await _numbers(client, u, uploadedFrom="2026-10-13T00:00:00+05:30") == {"AT", "AFTER"}


async def test_combines_with_number_month_type_and_range(
    db: Any, client: Any, make_user: Any
) -> None:
    u = await make_user()
    now = datetime.now(UTC)
    await _seed(db, u, "ABC-OLD", now - timedelta(days=5))
    await _seed(db, u, "ABC-NEW", now - timedelta(hours=1))
    await _seed(db, u, "XYZ-NEW", now - timedelta(hours=1))
    await _seed(db, u, "ABC-TAX", now - timedelta(hours=1), "Tax Invoice")
    since = (now - timedelta(days=1)).isoformat()
    assert await _numbers(client, u, uploadedFrom=since) == {"ABC-NEW", "XYZ-NEW", "ABC-TAX"}
    assert await _numbers(client, u, uploadedFrom=since, number="ABC") == {"ABC-NEW", "ABC-TAX"}
    assert await _numbers(
        client, u, uploadedFrom=since, number="ABC", documentType="Tax Invoice"
    ) == {"ABC-TAX"}
    assert await _numbers(client, u, uploadedFrom=since, month="2026-10", number="ABC") == {
        "ABC-NEW",
        "ABC-TAX",
    }
    assert await _numbers(client, u, uploadedFrom=since, month="2026-09") == set()
    # both filters: the later cutoff wins (range=week is 7d, uploadedFrom is 1d)
    assert await _numbers(client, u, uploadedFrom=since, range="week") == {
        "ABC-NEW",
        "XYZ-NEW",
        "ABC-TAX",
    }


async def test_bad_values_are_clean_400_or_ignored(db: Any, client: Any, make_user: Any) -> None:
    u = await make_user()
    await _seed(db, u, "ONE", datetime.now(UTC))
    too_far = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    for bad in (
        "garbage",
        "1999-12-31T23:59:59Z",
        "2026-10-13",  # no time/offset
        "2026-10-13T00:00:00",  # naive
        too_far,
        "9999-01-01T00:00:00Z",
        "x" * 500,
    ):
        res = await client.get(
            "/api/documents", headers=u.headers, params={"page": 1, "uploadedFrom": bad}
        )
        assert res.status_code == 400, bad
        assert res.json()["detail"] == "Invalid date filter."
    assert await _numbers(client, u, uploadedFrom="") == {"ONE"}  # empty = no filter
    assert await _numbers(client, u, uploadedFrom="   ") == {"ONE"}


async def test_old_range_param_still_works(db: Any, client: Any, make_user: Any) -> None:
    u = await make_user()
    now = datetime.now(UTC)
    await _seed(db, u, "RECENT", now - timedelta(hours=2))
    await _seed(db, u, "OLD", now - timedelta(days=3))
    assert await _numbers(client, u, range="today") == {"RECENT"}
    assert await _numbers(client, u, range="week") == {"RECENT", "OLD"}


async def test_other_users_documents_never_leak(db: Any, client: Any, make_user: Any) -> None:
    a, b = await make_user(), await make_user()
    await _seed(db, b, "THEIRS", datetime.now(UTC))
    assert await _numbers(client, a, uploadedFrom=ISO) == set()


async def test_chip_flow_new_doc_vs_last_month_doc(db: Any, client: Any, make_user: Any) -> None:
    """Manual-check scenario: a fresh upload is in every chip; one dated last month only in Year."""
    from datetime import timezone

    ist = timezone(timedelta(hours=5, minutes=30))
    now_local = datetime.now(ist)
    day = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    starts = {
        "today": day,
        "week": day - timedelta(days=now_local.weekday()),
        "month": day.replace(day=1),
        "year": day.replace(month=1, day=1),
    }
    last_month = starts["month"] - timedelta(days=1)  # the day before this month began
    u = await make_user()
    await _seed(db, u, "FRESH", datetime.now(UTC))
    await _seed(db, u, "OLD", last_month.astimezone(UTC))
    for name, start in starts.items():
        got = await _numbers(client, u, uploadedFrom=start.astimezone(UTC).isoformat())
        if name == "year" and last_month.year == now_local.year:
            assert got == {"FRESH", "OLD"}, name
        else:
            assert got == {"FRESH"}, name
