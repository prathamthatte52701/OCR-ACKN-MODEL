# ruff: noqa: F401, F811
"""Edge cases found by the independent review of Save Again: missing workbook record, a DB error
after the row is written, and keys with XML-illegal characters."""

from typing import Any

import pytest

from app.features.excel import router as excel_router
from app.features.excel.test_save_again_replaces import (  # noqa: F401 - fixtures
    _doc,
    _records,
    _rows,
    _save,
    _save_ok,
    _start,
    _wb,
    clock,
    exports_dir,
)


async def test_missing_workbook_record_still_replaces_by_stored_filename(
    client: Any, db: Any, make_user: Any, exports_dir: Any, clock: Any
) -> None:
    u = await make_user()
    await _start(client, u)
    wb = await _wb(db, u)
    await db.workbooks.delete_one({"_id": wb["_id"]})  # settings still point at the file
    d = await _doc(db, u, "820000901")
    await _save_ok(client, u, d)
    body = await _save_ok(client, u, d)
    assert body["replaced"] == 1 and "staleRowWarning" not in body
    assert await _records(db, d) == 1
    book_rows = await _rows_by_name(exports_dir, u, wb["filename"])
    assert book_rows == ["820000901"]


async def _rows_by_name(exports_dir: Any, user: Any, filename: str) -> list[str]:
    import openpyxl

    from app.features.excel import service as excel_service

    path = exports_dir / f"{excel_service.physical_workbook_filename(user.id, filename)}.xlsx"
    book = openpyxl.load_workbook(path)
    return [str(r[1]) for ws in book for r in ws.iter_rows(min_row=2, values_only=True)]


async def test_db_error_after_the_row_is_written_is_still_a_success(
    client: Any,
    db: Any,
    make_user: Any,
    exports_dir: Any,
    clock: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    u = await make_user()
    await _start(client, u)
    d = await _doc(db, u, "820000902")
    await _save_ok(client, u, d)

    async def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("mongo hiccup")

    monkeypatch.setattr(excel_router, "_collect_old_rows", boom)
    r = await _save(client, u, d)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["replaced"] == 0 and "Save Again" in body["staleRowWarning"]
    assert (await db.documents.find_one({"_id": d}))["exported"] is True
    # the new row is in; the old one is still there until the next Save Again
    assert (await _rows(db, exports_dir, u)).count(("March", "820000902", "05/03/2026")) == 2
    monkeypatch.undo()


async def test_number_with_xml_illegal_character_is_replaced_not_duplicated(
    client: Any, db: Any, make_user: Any, exports_dir: Any, clock: Any
) -> None:
    u = await make_user()
    await _start(client, u)
    d = await _doc(db, u, "AB\x0112345")
    await _save_ok(client, u, d)
    body = await _save_ok(client, u, d)
    assert body["replaced"] == 1 and "staleRowWarning" not in body
    assert len(await _rows(db, exports_dir, u)) == 1
    assert await _records(db, d) == 1
