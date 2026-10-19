"""processingRunId: stale jobs write nothing, Reprocess is an atomic claim, generic failures get
PROCESSING_ERROR, admin edits clear flags, a failed model load is cached for a cooldown.
No real Paddle, Groq or real DB."""

import asyncio
import io
import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from bson import ObjectId
from PIL import Image

from app.features.documents import router as docs_router
from app.features.ocr import extraction as ex
from app.features.ocr import paddle_runner, pipeline
from app.features.ocr.providers import errors
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
ALLOWED_EXTRA = {
    "processingError",
    "processingErrorCode",
    "uploadStatus",
    "updatedAt",
    "reprocessedAt",
    "processingRunId",
}
BUSY = "This document is already being processed. Please wait."
GENERIC_MSG = "Something went wrong while processing this document."


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (200, 200), "white").save(buf, format="PNG")
    return buf.getvalue()


PNG = _png()


@pytest.fixture(autouse=True)
def slot() -> Iterator[None]:
    pipeline._reset_slot_for_tests()
    paddle_runner._reset_engine_for_tests()
    yield
    pipeline._reset_slot_for_tests()
    paddle_runner._reset_engine_for_tests()


class Env:
    def __init__(self) -> None:
        self.ocr: Callable[[], Any] = lambda: "NEW OCR TEXT"
        self.ai: Callable[[str], Any] = lambda _t: {}


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
        "processingRunId": "old",
        **extra,
    }
    return (await db.documents.insert_one(doc)).inserted_id


async def _get(db: Any, doc_id: Any) -> dict[str, Any]:
    d: dict[str, Any] = await db.documents.find_one({"_id": doc_id})
    return d


async def _wait(cond: Callable[[], Any], timeout: float = 10.0) -> None:
    end = time.monotonic() + timeout
    while not await cond():
        assert time.monotonic() < end, "condition not reached"
        await asyncio.sleep(0.02)


def _count_jobs(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, Any]]:
    jobs: list[tuple[Any, Any]] = []

    async def fake(doc_id: Any, *a: Any, **kw: Any) -> None:
        run_id = kw.get("run_id", a[3] if len(a) > 3 else None)
        jobs.append((doc_id, run_id))

    monkeypatch.setattr(docs_router, "process_document", fake)
    return jobs


def _post(client: Any, user: Any, doc_id: Any) -> Any:
    return client.post(f"/api/documents/{doc_id}/reprocess", headers=user.headers)


