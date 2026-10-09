"""Stage 2: POST /documents/bulk-save ("Save All") - dedupe, cap, blocked-by-workbook,
per-document failures, exportedrows == rows written, date fallback reporting."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import openpyxl
import pytest
from bson import ObjectId

from app.features.excel import router as excel_router
from app.features.excel import service as excel_service

YEAR = excel_service.current_period()[0]


@pytest.fixture
def exports_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(excel_service, "EXPORT_DIR", tmp_path)
    return tmp_path


async def _doc(
    db: Any,
    owner: Any,
    number: str,
    status: str = "processed",
    date: str | None = f"05/10/{YEAR}",
) -> ObjectId:
    now = datetime.now(UTC)
    res = await db.documents.insert_one(
        {
            "userId": owner.id,
            "autoName": number,
            "originalFilename": f"{number}.pdf",
            "mimeType": "application/pdf",
            "size": 10,
            "uploadStatus": status,
            "documentType": "Delivery Challan",
            "number": number,
            "date": date,
            "edited": False,
            "exported": False,
            "isDeleted": False,
            "filePurged": True,
            "createdAt": now,
            "updatedAt": now,
        }
    )
    return res.inserted_id


async def _workbook(client: Any, user: Any, name: str = "Book") -> None:
    r = await client.post(
        "/api/documents/new-excel-file", headers=user.headers, json={"filename": name}
    )
    assert r.status_code == 200, r.text


async def _bulk(client: Any, user: Any, ids: list[Any]) -> Any:
    return await client.post(
        "/api/documents/bulk-save",
        headers=user.headers,
        json={"documentIds": [str(i) for i in ids]},
    )


def _xlsx_rows(exports_dir: Path, user: Any, name: str = "Book") -> list[tuple[str, tuple]]:
    path = exports_dir / f"{excel_service.physical_workbook_filename(user.id, name)}.xlsx"
    book = openpyxl.load_workbook(path)
    return [
        (ws.title, tuple(row)) for ws in book for row in ws.iter_rows(min_row=2, values_only=True)
    ]


async def test_only_processed_saved_failed_and_unprocessed_reported(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    u = await make_user()
    await _workbook(client, u)
    good = [await _doc(db, u, f"8200000{i}") for i in range(3)]
    bad = [await _doc(db, u, "FAILED1", "failed"), await _doc(db, u, "UPLOADED1", "uploaded")]
    r = await _bulk(client, u, [good[0], bad[0], good[1], bad[1], good[2]])
    body = r.json()
    assert r.status_code == 200 and body["blocked"] is None
    assert body["succeeded"] == [str(g) for g in good]
    assert sorted(f["documentId"] for f in body["failed"]) == sorted(str(b) for b in bad)
    assert all(f["reason"] == "Document has not been processed yet." for f in body["failed"])
    assert body["message"] == "3/5 saved successfully."
    # server truth: exportedrows == succeeded == rows in the xlsx
    assert await db.exportedrows.count_documents({"userId": u.id}) == 3
    assert len(_xlsx_rows(exports_dir, u)) == 3
    assert await db.documents.count_documents({"userId": u.id, "exported": True}) == 3


async def test_duplicate_ids_in_one_request_write_one_row(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    u = await make_user()
    await _workbook(client, u)
    d = await _doc(db, u, "820000001")
    other = await _doc(db, u, "820000002")
    body = (await _bulk(client, u, [d, d, other, d, other])).json()
    assert body["succeeded"] == [str(d), str(other)]  # first occurrence order kept
    assert body["message"] == "2/2 saved successfully."
    assert await db.exportedrows.count_documents({}) == 2
    assert len(_xlsx_rows(exports_dir, u)) == 2


async def test_cap_101_ids_is_400_and_nothing_written(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    u = await make_user()
    await _workbook(client, u)
    r = await _bulk(client, u, [ObjectId() for _ in range(101)])
    assert r.status_code == 400 and "at most 100" in r.json()["detail"]
    ok = await _bulk(client, u, [ObjectId() for _ in range(100)])  # exactly 100 is allowed
    assert ok.status_code == 200 and len(ok.json()["failed"]) == 100
    assert await db.exportedrows.count_documents({}) == 0
    # far past the schema's own ceiling it is still rejected cleanly (422), never a 500
    assert (await _bulk(client, u, [ObjectId() for _ in range(201)])).status_code in (400, 422)


async def test_no_active_workbook_blocks_and_stops_the_loop(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    u = await make_user()  # never created a workbook
    ids = [await _doc(db, u, f"8200010{i}") for i in range(4)]
    unprocessed = await _doc(db, u, "FAILED1", "failed")
    r = await _bulk(client, u, [unprocessed, *ids])
    body = r.json()
    assert r.status_code == 200
    assert body["blocked"]["error"] == "NO_ACTIVE_WORKBOOK" and body["blocked"]["year"] == YEAR
    assert body["succeeded"] == []
    assert body["notAttempted"] == [str(i) for i in ids]  # the blocked one and everything after
    assert [f["documentId"] for f in body["failed"]] == [str(unprocessed)]
    assert await db.exportedrows.count_documents({}) == 0
    assert list(exports_dir.glob("*.xlsx")) == []  # nothing partially written
    assert await db.documents.count_documents({"exported": True}) == 0


async def test_year_mismatch_blocks_with_need_new_workbook(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    u = await make_user()
    await _workbook(client, u)
    await db.settings.update_one(
        {"userId": u.id, "key": "excelState"}, {"$set": {"activeYear": YEAR - 1}}
    )
    ids = [await _doc(db, u, f"8200020{i}") for i in range(3)]
    body = (await _bulk(client, u, ids)).json()
    assert body["blocked"]["error"] == "NEED_NEW_WORKBOOK" and body["blocked"]["year"] == YEAR
    assert body["succeeded"] == [] and body["notAttempted"] == [str(i) for i in ids]
    assert await db.exportedrows.count_documents({}) == 0 and _xlsx_rows(exports_dir, u) == []


async def test_blocked_then_one_retry_with_only_unsaved_ids_has_no_duplicates(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    u = await make_user()
    ids = [await _doc(db, u, f"8200030{i}") for i in range(3)]
    first = (await _bulk(client, u, ids)).json()
    assert first["blocked"]["error"] == "NO_ACTIVE_WORKBOOK"
    await _workbook(client, u)  # what the frontend does after the name prompt
    retry = (await _bulk(client, u, [uuid for uuid in first["notAttempted"]])).json()
    assert retry["blocked"] is None and len(retry["succeeded"]) == 3
    assert await db.exportedrows.count_documents({}) == 3
    assert len(_xlsx_rows(exports_dir, u)) == 3


async def test_another_users_id_fails_404_and_their_data_is_untouched(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    a, b = await make_user(), await make_user()
    await _workbook(client, a)
    mine = await _doc(db, a, "820000401")
    theirs = await _doc(db, b, "820000402")
    body = (await _bulk(client, a, [mine, theirs])).json()
    assert body["succeeded"] == [str(mine)]
    assert body["failed"] == [{"documentId": str(theirs), "reason": "Document not found."}]
    assert (await db.documents.find_one({"_id": theirs}))["exported"] is False
    assert await db.exportedrows.count_documents({"userId": b.id}) == 0
    assert await db.exportedrows.count_documents({}) == 1


async def test_locked_file_fails_one_document_others_still_saved(
    client: Any, db: Any, make_user: Any, exports_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    u = await make_user()
    await _workbook(client, u)
    ids = [await _doc(db, u, n) for n in ("820000501", "LOCKME", "820000503")]
    real_append = excel_service.append_row

    async def flaky(filename: str, month: str, row: dict) -> Path:
        if row["number"] == "LOCKME":
            raise excel_service.FileLockedError("raw lock text")
        return await real_append(filename, month, row)

    monkeypatch.setattr(excel_service, "append_row", flaky)
    body = (await _bulk(client, u, ids)).json()
    assert body["succeeded"] == [str(ids[0]), str(ids[2])]
    assert body["failed"] == [{"documentId": str(ids[1]), "reason": excel_router.FILE_BUSY_MESSAGE}]
    assert (
        excel_router.FILE_BUSY_MESSAGE
        == "The Excel file is busy or open. Close it in Excel and try again."
    )
    assert await db.exportedrows.count_documents({}) == 2
    assert len(_xlsx_rows(exports_dir, u)) == 2


async def test_unexpected_error_on_one_document_does_not_abort_the_batch(
    client: Any, db: Any, make_user: Any, exports_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    u = await make_user()
    await _workbook(client, u)
    ids = [await _doc(db, u, n) for n in ("820000601", "BOOM", "820000603")]
    real_append = excel_service.append_row

    async def boom(filename: str, month: str, row: dict) -> Path:
        if row["number"] == "BOOM":
            raise RuntimeError("disk exploded")
        return await real_append(filename, month, row)

    monkeypatch.setattr(excel_service, "append_row", boom)
    r = await _bulk(client, u, ids)
    body = r.json()
    assert r.status_code == 200 and len(body["succeeded"]) == 2
    assert body["failed"] == [
        {"documentId": str(ids[1]), "reason": "Could not save this document."}
    ]
    assert "disk exploded" not in r.text


async def test_missing_or_unreadable_date_is_listed_in_date_fallback(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    u = await make_user()
    await _workbook(client, u)
    fine = await _doc(db, u, "820000701", date=f"12/10/{YEAR}")
    none = await _doc(db, u, "820000702", date=None)
    junk = await _doc(db, u, "820000703", date="99/99/9999")
    body = (await _bulk(client, u, [fine, none, junk])).json()
    assert body["succeeded"] == [str(fine), str(none), str(junk)]
    assert body["dateFallback"] == [str(none), str(junk)]
    sheets = {title for title, _ in _xlsx_rows(exports_dir, u)}
    current_month = excel_service.current_period()[1]
    assert sheets == {
        "October",
        current_month,
    }  # fine one in October, the others in "today's" month


async def test_october_dated_documents_land_in_the_october_sheet(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    u = await make_user()
    await _workbook(client, u)
    ids = [await _doc(db, u, f"8200008{i}", date=f"0{i + 1}/10/{YEAR}") for i in range(3)]
    body = (await _bulk(client, u, ids)).json()
    assert len(body["succeeded"]) == 3 and body["dateFallback"] == []
    assert {title for title, _ in _xlsx_rows(exports_dir, u)} == {"October"}


async def test_single_save_still_works_and_reports_date_fallback_flag(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    u = await make_user()
    await _workbook(client, u)
    d = await _doc(db, u, "820000901")
    r = await client.post(f"/api/documents/{d}/save", headers=u.headers)
    assert r.status_code == 200 and r.json()["message"] == "Excel file appended successfully."
    assert r.json()["worksheet"] == "October" and r.json()["dateFallback"] is False
    bad = await _doc(db, u, "FAILED2", "failed")
    r2 = await client.post(f"/api/documents/{bad}/save", headers=u.headers)
    assert r2.status_code == 400 and r2.json()["detail"] == "Document has not been processed yet."
