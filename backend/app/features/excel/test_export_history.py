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


# ---------------------------------------------------------------------------
# GET /documents/workbooks/download-all : one zip with ALL of the caller's workbooks
# ---------------------------------------------------------------------------
import io  # noqa: E402
import tempfile  # noqa: E402
import zipfile  # noqa: E402

ZIP_URL = "/api/documents/workbooks/download-all"
ZIP_PREFIX = "workbooks-zip-"


async def _wb(
    db: Any, exports_dir: Path, user: Any, name: str, year: int, *, with_file: bool = True
) -> ObjectId:
    now = datetime.now(UTC)
    res = await db.workbooks.insert_one(
        {
            "userId": user.id,
            "year": year,
            "filename": name,
            "isActive": False,
            "createdAt": now,
            "updatedAt": now,
        }
    )
    if with_file:
        book = openpyxl.Workbook()
        book.active["A1"] = f"owner:{user.id}:{name}:{year}"
        book.save(exports_dir / f"{excel_service.physical_workbook_filename(user.id, name)}.xlsx")
    return res.inserted_id


def _zip_of(res: Any) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(res.content))


def _leftover_zip_temps() -> set[str]:
    return {p.name for p in Path(tempfile.gettempdir()).glob(f"{ZIP_PREFIX}*")}


async def test_zip_has_all_own_workbooks_as_valid_xlsx(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    a = await make_user()
    await _wb(db, exports_dir, a, "Bills_2025", 2025)
    await _wb(db, exports_dir, a, "Bills_2026", 2026)
    res = await client.get(ZIP_URL, headers=a.headers)
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("application/zip")
    assert res.headers["x-download-included"] == "2"
    assert res.headers["x-download-skipped"] == "0"
    disposition = res.headers["content-disposition"]
    assert "workbooks.zip" in disposition
    assert a.email not in disposition and a.username not in disposition
    zf = _zip_of(res)
    assert sorted(zf.namelist()) == ["Bills_2025.xlsx", "Bills_2026.xlsx"]
    for name in zf.namelist():
        book = openpyxl.load_workbook(io.BytesIO(zf.read(name)))  # a real, openable workbook
        assert str(book.active["A1"].value).startswith(f"owner:{a.id}:")


async def test_zip_never_contains_another_users_workbooks(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    a, b = await make_user(), await make_user()
    await _wb(db, exports_dir, a, "BooksA1", 2025)
    await _wb(db, exports_dir, a, "BooksA2", 2026)
    await _wb(db, exports_dir, b, "BooksB", 2026)
    res = await client.get(ZIP_URL, headers=b.headers)
    assert res.status_code == 200
    zf = _zip_of(res)
    assert zf.namelist() == ["BooksB.xlsx"]
    assert f"owner:{b.id}:" in str(
        openpyxl.load_workbook(io.BytesIO(zf.read("BooksB.xlsx"))).active["A1"].value
    )
    res_a = await client.get(ZIP_URL, headers=a.headers)
    assert sorted(_zip_of(res_a).namelist()) == ["BooksA1.xlsx", "BooksA2.xlsx"]


async def test_missing_file_is_skipped_and_reported(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    a = await make_user()
    await _wb(db, exports_dir, a, "Present", 2025)
    await _wb(db, exports_dir, a, "Gone", 2026, with_file=False)
    res = await client.get(ZIP_URL, headers=a.headers)
    assert res.status_code == 200, res.text
    assert res.headers["x-download-included"] == "1"
    assert res.headers["x-download-skipped"] == "1"
    assert "Gone" in res.headers["x-download-skipped-names"]
    assert _zip_of(res).namelist() == ["Present.xlsx"]


async def test_all_files_missing_gives_a_clean_error(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    a = await make_user()
    await _wb(db, exports_dir, a, "Gone1", 2025, with_file=False)
    before = _leftover_zip_temps()
    res = await client.get(ZIP_URL, headers=a.headers)
    assert res.status_code == 404
    assert isinstance(res.json()["detail"], str)
    assert _leftover_zip_temps() == before


async def test_zero_workbooks_gives_a_clean_error(client: Any, make_user: Any) -> None:
    a = await make_user()
    res = await client.get(ZIP_URL, headers=a.headers)
    assert res.status_code == 404
    assert "workbook" in res.json()["detail"].lower()


async def test_zip_route_needs_login(client: Any) -> None:
    assert (await client.get(ZIP_URL)).status_code == 401


async def test_duplicate_workbook_names_are_made_unique_in_the_zip(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    a = await make_user()
    # two records with the same display name (same file on disk): entries must not overwrite
    await _wb(db, exports_dir, a, "Books", 2025)
    await _wb(db, exports_dir, a, "Books", 2026, with_file=False)
    res = await client.get(ZIP_URL, headers=a.headers)
    assert res.status_code == 200
    names = _zip_of(res).namelist()
    assert len(names) == len(set(names)) == 2
    assert all(n.endswith(".xlsx") for n in names)


async def test_odd_workbook_names_cannot_escape_the_zip_or_the_folder(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    a = await make_user()
    for i, name in enumerate(["../../evil", "a/b..c", "..\\x", "name with spaces & more", "...."]):
        # a name with a backslash cannot even be created as a file here: its record stays file-less
        await _wb(db, exports_dir, a, name, 2000 + i, with_file="\\" not in name)
    res = await client.get(ZIP_URL, headers=a.headers)
    assert res.status_code == 200, res.text
    names = _zip_of(res).namelist()
    assert len(names) == 4, (names, res.headers["x-download-skipped-names"])
    assert res.headers["x-download-skipped"] == "1"
    for n in names:
        assert ".." not in n and "/" not in n and "\\" not in n and not n.startswith(".")
        assert n.endswith(".xlsx")
    assert len(set(names)) == len(names)


async def test_twenty_workbooks_twice_leaves_no_temp_files(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    a = await make_user()
    for i in range(20):
        await _wb(db, exports_dir, a, f"Books{i:02d}", 2000 + i)
    before = _leftover_zip_temps()
    for _ in range(2):
        res = await client.get(ZIP_URL, headers=a.headers)
        assert res.status_code == 200
        assert len(_zip_of(res).namelist()) == 20
    assert _leftover_zip_temps() == before


async def test_workbook_download_by_id_returns_that_exact_workbook(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    a = await make_user()
    w25 = await _wb(db, exports_dir, a, "Bills_2025", 2025)
    w26 = await _wb(db, exports_dir, a, "Bills_2026", 2026)
    for wid, name in ((w25, "Bills_2025"), (w26, "Bills_2026")):
        res = await client.get(
            f"/api/documents/workbook/download?workbookId={wid}", headers=a.headers
        )
        assert res.status_code == 200
        assert f"{name}.xlsx" in res.headers["content-disposition"]
        book = openpyxl.load_workbook(io.BytesIO(res.content))
        assert f":{name}:" in str(book.active["A1"].value)  # the right file, not the other year's
    bad = await client.get(
        "/api/documents/workbook/download?workbookId=not-an-id", headers=a.headers
    )
    assert bad.status_code == 400
    assert (
        await client.get(f"/api/documents/workbook/download?workbookId={w25}")
    ).status_code == 401
