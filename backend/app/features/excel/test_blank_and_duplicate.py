"""N1: a document with no number cannot be saved; N4: same type+number+date already in Excel only
warns (reuses staleRowWarning / staleWarnings)."""

from pathlib import Path
from typing import Any

import pytest
from bson import ObjectId

from app.features.excel import service as excel_service
from app.features.excel.test_bulk_save import YEAR, _bulk, _doc, _workbook

BLANK = "Number not read. Reprocess the document, or type the number, then save."
DUP = (
    "Another document with the same number and date is already in Excel. "
    "Check that this is not a duplicate."
)


@pytest.fixture
def exports_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(excel_service, "EXPORT_DIR", tmp_path)
    return tmp_path


async def _ti(db: Any, owner: Any, tax: Any, ref: Any, date: str = f"05/10/{YEAR}") -> ObjectId:
    doc_id = await _doc(db, owner, "x", date=date)
    await db.documents.update_one(
        {"_id": doc_id},
        {
            "$set": {
                "documentType": "Tax Invoice",
                "taxInvoiceNo": tax,
                "referenceNo": ref,
                "number": None,
            }
        },
    )
    return doc_id


async def test_single_save_blank_dc_is_400_and_creates_nothing(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    u = await make_user()  # no workbook, no settings
    for blank in ("", "   ", None):
        d = await _doc(db, u, "x")
        await db.documents.update_one({"_id": d}, {"$set": {"number": blank}})
        r = await client.post(f"/api/documents/{d}/save", headers=u.headers)
        assert r.status_code == 400 and r.json()["detail"] == BLANK
    assert list(exports_dir.iterdir()) == []
    assert await db.workbooks.count_documents({"userId": u.id}) == 0
    assert await db.exportedrows.count_documents({"userId": u.id}) == 0


async def test_tax_invoice_blank_only_when_both_empty(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    u = await make_user()
    await _workbook(client, u)
    both = await _ti(db, u, " ", "")
    one = await _ti(db, u, "", "REF1")
    other = await _ti(db, u, "INV1", None)
    r = await client.post(f"/api/documents/{both}/save", headers=u.headers)
    assert r.status_code == 400 and r.json()["detail"] == BLANK
    for ok in (one, other):
        assert (
            await client.post(f"/api/documents/{ok}/save", headers=u.headers)
        ).status_code == 200


async def test_bulk_blank_fails_only_that_document(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    u = await make_user()
    await _workbook(client, u)
    a = await _doc(db, u, "8300001")
    blank = await _doc(db, u, "x")
    await db.documents.update_one({"_id": blank}, {"$set": {"number": ""}})
    b = await _doc(db, u, "8300002")
    body = (await _bulk(client, u, [a, blank, b])).json()
    assert body["succeeded"] == [str(a), str(b)]
    assert body["failed"] == [{"documentId": str(blank), "reason": BLANK}]
    assert body["message"] == "2/3 saved successfully."
    assert await db.exportedrows.count_documents({"documentId": blank}) == 0
    assert await db.exportedrows.count_documents({}) == 2


async def test_save_again_of_blanked_document_is_blocked(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    u = await make_user()
    await _workbook(client, u)
    d = await _doc(db, u, "8300003")
    assert (await client.post(f"/api/documents/{d}/save", headers=u.headers)).status_code == 200
    await db.documents.update_one({"_id": d}, {"$set": {"number": ""}})
    r = await client.post(f"/api/documents/{d}/save", headers=u.headers)
    assert r.status_code == 400 and r.json()["detail"] == BLANK


async def test_duplicate_warns_but_saves(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    u = await make_user()
    await _workbook(client, u)
    first = await _doc(db, u, "8400001")
    second = await _doc(db, u, "8400001")
    diff_date = await _doc(db, u, "8400001", date=f"06/10/{YEAR}")
    r1 = await client.post(f"/api/documents/{first}/save", headers=u.headers)
    assert "staleRowWarning" not in r1.json()
    r2 = await client.post(f"/api/documents/{second}/save", headers=u.headers)
    assert r2.status_code == 200 and DUP in r2.json()["staleRowWarning"]
    r3 = await client.post(f"/api/documents/{diff_date}/save", headers=u.headers)
    assert "staleRowWarning" not in r3.json()
    # Save Again of the first: its own earlier record is not a duplicate, the second's is
    again = await client.post(f"/api/documents/{first}/save", headers=u.headers)
    assert DUP in again.json()["staleRowWarning"]
    solo = await _doc(db, u, "8400009")
    await client.post(f"/api/documents/{solo}/save", headers=u.headers)
    again = await client.post(f"/api/documents/{solo}/save", headers=u.headers)
    assert "staleRowWarning" not in again.json()


async def test_duplicate_other_user_ignored_and_bulk_same_batch(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    u, v = await make_user(), await make_user()
    await _workbook(client, u)
    await _workbook(client, v)
    mine = await _doc(db, u, "8500001")
    theirs = await _doc(db, v, "8500001")
    await client.post(f"/api/documents/{theirs}/save", headers=v.headers)
    a = await _doc(db, u, "8500002")
    b = await _doc(db, u, "8500002")
    body = (await _bulk(client, u, [mine, a, b])).json()
    assert len(body["succeeded"]) == 3
    assert [w["documentId"] for w in body["staleWarnings"]] == [str(b)]
    assert DUP in body["staleWarnings"][0]["message"]
