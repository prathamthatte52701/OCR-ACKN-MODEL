"""GET /documents?month= filters by the document's own DD/MM/YYYY date, not upload time."""

from datetime import UTC, datetime
from typing import Any

import pytest


async def _seed(
    db: Any, owner: Any, number: str, date: Any, dtype: str = "Delivery Challan"
) -> None:
    now = datetime.now(UTC)
    doc: dict[str, Any] = {
        "userId": owner.id,
        "autoName": "n",
        "originalFilename": "x.pdf",
        "mimeType": "application/pdf",
        "size": 1,
        "uploadStatus": "processed",
        "documentType": dtype,
        "edited": False,
        "exported": False,
        "isDeleted": False,
        "createdAt": now,
        "updatedAt": now,
    }
    doc["taxInvoiceNo" if dtype == "Tax Invoice" else "number"] = number
    if date != "MISSING":
        doc["date"] = date
    await db.documents.insert_one(doc)


async def _list(client: Any, user: Any, **params: Any) -> Any:
    return await client.get("/documents", headers=user.headers, params={"page": 1, **params})


async def _numbers(client: Any, user: Any, **params: Any) -> set[str]:
    res = await _list(client, user, **params)
    assert res.status_code == 200, res.text
    return {d.get("taxInvoiceNo") or d.get("number") for d in res.json()["documents"]}


@pytest.fixture
async def seeded(db: Any, make_user: Any) -> Any:
    a = await make_user()
    b = await make_user()
    await _seed(db, a, "C-OCT-1", "05/10/2026")
    await _seed(db, a, "C-OCT-2", "31/10/2026")
    await _seed(db, a, "T-OCT-1", "15/10/2026", "Tax Invoice")
    await _seed(db, a, "C-SEP-1", "30/09/2026")
    await _seed(db, a, "C-OCT-2025", "05/10/2025")
    await _seed(db, a, "C-NULL", None)
    await _seed(db, a, "C-MISSING", "MISSING")
    await _seed(db, a, "C-ODD", "5/10/2026")
    await _seed(db, b, "B-OCT-1", "05/10/2026")
    return a


async def test_month_matches_only_that_month_both_types(client: Any, seeded: Any) -> None:
    assert await _numbers(client, seeded, month="2026-10") == {"C-OCT-1", "C-OCT-2", "T-OCT-1"}


async def test_documenttype_narrows_within_month(client: Any, seeded: Any) -> None:
    got = await _numbers(client, seeded, month="2026-10", documentType="Tax Invoice")
    assert got == {"T-OCT-1"}


async def test_month_none_returns_missing_null_and_odd_dates(client: Any, seeded: Any) -> None:
    assert await _numbers(client, seeded, month="none") == {"C-NULL", "C-MISSING", "C-ODD"}


@pytest.mark.parametrize(
    "bad", ["2026-13", "2026-1", "1999-10", "2101-01", "abc", "2026-10-01", ".*"]
)
async def test_invalid_month_is_400(client: Any, seeded: Any, bad: str) -> None:
    res = await _list(client, seeded, month=bad)
    assert res.status_code == 400
    assert res.json()["detail"] == "Invalid month."


async def test_month_and_number_search_intersect(client: Any, seeded: Any) -> None:
    # "OCT" matches C-OCT-1, C-OCT-2, T-OCT-1 and C-OCT-2025; the month must still apply
    got = await _numbers(client, seeded, month="2026-10", number="OCT-2")
    assert got == {"C-OCT-2"}
    got = await _numbers(client, seeded, month="2026-10", number="OCT")
    assert got == {"C-OCT-1", "C-OCT-2", "T-OCT-1"}


async def test_other_users_documents_never_appear(client: Any, seeded: Any) -> None:
    assert "B-OCT-1" not in await _numbers(client, seeded, month="2026-10")
    assert "B-OCT-1" not in await _numbers(client, seeded)
