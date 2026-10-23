"""N3 admin/user correct parity, N6 orphan corrections, N9 correct-vs-reprocess race,
N13 orphan upload file. Only the "_test" database is used."""

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from bson import ObjectId

from app.features.admin import router as admin_router
from app.features.documents import correction_rules
from app.features.documents import router as docs_router

TI = "Tax Invoice"
CHANGED = "This document changed while you were editing. Please reload and try again."


async def _doc(db: Any, owner: Any, status: str = "processed", **extra: Any) -> ObjectId:
    now = datetime.now(UTC)
    res = await db.documents.insert_one(
        {
            "userId": owner.id,
            "documentType": TI,
            "originalFilename": "a.png",
            "uploadStatus": status,
            "processingRunId": "run-old",
            "taxInvoiceNo": "OLD1",
            "referenceNo": None,
            "date": None,
            "number": None,
            "isDeleted": False,
            "edited": False,
            "createdAt": now,
            "updatedAt": now,
            **extra,
        }
    )
    return res.inserted_id


def _urls(doc_id: ObjectId) -> dict[str, str]:
    return {"user": f"/api/documents/{doc_id}/correct", "admin": f"/api/admin/documents/{doc_id}"}


async def _who(make_user: Any, route: str) -> Any:
    return await make_user(role="admin" if route == "admin" else "user")


async def _patch(
    client: Any, route: str, acct: Any, doc_id: ObjectId, field: str, value: str
) -> Any:
    return await client.patch(
        _urls(doc_id)[route], headers=acct.headers, json={"field": field, "value": value}
    )


# ---------------- N3: both routes share the rules ----------------


@pytest.mark.parametrize("route", ["user", "admin"])
async def test_same_rules_on_both_routes(client: Any, db: Any, make_user: Any, route: str) -> None:
    owner = await make_user()
    acct = owner if route == "user" else await make_user(role="admin")
    doc_id = await _doc(db, owner)
    long_value = "A" * 41
    r = await _patch(client, route, acct, doc_id, "taxInvoiceNo", long_value)
    assert r.status_code == 400 and "max 40" in r.json()["detail"]
    r = await _patch(client, route, acct, doc_id, "taxInvoiceNo", "=HYPERLINK(x)")
    assert r.status_code == 400
    r = await _patch(client, route, acct, doc_id, "date", "99/99/2020")
    assert r.status_code == 400 and "year 2000-2100" in r.json()["detail"]
    assert await db.corrections.count_documents({}) == 0
    r = await _patch(client, route, acct, doc_id, "taxInvoiceNo", "INV-7")
    assert r.status_code == 200


@pytest.mark.parametrize("route", ["user", "admin"])
async def test_still_processing_is_409_on_both_routes(
    client: Any, db: Any, make_user: Any, route: str
) -> None:
    owner = await make_user()
    acct = owner if route == "user" else await make_user(role="admin")
    doc_id = await _doc(db, owner, status="uploaded")
    r = await _patch(client, route, acct, doc_id, "taxInvoiceNo", "INV-7")
    assert r.status_code == 409 and "still being processed" in r.json()["detail"]
    assert await db.corrections.count_documents({}) == 0
    assert (await db.documents.find_one({"_id": doc_id}))["taxInvoiceNo"] == "OLD1"


# ---------------- N9: conditional write ----------------


def _simulate_reprocess_between_read_and_write(monkeypatch: pytest.MonkeyPatch, db: Any) -> None:
    """A Reprocess claim lands after the route read+validated the document, before its write."""
    real_apply = correction_rules.apply_correction

    async def apply_after_claim(db_: Any, doc: dict, field: str, value: str) -> bool:
        await db_.documents.update_one(
            {"_id": doc["_id"]},
            {
                "$set": {
                    "uploadStatus": "uploaded",
                    "processingRunId": "run-new",
                    "taxInvoiceNo": None,
                    "edited": False,
                }
            },
        )
        return await real_apply(db_, doc, field, value)

    monkeypatch.setattr(docs_router, "apply_correction", apply_after_claim)
    monkeypatch.setattr(admin_router, "apply_correction", apply_after_claim)


