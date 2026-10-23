"""P1: two workbook names that land on the same physical file ("Bills", "Bills.xlsx", "bills",
" Bills ") must never be creatable side by side - the second create used to replace the first
file and wipe its rows. There is no rename/restore endpoint, so create is the only entry point.

New names (workbook_key / WorkbookExistsError) are referenced lazily so the behaviour tests still
run (and fail) against the old code."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import openpyxl
import pytest

from app.features.excel import router as excel_router
from app.features.excel import service as excel_service
from app.features.excel.test_bulk_save import _bulk, _doc

YEAR = excel_service.current_period()[0]
EXISTS_MSG = "A workbook with this name already exists."


@pytest.fixture
def exports_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(excel_service, "EXPORT_DIR", tmp_path)
    return tmp_path


async def _create(client: Any, user: Any, name: str) -> Any:
    return await client.post(
        "/api/documents/new-excel-file", headers=user.headers, json={"filename": name}
    )


def _path(user: Any, name: str) -> Path:
    return excel_service.file_path(excel_service.physical_workbook_filename(user.id, name))


def _numbers(path: Path) -> list[str]:
    book = openpyxl.load_workbook(path)
    return [
        str(row[1]) for ws in book for row in ws.iter_rows(min_row=2, values_only=True) if row[1]
    ]


async def _save_one(client: Any, db: Any, user: Any, number: str) -> None:
    r = await _bulk(client, user, [await _doc(db, user, number)])
    assert r.status_code == 200 and r.json()["succeeded"], r.text


@pytest.mark.parametrize(
    "second", ["Bills.xlsx", "bills", " Bills ", "bills.XLSX", "BILLS", "Bills .xlsx"]
)
async def test_same_file_name_is_refused_and_first_workbook_keeps_its_rows(
    client: Any, db: Any, make_user: Any, exports_dir: Path, second: str
) -> None:
    u = await make_user()
    assert (await _create(client, u, "Bills")).status_code == 200
    await _save_one(client, db, u, "820000001")
    before = _path(u, "Bills").read_bytes()

    r = await _create(client, u, second)
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == EXISTS_MSG

    assert _path(u, "Bills").read_bytes() == before  # file untouched
    assert _numbers(_path(u, "Bills")) == ["820000001"]  # row still there
    assert await db.workbooks.count_documents({"userId": u.id}) == 1
    assert len(list(exports_dir.glob("*.xlsx"))) == 1


async def test_reverse_order_bills_xlsx_then_bills_is_refused(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    u = await make_user()
    assert (await _create(client, u, "Bills.xlsx")).status_code == 200
    await _save_one(client, db, u, "820000002")
    assert (await _create(client, u, "Bills")).status_code == 400
    assert _numbers(_path(u, "Bills.xlsx")) == ["820000002"]


async def test_double_xlsx_is_a_different_file_and_neither_damages_the_other(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    # Only ONE trailing .xlsx is stripped: "Bills.xlsx.xlsx" has key "bills.xlsx", a different
    # file from "Bills". Invariant: same physical file (case-insensitive) => refused, else both ok.
    u = await make_user()
    assert (await _create(client, u, "Bills")).status_code == 200
    await _save_one(client, db, u, "820000003")
    a, b = _path(u, "Bills"), _path(u, "Bills.xlsx.xlsx")
    assert a.name.lower() != b.name.lower()
    r = await _create(client, u, "Bills.xlsx.xlsx")
    assert r.status_code == 200, r.text
    assert _numbers(a) == ["820000003"] and b.exists() and _numbers(b) == []
    # and now it collides with itself under every spelling
    assert (await _create(client, u, "BILLS.XLSX.xlsx")).status_code == 400
    assert _numbers(a) == ["820000003"]


@pytest.mark.parametrize("name", ["Bills", "bills.xlsx", "Q1 Bills"])
async def test_invariant_same_physical_path_means_refused(
    client: Any, make_user: Any, exports_dir: Path, name: str
) -> None:
    u = await make_user()
    assert (await _create(client, u, "Bills")).status_code == 200
    same = _path(u, name).name.lower() == _path(u, "Bills").name.lower()
    r = await _create(client, u, name)
    assert r.status_code == (400 if same else 200)
    assert _path(u, "Bills").exists()


@pytest.mark.parametrize("name", ["Bad.", "a/b", "a..b", "   ", ""])
async def test_schema_rejects_bad_names(
    client: Any, make_user: Any, exports_dir: Path, name: str
) -> None:
    u = await make_user()
    r = await _create(client, u, name)
    assert r.status_code in (400, 422)
    assert list(exports_dir.glob("*.xlsx")) == []


async def test_dot_xlsx_alone_never_overwrites_anything(
    client: Any, make_user: Any, exports_dir: Path
) -> None:
    u = await make_user()
    assert (await _create(client, u, "Bills")).status_code == 200
    before = _path(u, "Bills").read_bytes()
    r = await _create(client, u, ".xlsx")
    assert r.status_code in (200, 400, 422)
    assert _path(u, "Bills").read_bytes() == before
    if r.status_code == 200:  # allowed: it is its own file, and a second try is refused
        assert (await _create(client, u, ".XLSX")).status_code == 400


async def test_two_users_can_both_create_the_same_name(
    client: Any, make_user: Any, exports_dir: Path
) -> None:
    a, b = await make_user(), await make_user()
    assert (await _create(client, a, "Bills")).status_code == 200
    assert (await _create(client, b, "Bills")).status_code == 200
    assert _path(a, "Bills").exists() and _path(b, "Bills").exists()
    assert (await _create(client, b, "bills.xlsx")).status_code == 400
    assert _path(a, "Bills").exists()


async def test_normal_new_name_still_works(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    u = await make_user()
    assert (await _create(client, u, "Bills")).status_code == 200
    r = await _create(client, u, "Salaries")
    assert r.status_code == 200 and r.json()["filename"] == "Salaries"
    assert await db.workbooks.count_documents({"userId": u.id}) == 2
    assert await db.workbooks.count_documents({"userId": u.id, "isActive": True}) == 1


async def test_orphan_file_with_no_record_is_refused_and_untouched(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    u = await make_user()
    path = _path(u, "Bills")
    path.write_bytes(b"precious orphan bytes")
    r = await _create(client, u, "Bills")
    assert r.status_code == 400 and r.json()["detail"] == EXISTS_MSG
    assert path.read_bytes() == b"precious orphan bytes"
    assert await db.workbooks.count_documents({"userId": u.id}) == 0
    # a different-case spelling hits the same file on Windows; it must not be replaced either
    r2 = await _create(client, u, "Bills.xlsx")
    assert r2.status_code == 400 and path.read_bytes() == b"precious orphan bytes"


async def test_legacy_record_still_opens_appends_and_downloads(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    u = await make_user()
    now = datetime.now(UTC)
    await excel_service.create_workbook(
        excel_service.physical_workbook_filename(u.id, "Legacy.xlsx")
    )
    rec = await db.workbooks.insert_one(
        {
            "userId": u.id,
            "year": YEAR,
            "filename": "Legacy.xlsx",
            "isActive": True,
            "archivedAt": None,
            "createdAt": now,
            "updatedAt": now,
        }
    )
    await db.settings.insert_one(
        {
            "userId": u.id,
            "key": "excelState",
            "activeWorkbookName": "Legacy.xlsx",
            "activeYear": YEAR,
            "updatedAt": now,
        }
    )
    await _save_one(client, db, u, "820000004")
    assert _numbers(_path(u, "Legacy.xlsx")) == ["820000004"]
    dl = await client.get(
        "/api/documents/workbook/download",
        headers=u.headers,
        params={"workbookId": str(rec.inserted_id)},
    )
    assert dl.status_code == 200 and dl.content[:2] == b"PK"
    # and the legacy name is protected from a colliding create
    assert (await _create(client, u, "legacy")).status_code == 400
    assert _numbers(_path(u, "Legacy.xlsx")) == ["820000004"]


async def test_parallel_creates_of_one_name_exactly_one_wins(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    u = await make_user()
    rs = await asyncio.gather(*[_create(client, u, n) for n in ("Bills", "Bills.xlsx", "bills")])
    assert sorted(r.status_code for r in rs) == [200, 400, 400]
    assert await db.workbooks.count_documents({"userId": u.id}) == 1
    assert len(list(exports_dir.glob("*.xlsx"))) == 1
    openpyxl.load_workbook(next(exports_dir.glob("*.xlsx")))  # intact, loadable


async def test_create_workbook_exclusive_refuses_existing_file_without_touching_it(
    exports_dir: Path,
) -> None:
    target = exports_dir / "u_Bills.xlsx"
    target.write_bytes(b"keep me")
    with pytest.raises(excel_service.WorkbookExistsError):  # lazy: old code has no such class
        await excel_service.create_workbook("u_bills.xlsx", exclusive=True)
    assert target.read_bytes() == b"keep me"
    await excel_service.create_workbook("u_Fresh", exclusive=True)
    assert (exports_dir / "u_Fresh.xlsx").exists()


@pytest.mark.parametrize(
    "a,b,same",
    [
        ("Bills", "Bills.xlsx", True),
        ("Bills", "bills", True),
        ("Bills", " Bills ", True),
        ("Bills", "bills.XLSX", True),
        ("BILLS .xlsx", "bills", True),
        ("Bills.xlsx.xlsx", "Bills.xlsx", False),
        ("Bills.xlsx.xlsx", "BILLS.XLSX.xlsx", True),
        ("Bills.xlsx.xlsx", "Bills", False),
        (".xlsx", "", True),
        ("Café", "Café", True),
        ("Bills", "Bills2", False),
        ("a/b", "a_b", True),
    ],
)
def test_workbook_key_truth_table(a: str, b: str, same: bool) -> None:
    key = excel_service.workbook_key  # lazy: old code has no workbook_key
    assert (key(a) == key(b)) is same


async def test_year_workbook_auto_name_skips_existing_record(
    db: Any, make_user: Any, exports_dir: Path
) -> None:
    u = await make_user()
    now = datetime.now(UTC)
    await db.workbooks.insert_one(
        {
            "userId": u.id,
            "year": 2025 + 50,
            "filename": "excel 2025.XLSX",
            "isActive": False,
            "archivedAt": now,
            "createdAt": now,
            "updatedAt": now,
        }
    )
    await excel_service.create_workbook(
        excel_service.physical_workbook_filename(u.id, "Excel 2025")
    )
    rec = await excel_router._create_year_workbook(db, u.id, 2025, "January")
    assert rec["filename"] == "Excel 2025 (2)"
    assert _path(u, "Excel 2025").exists() and _path(u, "Excel 2025 (2)").exists()


async def test_year_workbook_auto_name_skips_orphan_file(
    db: Any, make_user: Any, exports_dir: Path
) -> None:
    u = await make_user()
    orphan = _path(u, "Excel 2025")
    orphan.write_bytes(b"orphan")
    rec = await excel_router._create_year_workbook(db, u.id, 2025, "January")
    assert rec["filename"] == "Excel 2025 (2)"
    assert orphan.read_bytes() == b"orphan"
