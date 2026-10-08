"""T6/T7: Export History is private per user; workbook downloads are owned-only."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import openpyxl
import pytest
from bson import ObjectId

from app.features.excel import service as excel_service


@pytest.fixture
def exports_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(excel_service, "EXPORT_DIR", tmp_path)
    return tmp_path


async def _workbook(db: Any, exports_dir: Path, user: Any, name: str) -> ObjectId:
    now = datetime.now(UTC)
    res = await db.workbooks.insert_one(
        {
            "userId": user.id,
            "year": 2026,
            "filename": name,
            "isActive": True,
            "createdAt": now,
            "updatedAt": now,
        }
    )
    wb = openpyxl.Workbook()
    wb.active["A1"] = f"owner:{user.id}"
    wb.save(exports_dir / f"{excel_service.physical_workbook_filename(user.id, name)}.xlsx")
    return res.inserted_id


async def _export_row(db: Any, user: Any, workbook_id: ObjectId, number: str) -> None:
    now = datetime.now(UTC)
    await db.exportedrows.insert_one(
        {
            "userId": user.id,
            "documentId": ObjectId(),
            "workbookId": workbook_id,
            "documentType": "Delivery Challan",
            "number": number,
            "date": "01/01/2026",
            "exportedAt": now,
            "createdAt": now,
            "updatedAt": now,
        }
    )


async def test_export_history_shows_only_own_rows_and_no_owner(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    a, b = await make_user(), await make_user()
    wa = await _workbook(db, exports_dir, a, "BooksA")
    wb_ = await _workbook(db, exports_dir, b, "BooksB")
    await _export_row(db, a, wa, "820000001")
    await _export_row(db, b, wb_, "820000002")

    r = await client.get("/api/documents/export-history", headers=a.headers)
    assert r.status_code == 200
    rows = r.json()["exports"]
    assert [x["number"] for x in rows] == ["820000001"]
    assert "owner" not in rows[0]
    # nothing about user B leaks anywhere in the response
    assert b.email not in r.text and b.username not in r.text and str(b.id) not in r.text


async def test_export_history_empty_for_new_user(client: Any, make_user: Any) -> None:
    u = await make_user()
    r = await client.get("/api/documents/export-history", headers=u.headers)
    assert r.status_code == 200 and r.json()["exports"] == []


async def test_workbook_download_own_ok_other_users_404(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    a, b = await make_user(), await make_user()
    wa = await _workbook(db, exports_dir, a, "BooksA")
    wb_ = await _workbook(db, exports_dir, b, "BooksB")

    own = await client.get(
        f"/api/documents/export-history/workbook/{wa}/download", headers=a.headers
    )
    assert own.status_code == 200 and own.content[:2] == b"PK"
    other = await client.get(
        f"/api/documents/export-history/workbook/{wb_}/download", headers=a.headers
    )
    assert other.status_code == 404
    other2 = await client.get(
        f"/api/documents/workbook/download?workbookId={wb_}", headers=a.headers
    )
    assert other2.status_code == 404
    own2 = await client.get(f"/api/documents/workbook/download?workbookId={wa}", headers=a.headers)
    assert own2.status_code == 200


async def test_download_refuses_name_that_would_steer_to_another_users_file(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    a, b = await make_user(), await make_user()
    await _workbook(db, exports_dir, b, "Secret")
    # attacker's own record whose display name tries to point at B's physical file
    evil = f"x/{b.id}_Secret"
    now = datetime.now(UTC)
    res = await db.workbooks.insert_one(
        {
            "userId": a.id,
            "year": 2026,
            "filename": evil,
            "isActive": True,
            "createdAt": now,
            "updatedAt": now,
        }
    )
    r = await client.get(
        f"/api/documents/workbook/download?workbookId={res.inserted_id}", headers=a.headers
    )
    assert r.status_code == 404  # sanitized name resolves to A's own (missing) file, never B's
    assert b"owner:" not in r.content


async def test_admin_still_sees_all_exports(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    admin = await make_user(role="admin")
    a, b = await make_user(), await make_user()
    await _export_row(db, a, await _workbook(db, exports_dir, a, "A1"), "820000011")
    await _export_row(db, b, await _workbook(db, exports_dir, b, "B1"), "820000012")
    r = await client.get("/api/admin/exports", headers=admin.headers)
    assert r.status_code == 200 and r.json()["totalExports"] == 2


async def _many_exports(db: Any, user: Any, workbook_id: ObjectId, count: int) -> None:
    from datetime import timedelta

    base = datetime.now(UTC)
    await db.exportedrows.insert_many(
        [
            {
                "userId": user.id,
                "documentId": ObjectId(),
                "workbookId": workbook_id,
                "documentType": "Delivery Challan",
                "number": f"8200{i:05d}",
                "date": "01/01/2026",
                "exportedAt": base + timedelta(seconds=i),
                "createdAt": base,
                "updatedAt": base,
            }
            for i in range(count)
        ]
    )


async def test_export_history_is_paginated_30_per_page_newest_first(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    a, b = await make_user(), await make_user()
    wa = await _workbook(db, exports_dir, a, "BooksA")
    await _many_exports(db, a, wa, 65)
    await _many_exports(db, b, await _workbook(db, exports_dir, b, "BooksB"), 40)

    p1 = (await client.get("/api/documents/export-history", headers=a.headers)).json()
    assert p1["totalExports"] == 65 and p1["totalPages"] == 3 and p1["currentPage"] == 1
    assert len(p1["exports"]) == 30
    assert p1["exports"][0]["number"] == "820000064"  # newest first
    p2 = (await client.get("/api/documents/export-history?page=2", headers=a.headers)).json()
    p3 = (await client.get("/api/documents/export-history?page=3", headers=a.headers)).json()
    assert (len(p2["exports"]), len(p3["exports"])) == (30, 5)
    numbers = [r["number"] for r in p1["exports"] + p2["exports"] + p3["exports"]]
    assert len(set(numbers)) == 65  # no row repeated or skipped across pages
    assert p1["exports"][0]["workbook"] == {"filename": "BooksA", "year": 2026}


async def test_export_history_page_bounds_and_limit_cap(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    a = await make_user()
    await _many_exports(db, a, await _workbook(db, exports_dir, a, "BooksA"), 35)
    past = (await client.get("/api/documents/export-history?page=99", headers=a.headers)).json()
    assert past["currentPage"] == 2 and len(past["exports"]) == 5  # clamped to the last page
    for query in ("page=0", "page=-3", "limit=0", "limit=-5"):
        r = await client.get(f"/api/documents/export-history?{query}", headers=a.headers)
        assert r.status_code == 200 and len(r.json()["exports"]) >= 1, query
    big = (
        await client.get("/api/documents/export-history?limit=1000000", headers=a.headers)
    ).json()
    assert len(big["exports"]) == 35  # capped at 100, all 35 fit
    junk = await client.get("/api/documents/export-history?page=abc", headers=a.headers)
    assert junk.status_code == 422


async def test_export_history_pagination_never_mixes_users(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    a, b = await make_user(), await make_user()
    await _many_exports(db, a, await _workbook(db, exports_dir, a, "BooksA"), 31)
    await _many_exports(db, b, await _workbook(db, exports_dir, b, "BooksB"), 31)
    for page in (1, 2):
        r = await client.get(f"/api/documents/export-history?page={page}", headers=a.headers)
        assert r.json()["totalExports"] == 31
        assert b.email not in r.text and str(b.id) not in r.text
