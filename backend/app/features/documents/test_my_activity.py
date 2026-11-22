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
    res = await client.get("/api/documents/my-activity", headers=user.headers, params=params)
    assert res.status_code == 200
    body: dict = res.json()
    return body


async def _upload(client: Any, user: Any) -> str:
    res = await client.post(
        "/api/documents/upload",
        headers=user.headers,
        files={"document": ("a.pdf", io.BytesIO(PDF), "application/pdf")},
        data={"documentType": "Delivery Challan"},
    )
    assert res.status_code == 201, res.text
    return str(res.json()["document"]["_id"])


def _actions(body: dict) -> list[str]:
    return [e["action"] for e in body["activity"]]


async def test_user_actions_each_log_one_entry_only_for_owner(
    client: Any, db: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
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
    # a real job always carries the run id its document was given when it was started
    run_id = (await db.documents.find_one({"_id": ObjectId(doc_id)}))["processingRunId"]
    await pipeline.process_document(
        ObjectId(doc_id), PDF, "application/pdf", "Delivery Challan", run_id
    )
    assert _actions(await _activity(client, a)).count("document_processed") == 1

    res = await client.patch(
        f"/api/documents/{doc_id}/correct",
        headers=a.headers,
        json={"field": "number", "value": "820000002"},
    )
    assert res.status_code == 200, res.text
    body = await _activity(client, a)
    corrected = [e for e in body["activity"] if e["action"] == "document_corrected"]
    assert len(corrected) == 1
    assert corrected[0]["context"]["field"] == "number"
    assert "820000002" not in str(corrected[0]["context"])

    res = await client.post(f"/api/documents/{doc_id}/reprocess", headers=a.headers)
    assert res.status_code == 200, res.text
    assert _actions(await _activity(client, a)).count("document_reprocessed") == 1

    res = await client.delete(f"/api/documents/{doc_id}", headers=a.headers)
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


async def _seed_activity(db: Any, user: Any, n: int, *, action: str = "document_uploaded") -> None:
    if n:
        await db.auditlogs.insert_many(
            [
                {
                    "userId": user.id,
                    "action": action,
                    "context": {},
                    "createdAt": datetime.now(UTC),
                }
                for _ in range(n)
            ]
        )


async def test_default_page_size_is_30(client: Any, db: Any, make_user: Any) -> None:
    a = await make_user()
    await _seed_activity(db, a, 65)
    sizes = []
    for page in (1, 2, 3):
        body = await _activity(client, a, page=page)  # no limit sent: the backend default applies
        sizes.append(len(body["activity"]))
        assert body["totalActivity"] == 65
        assert body["totalPages"] == 3
        assert body["currentPage"] == page
    assert sizes == [30, 30, 5]


@pytest.mark.parametrize("n, pages", [(0, 1), (1, 1), (30, 1), (31, 2), (60, 2), (61, 3)])
async def test_total_pages_at_the_30_boundary(
    client: Any, db: Any, make_user: Any, n: int, pages: int
) -> None:
    a = await make_user()
    await _seed_activity(db, a, n)
    body = await _activity(client, a)
    assert body["totalPages"] == pages
    assert body["totalActivity"] == n
    assert len(body["activity"]) == min(n, 30)


async def test_bad_page_and_limit_values_stay_safe(client: Any, db: Any, make_user: Any) -> None:
    a = await make_user()
    await _seed_activity(db, a, 65)
    assert (await _activity(client, a, page=0))["currentPage"] == 1
    assert (await _activity(client, a, page=-1))["currentPage"] == 1
    far = await _activity(client, a, page=999)
    assert far["currentPage"] == 999 and far["activity"] == []  # past the end: empty, not an error
    assert len((await _activity(client, a, limit=0))["activity"]) == 30  # 0 falls back to default
    assert len((await _activity(client, a, limit=-5))["activity"]) == 1  # negative clamps to 1
    assert len((await _activity(client, a, limit=1000))["activity"]) == 65  # cap is 100; all 65 fit
    res = await client.get("/api/documents/my-activity", headers=a.headers, params={"page": "abc"})
    assert res.status_code == 422  # not a number: clean validation error, never a 500


async def test_other_users_entries_never_appear_in_pages(
    client: Any, db: Any, make_user: Any
) -> None:
    a = await make_user()
    b = await make_user()
    await _seed_activity(db, a, 35)
    await _seed_activity(db, b, 50)
    body = await _activity(client, a)
    assert body["totalActivity"] == 35 and body["totalPages"] == 2
    assert len(body["activity"]) == 30
    assert all(e.get("userId") in (None, str(a.id)) for e in body["activity"])
    second = await _activity(client, a, page=2)
    assert len(second["activity"]) == 5
