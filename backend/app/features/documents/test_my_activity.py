"""My Activity: each user action on a document logs exactly one entry, visible only to its owner."""

import io
from datetime import UTC, datetime
from typing import Any

import pytest
from bson import ObjectId

from app.features.documents import router as docs_router
from app.features.ocr import pipeline

PDF = b"%PDF-1.4 fake"


@pytest.fixture(autouse=True)
def no_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    async def noop(*_a: Any, **_k: Any) -> None:
        return None

    async def fake_validate_pdf(_b: bytes) -> int:
        return 1

    monkeypatch.setattr(docs_router, "process_document", noop)
    monkeypatch.setattr(docs_router, "get_pdf_page_count", fake_validate_pdf)


async def _activity(client: Any, user: Any, **params: Any) -> dict:
    res = await client.get("/documents/my-activity", headers=user.headers, params=params)
    assert res.status_code == 200
    body: dict = res.json()
    return body


async def _upload(client: Any, user: Any) -> str:
    res = await client.post(
        "/documents/upload",
        headers=user.headers,
        files={"document": ("a.pdf", io.BytesIO(PDF), "application/pdf")},
        data={"documentType": "Delivery Challan"},
    )
    assert res.status_code == 201, res.text
    return str(res.json()["document"]["_id"])


def _actions(body: dict) -> list[str]:
    return [e["action"] for e in body["activity"]]


async def test_user_actions_each_log_one_entry_only_for_owner(
    client: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = await make_user()
    b = await make_user()

    doc_id = await _upload(client, a)
    assert _actions(await _activity(client, a)) == ["document_uploaded"]

    # processed: success path of the pipeline, called directly with OCR/AI stubbed
    async def fake_text(*_a: Any, **_k: Any) -> str:
        return "header"

    async def fake_extract(*_a: Any, **_k: Any) -> dict:
        return {"number": "820000001", "date": "01/01/2026"}

    monkeypatch.setattr(pipeline, "_extract_header_text", fake_text)
    monkeypatch.setattr(pipeline, "extract_header", fake_extract)
    await pipeline.process_document(ObjectId(doc_id), PDF, "application/pdf", "Delivery Challan")
    assert _actions(await _activity(client, a)).count("document_processed") == 1

    res = await client.patch(
        f"/documents/{doc_id}/correct",
        headers=a.headers,
        json={"field": "number", "value": "820000002"},
    )
    assert res.status_code == 200, res.text
    body = await _activity(client, a)
    corrected = [e for e in body["activity"] if e["action"] == "document_corrected"]
    assert len(corrected) == 1
    assert corrected[0]["context"]["field"] == "number"
    assert "820000002" not in str(corrected[0]["context"])

    res = await client.post(f"/documents/{doc_id}/reprocess", headers=a.headers)
    assert res.status_code == 200, res.text
    assert _actions(await _activity(client, a)).count("document_reprocessed") == 1

    res = await client.delete(f"/documents/{doc_id}", headers=a.headers)
    assert res.status_code == 200, res.text
    body = await _activity(client, a)
    assert _actions(body).count("document_deleted") == 1
    deleted = next(e for e in body["activity"] if e["action"] == "document_deleted")
    assert deleted["document"] is None and deleted["context"]["filename"] == "a.pdf"
    assert body["totalActivity"] == 5

    assert (await _activity(client, b))["activity"] == []


async def test_failing_log_does_not_break_upload(
    client: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = await make_user()

    async def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("audit down")

    monkeypatch.setattr("app.core.audit_log.log_action", boom)
    await _upload(client, a)  # asserts 201
    monkeypatch.undo()
    assert (await _activity(client, a))["activity"] == []


async def test_limit_and_page_are_capped(client: Any, db: Any, make_user: Any) -> None:
    a = await make_user()
    await db.auditlogs.insert_many(
        [
            {
                "userId": a.id,
                "action": "document_uploaded",
                "context": {},
                "createdAt": datetime.now(UTC),
            }
            for _ in range(150)
        ]
    )
    body = await _activity(client, a, limit=100000)
    assert len(body["activity"]) == 100
    assert body["totalPages"] == 2
    assert (await _activity(client, a, page=10**9))["currentPage"] == 100_000
