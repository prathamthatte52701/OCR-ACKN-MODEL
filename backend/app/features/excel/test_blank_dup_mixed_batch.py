"""Break test for N1/N4: one bulk batch of 30 mixed documents. Counts must add up, a blank document
never gets a workbook row or an exportedrows record, and duplicates only warn."""

from pathlib import Path
from typing import Any

import pytest

from app.features.excel import service as excel_service
from app.features.excel.test_blank_and_duplicate import BLANK, _ti
from app.features.excel.test_bulk_save import YEAR, _bulk, _doc, _workbook


@pytest.fixture
def exports_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(excel_service, "EXPORT_DIR", tmp_path)
    return tmp_path


async def test_mixed_batch_of_30(client: Any, db: Any, make_user: Any, exports_dir: Path) -> None:
    u = await make_user()
    await _workbook(client, u)
    ids: list[Any] = []
    blanks: set[str] = set()
    for i in range(30):
        kind = i % 6
        if kind == 0:  # blank Delivery Challan (empty / whitespace / None)
            d = await _doc(db, u, "x")
            await db.documents.update_one(
                {"_id": d}, {"$set": {"number": ["", "   ", None][(i // 6) % 3]}}
            )
            blanks.add(str(d))
        elif kind == 1:  # Tax Invoice with both numbers blank
            d = await _ti(db, u, "  ", None)
            blanks.add(str(d))
        elif kind == 2:  # Tax Invoice with only the reference blank: allowed
            d = await _ti(db, u, f"G00277{i:05d}", None)
        elif kind == 3:  # duplicate pair (same number and date)
            d = await _doc(db, u, "8500001")
        else:  # normal
            d = await _doc(db, u, f"86{i:05d}")
        ids.append(d)

    r = await _bulk(client, u, ids)
    assert r.status_code == 200
    body = r.json()
    failed = {f["documentId"] for f in body["failed"]}
    assert failed == blanks
    assert all(f["reason"] == BLANK for f in body["failed"])
    assert len(body["succeeded"]) + len(body["failed"]) == 30
    assert set(body["succeeded"]) == {str(i) for i in ids} - blanks
    assert body["message"] == f"{len(body['succeeded'])}/30 saved successfully."

    for b in blanks:
        d = next(i for i in ids if str(i) == b)
        assert await db.exportedrows.count_documents({"documentId": d}) == 0
        assert (await db.documents.find_one({"_id": d}))["exported"] is False
    saved = len(body["succeeded"])
    assert await db.exportedrows.count_documents({"userId": u.id}) == saved
    rows = sum(
        1 for p in exports_dir.glob("*.xlsx") for _ in _data_rows(p)  # one row per saved document
    )
    assert rows == saved
    assert YEAR  # the workbook year the batch used


def _data_rows(path: Path) -> list[tuple]:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True)
    return [r for ws in wb for r in ws.iter_rows(min_row=2, values_only=True) if any(r)]
