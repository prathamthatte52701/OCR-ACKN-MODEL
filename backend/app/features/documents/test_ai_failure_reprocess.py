"""Reprocess clears the AI failure code; documents from before the code existed still serialize."""

from datetime import UTC, datetime
from typing import Any

import pytest
from bson import ObjectId

from app.features.documents import router as docs_router


@pytest.fixture(autouse=True)
def no_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    async def noop(*_a: Any, **_k: Any) -> None:
        return None

    async def one_page(_b: bytes) -> int:
        return 1

    async def fake_download(_file_id: Any) -> bytes:
        return b"%PDF-1.4 fake"

    monkeypatch.setattr(docs_router, "download_buffer", fake_download)
    monkeypatch.setattr(docs_router, "process_document", noop)
    monkeypatch.setattr(docs_router, "get_pdf_page_count", one_page)


async def _insert(db: Any, user: Any, **extra: Any) -> Any:
    doc = {
        "userId": user.id,
        "uploadStatus": "failed",
        "documentType": "Delivery Challan",
        "isDeleted": False,
        "originalName": "a.pdf",
        "gridFsFileId": ObjectId(),
        "mimeType": "application/pdf",
        "createdAt": datetime.now(UTC),
        **extra,
    }
    return (await db.documents.insert_one(doc)).inserted_id


async def test_reprocess_clears_error_and_code(client: Any, db: Any, make_user: Any) -> None:
    user = await make_user()
    doc_id = await _insert(
        db, user, processingError="busy", processingErrorCode="RATE_LIMIT", ocrTextHidden="t"
    )
    res = await client.post(f"/api/documents/{doc_id}/reprocess", headers=user.headers)
    assert res.status_code < 400, res.text
    doc = await db.documents.find_one({"_id": doc_id})
    assert doc["processingError"] is None
    assert doc["processingErrorCode"] is None
    assert doc["uploadStatus"] == "uploaded"


async def test_old_document_without_code_serializes(client: Any, db: Any, make_user: Any) -> None:
    user = await make_user()
    doc_id = await _insert(db, user, processingError="old message")
    one = await client.get(f"/api/documents/{doc_id}", headers=user.headers)
    assert one.status_code == 200, one.text
    lst = await client.get("/api/documents", headers=user.headers)
    assert lst.status_code == 200, lst.text
