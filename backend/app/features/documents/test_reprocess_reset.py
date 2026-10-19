"""Reprocess wipes everything a previous read derived (values, flags, hidden text, processedAt,
legacy *Confidence) and a successful read writes every flag explicitly. No real Paddle/Groq."""

import asyncio
import io
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from bson import ObjectId
from PIL import Image

from app.features.documents import router as docs_router
from app.features.ocr import extraction as ex
from app.features.ocr import pipeline
from app.features.ocr.providers.errors import AIExtractionError

TI = "Tax Invoice"
DC = "Delivery Challan"
FLAGS = (
    "taxInvoiceNoNeedsReview",
    "referenceNoNeedsReview",
    "numberNeedsReview",
    "taxInvoiceNoAutoCorrected",
    "numberAutoCorrected",
    "dateAutoCorrected",
)
VALUES = ("taxInvoiceNo", "referenceNo", "number", "date")
CONF = ("taxInvoiceNoConfidence", "referenceNoConfidence", "numberConfidence", "dateConfidence")
# keys process_document legitimately adds that are not extraction-derived
ALLOWED_EXTRA = {
    "processingError",
    "processingErrorCode",
    "uploadStatus",
    "updatedAt",
    "reprocessedAt",
}


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (200, 200), "white").save(buf, format="PNG")
    return buf.getvalue()


PNG = _png()


class Env:
    """Controls the fake OCR engine and fake AI extraction."""

    def __init__(self) -> None:
        self.ocr: Callable[[], Any] = lambda: "NEW OCR TEXT"
        self.ai: Callable[[str], Any] = lambda _t: {}


@pytest.fixture(autouse=True)
def slot() -> Iterator[None]:
    pipeline._reset_slot_for_tests()
    yield
    pipeline._reset_slot_for_tests()


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Env:
    e = Env()
    monkeypatch.setattr(pipeline, "run_ocr", lambda _p, **_k: e.ocr())
    monkeypatch.setattr(pipeline, "classify_page_orientation", lambda _b: (0, 1.0))

    async def ai(document_type: str, _text: str) -> dict[str, Any]:
        out = e.ai(document_type)
        if isinstance(out, BaseException):
            raise out
        return dict(out)

    async def download(_file_id: Any) -> bytes:
        return PNG

    monkeypatch.setattr(pipeline, "extract_header", ai)
    monkeypatch.setattr(docs_router, "download_buffer", download)
    return e


def _const(res: dict[str, Any]) -> Callable[[str], Any]:
    return lambda _t: res


def ti_result(**over: Any) -> dict[str, Any]:
    base = ex.build_extraction_result(
        TI, {"taxInvoiceNo": "TI/2526/000123", "referenceNo": "1234567", "date": "01/01/2026"}
    )
    return {**base, **over}


def dc_result(**over: Any) -> dict[str, Any]:
    base = ex.build_extraction_result(DC, {"number": "DC/2526/000123", "date": "01/01/2026"})
    return {**base, **over}


async def _insert(db: Any, user: Any, doc_type: str = TI, **extra: Any) -> Any:
    doc = {
        "userId": user.id,
        "uploadStatus": "processed",
        "documentType": doc_type,
        "isDeleted": False,
        "originalName": "a.png",
        "gridFsFileId": ObjectId(),
        "mimeType": "image/png",
        "createdAt": datetime.now(UTC),
        **extra,
    }
    return (await db.documents.insert_one(doc)).inserted_id


def stale(**over: Any) -> dict[str, Any]:
    """A fully processed, fully flagged old document."""
    d: dict[str, Any] = {
        "taxInvoiceNo": "OLD-TI",
        "referenceNo": "OLD-REF",
        "number": "OLD-NUM",
        "date": "09/09/2020",
        **dict.fromkeys(FLAGS, True),
        **dict.fromkeys(CONF, 0.9),
        "ocrTextHidden": "old text",
        "processedAt": datetime(2020, 1, 1, tzinfo=UTC),
        "edited": True,
        "exported": True,
    }
    d.update(over)
    return d


async def reprocess(client: Any, db: Any, user: Any, doc_id: Any, expect: int = 200) -> dict:
    res = await client.post(f"/api/documents/{doc_id}/reprocess", headers=user.headers)
    assert res.status_code == expect, res.text
    if expect >= 400:
        return {}
    end = time.monotonic() + 10
    while True:
        d = await db.documents.find_one({"_id": doc_id})
        if d["uploadStatus"] in ("processed", "failed") and d.get("reprocessedAt"):
            return dict(d)
        assert time.monotonic() < end, f"reprocess did not finish: {d}"
        await asyncio.sleep(0.02)