# 1
async def test_concurrent_reprocess_one_winner(
    env: Env, client: Any, db: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobs = _count_jobs(monkeypatch)
    user = await make_user()
    for _ in range(5):
        doc_id = await _insert(db, user)
        jobs.clear()
        r = await asyncio.gather(_post(client, user, doc_id), _post(client, user, doc_id))
        assert sorted(x.status_code for x in r) == [200, 409], [x.text for x in r]
        loser = next(x for x in r if x.status_code == 409)
        assert loser.json()["detail"] == BUSY
        await asyncio.sleep(0.05)
        assert len(jobs) == 1
        d = await _get(db, doc_id)
        assert d["processingRunId"] not in (None, "old")
        assert jobs[0][1] == d["processingRunId"]


# 2
async def test_recent_uploaded_is_409_and_unchanged(
    env: Env, client: Any, db: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobs = _count_jobs(monkeypatch)
    user = await make_user()
    doc_id = await _insert(
        db,
        user,
        uploadStatus="uploaded",
        updatedAt=datetime.now(UTC) - timedelta(minutes=1),
        taxInvoiceNo="KEEP",
        edited=True,
    )
    before = await _get(db, doc_id)
    res = await _post(client, user, doc_id)
    assert res.status_code == 409 and res.json()["detail"] == BUSY
    assert await _get(db, doc_id) == before
    assert jobs == []


# 3
@pytest.mark.parametrize("age", [timedelta(minutes=11), None])
async def test_stuck_uploaded_can_be_reprocessed(
    env: Env,
    client: Any,
    db: Any,
    make_user: Any,
    monkeypatch: pytest.MonkeyPatch,
    age: timedelta | None,
) -> None:
    jobs = _count_jobs(monkeypatch)
    user = await make_user()
    doc_id = await _insert(
        db,
        user,
        uploadStatus="uploaded",
        updatedAt=None if age is None else datetime.now(UTC) - age,
    )
    res = await _post(client, user, doc_id)
    assert res.status_code == 200, res.text
    d = await _get(db, doc_id)
    assert d["processingRunId"] not in (None, "old")
    assert d["uploadStatus"] == "uploaded" and d["recoveryAttempts"] == 0
    assert len(jobs) == 1 and jobs[0][1] == d["processingRunId"]


# 4: late old job
class Gate:
    """Fake AI whose first call blocks until released; later calls return `result`."""

    def __init__(self, env: Env, first: Callable[[], Any]) -> None:
        self.release = asyncio.Event()
        self.calls = 0
        self.result = ti_result()
        self.first = first

        async def ai(document_type: str, _text: str) -> dict[str, Any]:
            n = self.calls
            self.calls += 1
            if n == 0:
                await self.release.wait()
                return dict(self.first())
            return dict(self.result)

        self.fn = ai


async def _late_scenario(
    env: Env,
    client: Any,
    db: Any,
    make_user: Any,
    monkeypatch: pytest.MonkeyPatch,
    first: Callable[[], Any],
) -> dict[str, Any]:
    gate = Gate(env, first)
    monkeypatch.setattr(pipeline, "extract_header", gate.fn)
    user = await make_user()
    doc_id = await _insert(db, user)
    job1 = asyncio.create_task(
        pipeline.process_document(doc_id, PNG, "image/png", TI, run_id="old")
    )
    await _wait(lambda: _async(gate.calls >= 1))
    res = await _post(client, user, doc_id)  # job 2 runs inside the request
    assert res.status_code == 200, res.text
    mid = await _get(db, doc_id)
    assert mid["uploadStatus"] == "processed" and mid["taxInvoiceNo"] == "TI/2526/000123"
    gate.release.set()
    await asyncio.wait_for(job1, 10)
    return mid


async def _async(v: Any) -> Any:
    return v


async def test_late_old_job_success_writes_nothing(
    env: Env, client: Any, db: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    mid = await _late_scenario(
        env,
        client,
        db,
        make_user,
        monkeypatch,
        lambda: ti_result(taxInvoiceNo="LATE", taxInvoiceNoNeedsReview=True),
    )
    assert await _get(db, mid["_id"]) == mid


@pytest.mark.parametrize(
    "exc",
    [
        AIExtractionError("RATE_LIMIT"),
        paddle_runner.OcrEngineError("RuntimeError", "x"),
        RuntimeError("generic"),
    ],
)
async def test_late_old_job_failure_does_not_fail_new_success(
    env: Env,
    client: Any,
    db: Any,
    make_user: Any,
    monkeypatch: pytest.MonkeyPatch,
    exc: BaseException,
) -> None:
    def boom() -> Any:
        raise exc

    mid = await _late_scenario(env, client, db, make_user, monkeypatch, boom)
    assert await _get(db, mid["_id"]) == mid


async def test_late_old_job_ocr_engine_error_after_new_success(
    env: Env, client: Any, db: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate_evt = threading.Event()
    calls: list[int] = []

    def ocr(_p: str, **_k: Any) -> str:
        n = len(calls)
        calls.append(n)
        if n == 0:
            gate_evt.wait(10)
            raise RuntimeError("late engine failure")
        return "NEW OCR TEXT"

    monkeypatch.setattr(pipeline, "run_ocr", ocr)
    env.ai = lambda _t: ti_result()
    user = await make_user()
    doc_id = await _insert(db, user)
    job1 = asyncio.create_task(
        pipeline.process_document(doc_id, PNG, "image/png", TI, run_id="old")
    )
    await _wait(lambda: _async(len(calls) >= 1))
    # the OCR slot is held by job 1, so job 2 only runs once job 1 ended: reverse order is fine
    gate_evt.set()
    await asyncio.wait_for(job1, 10)
    d = await _get(db, doc_id)
    assert d["uploadStatus"] == "failed"  # job 1 owned the id, so its failure stands
    res = await _post(client, user, doc_id)
    assert res.status_code == 200, res.text
    d = await _get(db, doc_id)
    assert d["uploadStatus"] == "processed" and d["taxInvoiceNo"] == "TI/2526/000123"


async def test_reverse_order_job2_overwrites(
    env: Env, client: Any, db: Any, make_user: Any
) -> None:
    env.ai = lambda _t: ti_result(taxInvoiceNo="FIRST")
    user = await make_user()
    doc_id = await _insert(db, user)
    await pipeline.process_document(doc_id, PNG, "image/png", TI, run_id="old")
    assert (await _get(db, doc_id))["taxInvoiceNo"] == "FIRST"
    env.ai = lambda _t: ti_result()
    assert (await _post(client, user, doc_id)).status_code == 200
    d = await _get(db, doc_id)
    assert d["taxInvoiceNo"] == "TI/2526/000123" and d["uploadStatus"] == "processed"


# 5
async def test_legacy_document_without_run_id(
    env: Env, client: Any, db: Any, make_user: Any
) -> None:
    env.ai = lambda _t: ti_result()
    user = await make_user()
    doc_id = await _insert(db, user, uploadStatus="uploaded")
    await db.documents.update_one({"_id": doc_id}, {"$unset": {"processingRunId": ""}})
    await pipeline.process_document(doc_id, PNG, "image/png", TI)
    d = await _get(db, doc_id)
    assert d["uploadStatus"] == "processed" and d["taxInvoiceNo"] == "TI/2526/000123"

    await db.documents.update_one({"_id": doc_id}, {"$unset": {"processingRunId": ""}})
    assert (await _post(client, user, doc_id)).status_code == 200
    d = await _get(db, doc_id)
    assert isinstance(d["processingRunId"], str) and d["processingRunId"]

    env.ai = lambda _t: ti_result(taxInvoiceNo="STALE")
    before = await _get(db, doc_id)
    await pipeline.process_document(doc_id, PNG, "image/png", TI, run_id=None)
    assert await _get(db, doc_id) == before


# 6
async def test_recovery_sets_run_id_and_flags(env: Env, db: Any, make_user: Any) -> None:
    env.ai = lambda _t: ti_result()
    user = await make_user()
    doc_id = await _insert(db, user, uploadStatus="uploaded")
    await db.documents.update_one({"_id": doc_id}, {"$unset": {"processingRunId": ""}})
    assert await docs_router.recover_interrupted_uploads() == 1
    d = await _get(db, doc_id)
    assert d["uploadStatus"] == "processed"
    assert isinstance(d["processingRunId"], str) and d["processingRunId"]
    assert all(isinstance(d[f], bool) for f in FLAGS)
    assert d["taxInvoiceNo"] == "TI/2526/000123"


async def test_recovery_claim_makes_older_job_stale(env: Env, db: Any, make_user: Any) -> None:
    env.ai = lambda _t: ti_result()
    user = await make_user()
    doc_id = await _insert(db, user, uploadStatus="uploaded")  # run id "old"
    await docs_router.recover_interrupted_uploads()
    d = await _get(db, doc_id)
    assert d["processingRunId"] != "old"
    env.ai = lambda _t: ti_result(taxInvoiceNo="STALE")
    await pipeline.process_document(doc_id, PNG, "image/png", TI, run_id="old")
    assert await _get(db, doc_id) == d


# 7
def _png_small() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


async def test_upload_and_bulk_get_distinct_run_ids(
    client: Any, db: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobs = _count_jobs(monkeypatch)
    user = await make_user()
    img = _png_small()
    r = await client.post(
        "/api/documents/upload",
        headers=user.headers,
        files={"document": ("a.png", img, "image/png")},
        data={"documentType": TI},
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        "/api/documents/bulk-upload",
        headers=user.headers,
        files=[("documents", (f"{i}.png", img, "image/png")) for i in range(3)],
        data={"documentTypes": [TI, DC, TI]},
    )
    assert r.status_code == 201, r.text
    docs = [d async for d in db.documents.find({"userId": user.id})]
    assert len(docs) == 4
    ids = [d["processingRunId"] for d in docs]
    assert all(isinstance(i, str) and len(i) == 32 for i in ids) and len(set(ids)) == 4
    assert sorted(j[1] for j in jobs) == sorted(ids)
    assert {j[0] for j in jobs} == {d["_id"] for d in docs}


# 8
async def test_generic_exception_is_processing_error(
    env: Env, db: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(pipeline, "check_upload", boom)
    user = await make_user()
    doc_id = await _insert(db, user, uploadStatus="uploaded")
    await pipeline.process_document(doc_id, PNG, "image/png", TI, run_id="old")
    d = await _get(db, doc_id)
    assert d["uploadStatus"] == "failed"
    assert d["processingErrorCode"] == "PROCESSING_ERROR"
    assert d["processingError"] == GENERIC_MSG

    doc2 = await _insert(db, user, uploadStatus="uploaded", processingRunId="new")
    before = await _get(db, doc2)
    await pipeline.process_document(doc2, PNG, "image/png", TI, run_id="old")
    assert await _get(db, doc2) == before


def test_processing_error_code() -> None:
    assert "PROCESSING_ERROR" in errors.CODES
    assert errors.user_message("PROCESSING_ERROR") == GENERIC_MSG


# 9
async def test_download_failure_after_claim(
    env: Env, client: Any, db: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobs = _count_jobs(monkeypatch)

    async def bad(_f: Any) -> bytes:
        raise OSError("gridfs down")

    monkeypatch.setattr(docs_router, "download_buffer", bad)
    user = await make_user()
    doc_id = await _insert(db, user, edited=True, exported=True)
    before = await _get(db, doc_id)
    res = await _post(client, user, doc_id)
    assert res.status_code == 500
    # the claim had wiped the document; a failed file read puts it back EXACTLY as it was, so the
    # extracted values and the manual corrections are never lost and it is never left 'uploaded'
    d = await _get(db, doc_id)
    for key in (
        "uploadStatus",
        "taxInvoiceNo",
        "referenceNo",
        "number",
        "date",
        "edited",
        "exported",
        "processingError",
        "processingErrorCode",
        "processingRunId",
        "ocrTextHidden",
        *FLAGS,
    ):
        assert d.get(key) == before.get(key), key
    assert d["uploadStatus"] != "uploaded"
    assert jobs == []


# 10
async def _flagged(db: Any, user: Any, doc_type: str) -> Any:
    return await _insert(db, user, doc_type, **dict.fromkeys(FLAGS, True), exported=True)


CLEARS = {
    "taxInvoiceNo": ("taxInvoiceNoAutoCorrected", "taxInvoiceNoNeedsReview"),
    "referenceNo": ("referenceNoNeedsReview",),
    "date": ("dateAutoCorrected",),
    "number": ("numberAutoCorrected", "numberNeedsReview"),
}
VALUE_FOR = {
    "taxInvoiceNo": "TI/2526/000999",
    "referenceNo": "7654321",
    "date": "02/02/2026",
    "number": "DC/2526/000999",
}


@pytest.mark.parametrize("who", ["admin", "user"])
@pytest.mark.parametrize("field", list(CLEARS))
async def test_edit_clears_that_fields_flags(
    client: Any, db: Any, make_user: Any, who: str, field: str
) -> None:
    owner = await make_user()
    doc_type = DC if field == "number" else TI
    doc_id = await _flagged(db, owner, doc_type)
    if who == "admin":
        admin = await make_user(role="admin")
        res = await client.patch(
            f"/api/admin/documents/{doc_id}",
            headers=admin.headers,
            json={"field": field, "value": VALUE_FOR[field]},
        )
    else:
        res = await client.patch(
            f"/api/documents/{doc_id}/correct",
            headers=owner.headers,
            json={"field": field, "value": VALUE_FOR[field]},
        )
    assert res.status_code == 200, res.text
    d = await _get(db, doc_id)
    assert d[field] == VALUE_FOR[field]
    assert d["edited"] is True and d["exported"] is False
    for f in FLAGS:
        assert d[f] is (f not in CLEARS[field]), f


# 11
async def test_other_user_404_and_purged_400(
    env: Env, client: Any, db: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobs = _count_jobs(monkeypatch)
    owner, other = await make_user(), await make_user()
    doc_id = await _insert(db, owner)
    assert (await _post(client, other, doc_id)).status_code == 404
    purged = await _insert(db, owner, filePurged=True)
    assert (await _post(client, owner, purged)).status_code == 400
    assert jobs == []
    assert (await _get(db, doc_id))["processingRunId"] == "old"


# 12
class FailingPaddle:
    calls = 0

    def __init__(self, *_a: Any, **_k: Any) -> None:
        type(self).calls += 1
        raise RuntimeError("cannot load model (simulated)")


class GoodPaddle:
    calls = 0

    def __init__(self, *_a: Any, **_k: Any) -> None:
        type(self).calls += 1

    def predict(self, _path: str, **_kw: Any) -> list[Any]:
        return [
            SimpleNamespace(
                json={
                    "res": {
                        "rec_texts": ["TAX INVOICE No. 123456"],
                        "rec_boxes": [[10, 10, 300, 40]],
                    }
                }
            )
        ]


def test_model_load_failure_cooldown(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    import paddleocr

    path = tmp_path / "a.png"
    path.write_bytes(PNG)
    now = [1000.0]
    monkeypatch.setattr(paddle_runner, "_monotonic", lambda: now[0])
    FailingPaddle.calls = GoodPaddle.calls = 0
    monkeypatch.setattr(paddleocr, "PaddleOCR", FailingPaddle)
    cd = paddle_runner.MODEL_LOAD_RETRY_COOLDOWN_SECONDS
    assert cd > 0

    for _ in range(3):
        with pytest.raises(paddle_runner.OcrEngineError) as ei:
            paddle_runner.run_ocr(str(path))
        assert ei.value.cls_name == "RuntimeError"
    assert FailingPaddle.calls == 1

    now[0] += cd + 1
    with pytest.raises(paddle_runner.OcrEngineError):
        paddle_runner.run_ocr(str(path))
    assert FailingPaddle.calls == 2
    with pytest.raises(paddle_runner.OcrEngineError):
        paddle_runner.run_ocr(str(path))
    assert FailingPaddle.calls == 2

    monkeypatch.setattr(paddleocr, "PaddleOCR", GoodPaddle)
    now[0] += cd + 1
    out = paddle_runner.run_ocr(str(path))
    assert out and "123456" in out
    assert GoodPaddle.calls == 1
    paddle_runner.run_ocr(str(path))
    assert GoodPaddle.calls == 1  # cached engine, failure cleared


# 13
async def test_drift_guard_ai_failure_path(env: Env, db: Any, make_user: Any) -> None:
    derived = set(ex.EXTRACTION_DERIVED_FIELDS)
    env.ai = lambda _t: AIExtractionError("RATE_LIMIT")
    user = await make_user()
    for dtype in (TI, DC):
        doc_id = await _insert(db, user, dtype, uploadStatus="uploaded")
        before = set(await _get(db, doc_id))
        await pipeline.process_document(doc_id, PNG, "image/png", dtype, run_id="old")
        d = await _get(db, doc_id)
        assert d["uploadStatus"] == "failed"
        assert (set(d) - before) <= derived | ALLOWED_EXTRA, (set(d) - before) - derived
