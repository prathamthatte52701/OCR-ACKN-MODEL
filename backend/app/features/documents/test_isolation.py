"""T10: two-user IDOR sweep over every documents/ and excel/ route that takes an
id, a filename or a list of ids. User A is the attacker holding B's ids/names.
Expected everywhere: 404 (or an empty/skipped result), never B's data. Admin can
still reach everything (with audit entries); rejected/pending tokens get 403.

Route -> where the userId scope applies (verified by reading the code):
  GET    /documents                       list filter {"userId": caller}
  GET    /documents/training-stats        base_filter userId
  GET    /documents/my-activity           auditlogs filter userId + doc lookup userId
  GET    /documents/{id}                  _get_owned_document(userId)
  GET    /documents/{id}/download         _get_owned_document(userId)
  POST   /documents/download-all          per-id find_one userId (others skipped)
  POST   /documents/{id}/reprocess        _get_owned_document(userId)
  DELETE /documents/{id}                  _get_owned_document(userId)
  POST   /documents/{id}/purge-file       _get_owned_document(userId)
  PATCH  /documents/{id}/correct          _get_owned_document(userId)
  POST   /documents/{id}/save             find_one userId
  POST   /documents/bulk-save             per-id find_one userId (others fail per-doc)
  GET    /documents/workbooks             workbooks filter userId
  GET    /documents/workbook/download     workbook lookup userId + _owned_workbook_file
  GET    /documents/export-history        exportedrows filter userId
  GET    /documents/export-history/workbook/{id}/download   workbook lookup userId
  POST   /documents/new-excel-file        per-user workbooks/settings only
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import openpyxl
import pytest
from bson import ObjectId

from app.features.documents.gridfs_service import upload_buffer
from app.features.excel import service as excel_service


@pytest.fixture
def exports_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(excel_service, "EXPORT_DIR", tmp_path)
    return tmp_path


async def _doc(db: Any, owner: Any, number: str = "820000001") -> ObjectId:
    now = datetime.now(UTC)
    file_id = await upload_buffer(b"%PDF-1.4 fake", "x.pdf", "application/pdf")
    res = await db.documents.insert_one(
        {
            "userId": owner.id,
            "autoName": "n",
            "originalFilename": "x.pdf",
            "mimeType": "application/pdf",
            "size": 13,
            "uploadStatus": "processed",
            "documentType": "Delivery Challan",
            "number": number,
            "date": "01/01/2026",
            "numberConfidence": 100,
            "dateConfidence": 100,
            "gridFsFileId": file_id,
            "edited": False,
            "exported": False,
            "isDeleted": False,
            "filePurged": False,
            "createdAt": now,
            "updatedAt": now,
        }
    )
    return res.inserted_id


async def _workbook(db: Any, exports_dir: Path, owner: Any, name: str) -> ObjectId:
    now = datetime.now(UTC)
    res = await db.workbooks.insert_one(
        {
            "userId": owner.id,
            "year": 2026,
            "filename": name,
            "isActive": True,
            "createdAt": now,
            "updatedAt": now,
        }
    )
    wb = openpyxl.Workbook()
    wb.active["A1"] = f"secret-of-{owner.id}"
    wb.save(exports_dir / f"{excel_service.physical_workbook_filename(owner.id, name)}.xlsx")
    return res.inserted_id


async def test_idor_every_id_route_returns_404_for_other_users_document(
    client: Any, db: Any, make_user: Any
) -> None:
    a, b = await make_user(), await make_user()
    b_doc = await _doc(db, b)
    h = a.headers

    assert (await client.get(f"/api/documents/{b_doc}", headers=h)).status_code == 404
    assert (await client.get(f"/api/documents/{b_doc}/download", headers=h)).status_code == 404
    assert (await client.post(f"/api/documents/{b_doc}/reprocess", headers=h)).status_code == 404
    assert (await client.post(f"/api/documents/{b_doc}/purge-file", headers=h)).status_code == 404
    assert (await client.post(f"/api/documents/{b_doc}/save", headers=h)).status_code == 404
    r = await client.patch(
        f"/api/documents/{b_doc}/correct", headers=h, json={"field": "number", "value": "820999999"}
    )
    assert r.status_code == 404
    assert (await client.delete(f"/api/documents/{b_doc}", headers=h)).status_code == 404

    # B's document is completely untouched
    doc = await db.documents.find_one({"_id": b_doc})
    assert doc["number"] == "820000001" and not doc["isDeleted"] and not doc["filePurged"]
    assert await db.corrections.count_documents({}) == 0


async def test_idor_lists_and_stats_never_include_other_users_data(
    client: Any, db: Any, make_user: Any
) -> None:
    a, b = await make_user(), await make_user()
    await _doc(db, b, "820000077")
    for path in (
        "/api/documents",
        "/api/documents?page=1&limit=100",
        "/api/documents?number=820000077",
        "/api/documents/export-history",
        "/api/documents/workbooks",
        "/api/documents/my-activity",
    ):
        r = await client.get(path, headers=a.headers)
        assert r.status_code == 200, path
        assert "820000077" not in r.text and str(b.id) not in r.text, path
    stats = (await client.get("/api/documents/training-stats", headers=a.headers)).json()
    assert stats == {"trainedCount": 0, "correctedCount": 0}


async def test_idor_download_all_and_bulk_save_skip_foreign_ids(
    client: Any, db: Any, make_user: Any
) -> None:
    a, b = await make_user(), await make_user()
    b_doc = await _doc(db, b)
    r = await client.post(
        "/api/documents/download-all", headers=a.headers, json={"documentIds": [str(b_doc)]}
    )
    # nothing of B's can be zipped: either nothing to download, or an empty bundle
    assert r.headers.get("x-download-included", "0") == "0"
    assert b"%PDF" not in r.content
    r = await client.post(
        "/api/documents/bulk-save", headers=a.headers, json={"documentIds": [str(b_doc)]}
    )
    assert r.status_code in (200, 400, 404)
    assert (await db.documents.find_one({"_id": b_doc}))["exported"] is False
    assert await db.exportedrows.count_documents({}) == 0


async def test_idor_workbook_ids_names_and_path_steering(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    a, b = await make_user(), await make_user()
    b_wb = await _workbook(db, exports_dir, b, "Bills")
    h = a.headers
    assert (
        await client.get(f"/api/documents/workbook/download?workbookId={b_wb}", headers=h)
    ).status_code == 404
    assert (
        await client.get(f"/api/documents/export-history/workbook/{b_wb}/download", headers=h)
    ).status_code == 404

    # A tries to *create* workbooks whose names steer at B's physical file
    for evil in (f"x/{b.id}_Bills", f"..\\{b.id}_Bills", "..", "../x", f"{b.id}_Bills/.."):
        r = await client.post("/api/documents/new-excel-file", headers=h, json={"filename": evil})
        assert r.status_code in (400, 422, 200), evil
    # B's file is intact and still B's
    f = exports_dir / f"{excel_service.physical_workbook_filename(b.id, 'Bills')}.xlsx"
    assert openpyxl.load_workbook(f).active["A1"].value == f"secret-of-{b.id}"
    # and none of A's downloads can ever return B's content
    for wb in [w async for w in db.workbooks.find({"userId": a.id})]:
        r = await client.get(f"/api/documents/workbook/download?workbookId={wb['_id']}", headers=h)
        assert f"secret-of-{b.id}".encode() not in r.content


async def test_idor_same_workbook_name_for_two_users_stays_separate(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    a, b = await make_user(), await make_user()
    assert (
        await client.post(
            "/api/documents/new-excel-file", headers=a.headers, json={"filename": "Bills"}
        )
    ).status_code == 200
    assert (
        await client.post(
            "/api/documents/new-excel-file", headers=b.headers, json={"filename": "Bills"}
        )
    ).status_code == 200
    names = sorted(p.name for p in exports_dir.glob("*.xlsx"))
    assert names == sorted([f"{a.id}_Bills.xlsx", f"{b.id}_Bills.xlsx"])


async def test_admin_reaches_everything_with_audit(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    admin, b = await make_user(role="admin"), await make_user()
    b_doc = await _doc(db, b)
    b_wb = await _workbook(db, exports_dir, b, "Bills")
    r = await client.get(f"/api/admin/documents?userId={b.id}", headers=admin.headers)
    assert r.status_code == 200 and str(b_doc) in r.text
    assert (await client.get("/api/admin/exports", headers=admin.headers)).status_code == 200
    r = await client.get(f"/api/admin/workbooks/{b_wb}/download", headers=admin.headers)
    assert r.status_code == 200 and r.content[:2] == b"PK"
    assert await db.auditlogs.count_documents({"action": "admin_access"}) == 3


@pytest.mark.parametrize("state", ["pending", "rejected"])
async def test_non_approved_token_gets_403_on_every_route(
    client: Any, db: Any, make_user: Any, state: str
) -> None:
    owner = await make_user()
    doc = await _doc(db, owner)
    u = await make_user(status=state)
    h = u.headers
    gets = [
        "/api/auth/me",
        "/api/documents",
        f"/api/documents/{doc}",
        f"/api/documents/{doc}/download",
        "/api/documents/training-stats",
        "/api/documents/my-activity",
        "/api/documents/workbooks",
        "/api/documents/workbook/download",
        "/api/documents/export-history",
    ]
    for path in gets:
        assert (await client.get(path, headers=h)).status_code == 403, path
    assert (await client.post(f"/api/documents/{doc}/reprocess", headers=h)).status_code == 403
    assert (await client.post(f"/api/documents/{doc}/save", headers=h)).status_code == 403
    assert (await client.delete(f"/api/documents/{doc}", headers=h)).status_code == 403
    r = await client.post("/api/documents/new-excel-file", headers=h, json={"filename": "X"})
    assert r.status_code == 403
    r = await client.patch(
        f"/api/documents/{doc}/correct", headers=h, json={"field": "number", "value": "1"}
    )
    assert r.status_code == 403
    assert (await client.get("/api/admin/users", headers=h)).status_code == 403