def assert_clean_failed(d: dict[str, Any]) -> None:
    assert d["uploadStatus"] == "failed"
    assert all(d[k] is None for k in VALUES), d
    assert all(d[f] is False for f in FLAGS), d
    assert d["processedAt"] is None
    assert not any(c in d for c in CONF)
    assert d["edited"] is False


# 1
async def test_engine_error_leaves_clean_state(
    env: Env, client: Any, db: Any, make_user: Any
) -> None:
    def boom() -> Any:
        raise RuntimeError("engine boom")

    env.ocr = boom
    user = await make_user()
    doc_id = await _insert(db, user, **stale())
    d = await reprocess(client, db, user, doc_id)
    assert_clean_failed(d)
    assert d["ocrTextHidden"] is None


# 2
async def test_ai_failure_leaves_clean_state(
    env: Env, client: Any, db: Any, make_user: Any
) -> None:
    env.ai = lambda _t: AIExtractionError("RATE_LIMIT")
    user = await make_user()
    doc_id = await _insert(db, user, **stale())
    d = await reprocess(client, db, user, doc_id)
    assert_clean_failed(d)
    assert d["processingErrorCode"]
    assert d["ocrTextHidden"] == "NEW OCR TEXT" != "old text"


# 3
async def test_success_missing_flags_end_false(
    env: Env, client: Any, db: Any, make_user: Any
) -> None:
    partial = {"taxInvoiceNo": "TI/1", "referenceNo": "1234567", "date": "01/01/2026"}
    env.ai = lambda _t: partial
    user = await make_user()
    doc_id = await _insert(db, user, **stale())
    d = await reprocess(client, db, user, doc_id)
    assert d["uploadStatus"] == "processed"
    assert all(d[f] is False for f in FLAGS), d
    assert d["taxInvoiceNo"] == "TI/1" and d["number"] is None
    assert d["processedAt"].replace(tzinfo=None) > datetime(2021, 1, 1)
    assert d["ocrTextHidden"] == "NEW OCR TEXT"
    assert not any(c in d for c in CONF)

    env.ai = lambda _t: {**partial, "taxInvoiceNoNeedsReview": True}
    d = await reprocess(client, db, user, doc_id)
    assert d["taxInvoiceNoNeedsReview"] is True
    assert d["numberNeedsReview"] is False and d["referenceNoNeedsReview"] is False


# 4
async def test_delivery_challan_irrelevant_flag_cleared(
    env: Env, client: Any, db: Any, make_user: Any
) -> None:
    env.ai = lambda _t: dc_result()
    user = await make_user()
    doc_id = await _insert(db, user, DC, **stale())
    d = await reprocess(client, db, user, doc_id)
    assert d["uploadStatus"] == "processed"
    assert d["taxInvoiceNoNeedsReview"] is False
    assert d["referenceNoNeedsReview"] is False
    assert d["taxInvoiceNoAutoCorrected"] is False


# 5
async def test_first_time_processing_writes_all_flags(env: Env, db: Any, make_user: Any) -> None:
    user = await make_user()
    for dtype, res in ((TI, ti_result()), (DC, dc_result())):
        env.ai = _const(res)
        doc_id = await _insert(db, user, dtype, uploadStatus="uploaded")
        await pipeline.process_document(doc_id, PNG, "image/png", dtype)
        d = await db.documents.find_one({"_id": doc_id})
        assert d["uploadStatus"] == "processed"
        assert all(isinstance(d[f], bool) for f in FLAGS), d
        for k in VALUES:
            assert d[k] == res.get(k)


# 6
async def test_edited_document_replaced_by_new_read(
    env: Env, client: Any, db: Any, make_user: Any
) -> None:
    env.ai = lambda _t: ti_result()
    user = await make_user()
    doc_id = await _insert(
        db, user, **stale(taxInvoiceNo="HAND-EDIT", taxInvoiceNoAutoCorrected=True)
    )
    d = await reprocess(client, db, user, doc_id)
    assert d["edited"] is False
    assert d["taxInvoiceNo"] == ti_result()["taxInvoiceNo"]
    for f in FLAGS:
        assert d[f] == bool(ti_result().get(f, False)), f


# 7
async def test_recovery_of_legacy_uploaded_document(env: Env, db: Any, make_user: Any) -> None:
    env.ai = lambda _t: ti_result()
    user = await make_user()
    doc_id = await _insert(db, user, uploadStatus="uploaded")
    assert await docs_router.recover_interrupted_uploads() == 1
    d = await db.documents.find_one({"_id": doc_id})
    assert d["uploadStatus"] == "processed"
    assert all(isinstance(d[f], bool) for f in FLAGS), d