@pytest.mark.parametrize("route", ["user", "admin"])
async def test_reprocess_between_read_and_write_refuses_correction(
    client: Any, db: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    owner = await make_user()
    acct = owner if route == "user" else await make_user(role="admin")
    doc_id = await _doc(db, owner)
    _simulate_reprocess_between_read_and_write(monkeypatch, db)
    r = await _patch(client, route, acct, doc_id, "taxInvoiceNo", "INV-7")
    assert r.status_code == 409 and r.json()["detail"] == CHANGED
    assert await db.corrections.count_documents({}) == 0
    assert await db.auditlogs.count_documents({"action": "document_corrected"}) == 0
    d = await db.documents.find_one({"_id": doc_id})
    assert d["processingRunId"] == "run-new" and d["uploadStatus"] == "uploaded"
    assert d["taxInvoiceNo"] is None and d["edited"] is False  # reprocess result intact


@pytest.mark.parametrize("route", ["user", "admin"])
async def test_missing_run_id_still_correctable(
    client: Any, db: Any, make_user: Any, route: str
) -> None:
    owner = await make_user()
    acct = owner if route == "user" else await make_user(role="admin")
    doc_id = await _doc(db, owner)
    await db.documents.update_one({"_id": doc_id}, {"$unset": {"processingRunId": ""}})
    r = await _patch(client, route, acct, doc_id, "taxInvoiceNo", "INV-8")
    assert r.status_code == 200
    assert await db.corrections.count_documents({"documentId": doc_id}) == 1


async def test_50_concurrent_correct_vs_reprocess(client: Any, db: Any, make_user: Any) -> None:
    owner = await make_user()
    ids = [await _doc(db, owner) for _ in range(50)]

    async def claim(doc_id: ObjectId) -> None:
        await asyncio.sleep(0)
        await db.documents.update_one(
            {"_id": doc_id},
            {
                "$set": {
                    "uploadStatus": "uploaded",
                    "processingRunId": "run-new",
                    "taxInvoiceNo": None,
                    "edited": False,
                }
            },
        )

    results = await asyncio.gather(
        *[_patch(client, "user", owner, i, "taxInvoiceNo", "NEWVAL") for i in ids],
        *[claim(i) for i in ids],
    )
    codes = [r.status_code for r in results[:50]]
    assert set(codes) <= {200, 409}
    for doc_id, code in zip(ids, codes, strict=True):
        d = await db.documents.find_one({"_id": doc_id})
        rows = await db.corrections.count_documents({"documentId": doc_id})
        assert rows == (1 if code == 200 else 0)
        # a refused or overtaken correction must never survive a reprocess claim
        assert d["uploadStatus"] == "uploaded" and d["taxInvoiceNo"] is None


# ---------------- N6: corrections removed with the document ----------------


async def _with_correction(db: Any, owner: Any) -> ObjectId:
    doc_id = await _doc(db, owner)
    await db.corrections.insert_one({"documentId": doc_id, "fieldKey": "number"})
    return doc_id


async def test_user_delete_removes_corrections(client: Any, db: Any, make_user: Any) -> None:
    u = await make_user()
    keep = await _with_correction(db, u)
    gone = await _with_correction(db, u)
    r = await client.delete(f"/api/documents/{gone}", headers=u.headers)
    assert r.status_code == 200
    assert await db.corrections.count_documents({"documentId": gone}) == 0
    assert await db.corrections.count_documents({"documentId": keep}) == 1


async def test_admin_delete_removes_corrections(client: Any, db: Any, make_user: Any) -> None:
    u, a = await make_user(), await make_user(role="admin")
    gone = await _with_correction(db, u)
    r = await client.delete(f"/api/admin/documents/{gone}", headers=a.headers)
    assert r.status_code == 200
    assert await db.corrections.count_documents({"documentId": gone}) == 0


async def test_purge_removes_corrections(db: Any, make_user: Any) -> None:
    u, other = await make_user(), await make_user()
    gone = await _with_correction(db, u)
    keep = await _with_correction(db, other)
    await admin_router._execute_purge({"userId": u.id})
    assert await db.corrections.count_documents({"documentId": gone}) == 0
    assert await db.corrections.count_documents({"documentId": keep}) == 1


# ---------------- N13: no orphan upload file ----------------


def _png() -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (50, 50), "white").save(buf, format="PNG")
    return buf.getvalue()


async def _gridfs_count(db: Any) -> int:
    return await db["fs.files"].count_documents({})


async def test_insert_failure_deletes_gridfs_file(
    db: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    u = await make_user()
    before = await _gridfs_count(db)

    class Boom:
        async def insert_one(self, *_a: Any, **_k: Any) -> Any:
            raise RuntimeError("insert down")

    class FakeDb:
        documents = Boom()

    monkeypatch.setattr(docs_router, "get_database", lambda: FakeDb())
    with pytest.raises(RuntimeError, match="insert down"):
        await docs_router._validate_and_store(_png(), "image/png", "a.png", TI, u.id)
    assert await _gridfs_count(db) == before


async def test_insert_failure_and_delete_failure_records_orphan(
    db: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    u = await make_user()

    class Boom:
        async def insert_one(self, *_a: Any, **_k: Any) -> Any:
            raise RuntimeError("insert down")

    class FakeDb:
        documents = Boom()

    recorded: list[Any] = []

    async def bad_delete(_fid: Any) -> None:
        raise OSError("delete down")

    async def rec(fid: Any, doc_id: Any, user_id: Any, context: str, exc: Exception) -> None:
        recorded.append((fid, doc_id, user_id, context, type(exc).__name__))

    monkeypatch.setattr(docs_router, "get_database", lambda: FakeDb())
    monkeypatch.setattr(docs_router, "delete_file", bad_delete)
    monkeypatch.setattr(docs_router, "record_orphaned_file", rec)
    with pytest.raises(RuntimeError, match="insert down"):
        await docs_router._validate_and_store(_png(), "image/png", "a.png", TI, u.id)
    assert len(recorded) == 1 and recorded[0][2] == u.id and recorded[0][4] == "OSError"
