"""Oversized-image rejection on every path + the recovery retry cap. OCR is mocked."""

import asyncio
import io
from typing import Any

import fitz
from bson import ObjectId
from PIL import Image

from app.core.image_limits import IMAGE_TOO_LARGE_TEMPLATE
from app.core.test_image_limits import png_header
from app.features.documents import router as docs_router
from app.features.ocr import pipeline

BOMB = png_header(40000, 40000)
EXPECTED = IMAGE_TOO_LARGE_TEMPLATE.format(mp=1600)


def _png(size: tuple[int, int] = (200, 100)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (250, 250, 250)).save(buf, format="PNG")
    return buf.getvalue()


def _mock_ocr(monkeypatch: Any) -> list[Any]:
    calls: list[Any] = []

    async def fake(doc_id: Any, *_: Any) -> None:
        calls.append(doc_id)

    monkeypatch.setattr(docs_router, "process_document", fake)
    return calls


async def test_single_upload_oversized_is_400_and_stores_nothing(
    db: Any, client: Any, make_user: Any, monkeypatch: Any
) -> None:
    calls = _mock_ocr(monkeypatch)
    u = await make_user()
    res = await client.post(
        "/api/documents/upload",
        headers=u.headers,
        files={"document": ("big.png", BOMB, "image/png")},
        data={"documentType": "Tax Invoice"},
    )
    assert res.status_code == 400
    assert res.json()["detail"] == EXPECTED
    assert await db.documents.count_documents({}) == 0
    assert await db["fs.files"].count_documents({}) == 0
    assert calls == []


async def test_single_upload_oversized_pdf_is_400(
    db: Any, client: Any, make_user: Any, monkeypatch: Any
) -> None:
    _mock_ocr(monkeypatch)
    u = await make_user()
    pdf = fitz.open()
    pdf.new_page(width=14400, height=14400)
    res = await client.post(
        "/api/documents/upload",
        headers=u.headers,
        files={"document": ("big.pdf", pdf.tobytes(), "application/pdf")},
        data={"documentType": "Tax Invoice"},
    )
    assert res.status_code == 400
    assert "PDF page is too large" in res.json()["detail"]
    assert await db.documents.count_documents({}) == 0


async def test_bulk_one_oversized_two_processed(
    db: Any, client: Any, make_user: Any, monkeypatch: Any
) -> None:
    calls = _mock_ocr(monkeypatch)
    u = await make_user()
    res = await client.post(
        "/api/documents/bulk-upload",
        headers=u.headers,
        files=[
            ("documents", ("a.png", _png(), "image/png")),
            ("documents", ("big.png", BOMB, "image/png")),
            ("documents", ("c.png", _png((300, 200)), "image/png")),
        ],
        data={"documentTypes": ["Tax Invoice", "Tax Invoice", "Delivery Challan"]},
    )
    assert res.status_code == 201
    results = res.json()["results"]
    assert [r.get("originalFilename") for r in results if "error" in r] == ["big.png"]
    assert [r["error"] for r in results if "error" in r] == [EXPECTED]
    assert sum("document" in r for r in results) == 2
    assert len(calls) == 2
    assert await db.documents.count_documents({}) == 2


async def test_normal_image_accepted(
    db: Any, client: Any, make_user: Any, monkeypatch: Any
) -> None:
    calls = _mock_ocr(monkeypatch)
    u = await make_user()
    res = await client.post(
        "/api/documents/upload",
        headers=u.headers,
        files={"document": ("ok.png", _png((4000, 3000)), "image/png")},  # 12 MP
        data={"documentType": "Tax Invoice"},
    )
    assert res.status_code == 201
    assert len(calls) == 1


async def _insert_doc(db: Any, status: str = "uploaded", **extra: Any) -> ObjectId:
    res = await db.documents.insert_one(
        {
            "userId": ObjectId(),
            "originalFilename": "x.png",
            "mimeType": "image/png",
            "gridFsFileId": ObjectId(),
            "uploadStatus": status,
            "documentType": "Tax Invoice",
            "isDeleted": False,
            **extra,
        }
    )
    return res.inserted_id


async def test_process_document_oversized_marks_failed_without_raising(db: Any) -> None:
    doc_id = await _insert_doc(db)
    await pipeline.process_document(doc_id, BOMB, "image/png", "Tax Invoice")
    doc = await db.documents.find_one({"_id": doc_id})
    assert doc["uploadStatus"] == "failed"
    assert doc["processingError"] == EXPECTED


def _mock_recovery(monkeypatch: Any) -> list[Any]:
    calls: list[Any] = []

    async def fake_download(_: Any) -> bytes:
        return b"x"

    async def fake_process(doc_id: Any, *_: Any) -> None:
        await asyncio.sleep(0)
        calls.append(doc_id)

    monkeypatch.setattr(docs_router, "download_buffer", fake_download)
    monkeypatch.setattr(docs_router, "process_document", fake_process)
    return calls


async def test_recovery_gives_up_after_max_attempts(db: Any, monkeypatch: Any) -> None:
    calls = _mock_recovery(monkeypatch)
    stuck = await _insert_doc(db, recoveryAttempts=docs_router.MAX_RECOVERY_ATTEMPTS)
    fresh = await _insert_doc(db)
    await docs_router.recover_interrupted_uploads()
    assert calls == [fresh]
    bad = await db.documents.find_one({"_id": stuck})
    assert bad["uploadStatus"] == "failed"
    assert bad["processingError"] == docs_router.RECOVERY_GAVE_UP_MESSAGE
    assert (await db.documents.find_one({"_id": fresh}))["recoveryAttempts"] == 1


async def test_recovery_counts_each_restart_then_stops(db: Any, monkeypatch: Any) -> None:
    calls = _mock_recovery(monkeypatch)
    doc_id = await _insert_doc(db)
    for _ in range(3):  # process "dies" every time: status stays uploaded
        await docs_router.recover_interrupted_uploads()
    assert calls == [doc_id, doc_id]  # processed twice, third restart gives up
    doc = await db.documents.find_one({"_id": doc_id})
    assert doc["uploadStatus"] == "failed"
    assert doc["recoveryAttempts"] == 3


async def test_concurrent_claims_from_same_snapshot_have_one_winner(db: Any) -> None:
    """Two recovery runs that both read the doc as 'attempts=0' race to claim it: the
    counter is pinned in the update filter, so exactly one wins and only it processes."""
    doc_id = await _insert_doc(db)
    snapshot = await db.documents.find_one({"_id": doc_id})
    results = await asyncio.gather(*(docs_router._claim_for_recovery(snapshot) for _ in range(5)))
    assert sum(r is not None for r in results) == 1
    assert (await db.documents.find_one({"_id": doc_id}))["recoveryAttempts"] == 1


async def test_reprocess_resets_recovery_counter(
    db: Any, client: Any, make_user: Any, monkeypatch: Any
) -> None:
    _mock_recovery(monkeypatch)
    u = await make_user()
    doc_id = await _insert_doc(db, status="failed", recoveryAttempts=3)
    await db.documents.update_one({"_id": doc_id}, {"$set": {"userId": u.id}})
    res = await client.post(f"/api/documents/{doc_id}/reprocess", headers=u.headers)
    assert res.status_code == 200
    assert (await db.documents.find_one({"_id": doc_id}))["recoveryAttempts"] == 0