# 8
async def test_api_hides_internal_keys(env: Env, client: Any, db: Any, make_user: Any) -> None:
    user = await make_user()
    doc_id = await _insert(db, user, **stale())
    res = await client.get(f"/api/documents/{doc_id}", headers=user.headers)
    assert res.status_code == 200, res.text
    body = res.json()
    doc = body.get("document", body)
    assert "ocrTextHidden" not in doc
    assert not any(k.endswith("Confidence") for k in doc)
    for k in (*VALUES, *FLAGS):
        assert k in doc, k


# 9
async def test_drift_guard(env: Env, db: Any, make_user: Any) -> None:
    derived = set(ex.EXTRACTION_DERIVED_FIELDS)
    ops = ex.extraction_reset_ops()
    assert set(ops["$set"]) | set(ops["$unset"]) == derived
    for dtype, res in ((TI, ti_result()), (DC, dc_result())):
        assert set(res) <= derived, set(res) - derived
        env.ai = _const(res)
        user = await make_user()
        doc_id = await _insert(db, user, dtype, uploadStatus="uploaded")
        before = set(await db.documents.find_one({"_id": doc_id}))
        await pipeline.process_document(doc_id, PNG, "image/png", dtype)
        after = set(await db.documents.find_one({"_id": doc_id}))
        assert (after - before) <= derived | ALLOWED_EXTRA, (after - before) - derived


# 10
async def test_other_users_document_404(env: Env, client: Any, db: Any, make_user: Any) -> None:
    owner, other = await make_user(), await make_user()
    doc_id = await _insert(db, owner, **stale())
    await reprocess(client, db, other, doc_id, expect=404)
    assert (await db.documents.find_one({"_id": doc_id}))["taxInvoiceNo"] == "OLD-TI"


async def test_purged_file_400_and_untouched(
    env: Env, client: Any, db: Any, make_user: Any
) -> None:
    user = await make_user()
    doc_id = await _insert(db, user, filePurged=True, **stale())
    await reprocess(client, db, user, doc_id, expect=400)
    d = await db.documents.find_one({"_id": doc_id})
    assert d["taxInvoiceNo"] == "OLD-TI" and d["taxInvoiceNoNeedsReview"] is True


# 11
async def test_reprocess_after_failed_reprocess(
    env: Env, client: Any, db: Any, make_user: Any
) -> None:
    env.ai = lambda _t: AIExtractionError("RATE_LIMIT")
    user = await make_user()
    doc_id = await _insert(db, user, **stale())
    assert_clean_failed(await reprocess(client, db, user, doc_id))
    env.ai = lambda _t: ti_result()
    d = await reprocess(client, db, user, doc_id)
    assert d["uploadStatus"] == "processed"
    assert d["processingError"] is None and d["processingErrorCode"] is None
    assert d["taxInvoiceNo"] == ti_result()["taxInvoiceNo"]
    assert not any(c in d for c in CONF)


# 12
async def test_legacy_document_without_flags(
    env: Env, client: Any, db: Any, make_user: Any
) -> None:
    def boom() -> Any:
        raise RuntimeError("x")

    env.ocr = boom
    user = await make_user()
    doc_id = await _insert(db, user, uploadStatus="failed", taxInvoiceNo="X")
    d = await reprocess(client, db, user, doc_id)
    assert all(d[f] is False for f in FLAGS)
    assert all(d[k] is None for k in VALUES)


# 13
def test_reset_ops_shape() -> None:
    ops = ex.extraction_reset_ops()
    assert set(ops) == {"$set", "$unset"}
    s = ops["$set"]
    assert all(s[k] is None for k in (*VALUES, "ocrTextHidden", "processedAt"))
    assert all(s[f] is False for f in FLAGS)
    assert ops["$unset"] == dict.fromkeys(CONF, "")
    assert set(ex.EXTRACTION_VALUE_FIELDS) == set(VALUES)
    assert set(ex.EXTRACTION_FLAG_FIELDS) == set(FLAGS)
    assert set(ex.LEGACY_CONFIDENCE_FIELDS) == set(CONF)
    assert isinstance(ex.EXTRACTION_DERIVED_FIELDS, tuple)
    assert set(ex.EXTRACTION_DERIVED_FIELDS) == {
        *VALUES,
        *FLAGS,
        *CONF,
        "ocrTextHidden",
        "processedAt",
    }


def test_success_fields_empty_and_partial() -> None:
    empty = ex.extraction_success_fields({})
    assert all(empty[k] is None for k in VALUES)
    assert all(empty[f] is False for f in FLAGS)
    assert set(empty) == {*VALUES, *FLAGS}

    part = ex.extraction_success_fields(
        {"number": "N1", "numberNeedsReview": True, "dateAutoCorrected": 1, "junk": "x"}
    )
    assert part["number"] == "N1" and part["date"] is None
    assert part["numberNeedsReview"] is True and part["dateAutoCorrected"] is True
    assert part["taxInvoiceNoNeedsReview"] is False
    assert "junk" not in part
