"""OCR failure kinds: engine error / timeout / no text / stuck get distinct codes + messages,
one clean ERROR log line, and an engine health counter. No real Paddle, Groq or real DB."""

import asyncio
import io
import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import cv2
import fitz
import pytest
from bson import ObjectId
from loguru import logger
from PIL import Image, UnidentifiedImageError

from app.features.ocr import paddle_runner, pipeline
from app.features.ocr.providers import errors

SECRET = "SECRET-OCR-TEXT-9f3a"
ENGINE_MSG = "The text reader failed. Please tell the administrator."
TIMEOUT_MSG = (
    "Reading this document took too long. Please try again, or upload a smaller or clearer file."
)
NO_TEXT_MSG = (
    "We could not read any text from this document. Try a clearer photo or scan, "
    "or a higher-quality PDF."
)
STUCK_MSG = (
    "The text reader is stuck. Please tell the administrator to restart the app, "
    "then press Reprocess."
)


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (200, 200), "white").save(buf, format="PNG")
    return buf.getvalue()


PNG = _png()


class Fake:
    """Stand-in for run_ocr. `plan(n)` returns text or raises for call number n."""

    def __init__(self) -> None:
        self.gate = threading.Event()
        self.calls = 0
        self._lock = threading.Lock()
        self.plan: Callable[[int], Any] = lambda n: f"{SECRET} T{n}"
        self.block_first = False
        self.active = 0
        self.max_active = 0

    def run_ocr(self, _path: str, **_kw: Any) -> Any:
        with self._lock:
            n = self.calls
            self.calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.block_first and n == 0:
                self.gate.wait(15)
            return self.plan(n)
        finally:
            with self._lock:
                self.active -= 1

    def classify(self, _png: bytes) -> tuple[int, float]:
        return (0, 1.0)


def raiser(exc: BaseException) -> Callable[[int], Any]:
    def plan(_n: int) -> Any:
        raise exc

    return plan


@pytest.fixture(autouse=True)
def slot(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(pipeline, "OCR_TIMEOUT_SECONDS_IMAGE", 0.3)
    monkeypatch.setattr(pipeline, "OCR_TIMEOUT_SECONDS_PDF", 0.3)
    monkeypatch.setattr(pipeline, "_LOCK_WEDGED_THRESHOLD_SECONDS", 0.8)
    monkeypatch.setattr(pipeline, "_WAIT_SLICE_SECONDS", 0.05)
    pipeline._reset_slot_for_tests()
    yield
    pipeline._reset_slot_for_tests()


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Iterator[Fake]:
    f = Fake()
    monkeypatch.setattr(pipeline, "run_ocr", f.run_ocr)
    monkeypatch.setattr(pipeline, "classify_page_orientation", f.classify)

    async def ai(_t: str, _text: str) -> dict[str, Any]:
        return {"number": "123", "date": "01/01/2026"}

    monkeypatch.setattr(pipeline, "extract_header", ai)
    try:
        yield f
    finally:
        f.gate.set()


async def until(cond: Callable[[], bool], timeout: float = 5.0) -> None:
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, "condition not reached"
        await asyncio.sleep(0.01)


def st() -> dict[str, Any]:
    return dict(pipeline.ocr_lock_status())


def eng() -> dict[str, Any]:
    return dict(pipeline.ocr_engine_status())


async def _doc(db: Any, make_user: Any, mime: str = "image/png") -> ObjectId:
    user = await make_user()
    doc = {
        "userId": user.id,
        "uploadStatus": "uploaded",
        "documentType": "Delivery Challan",
        "isDeleted": False,
        "originalName": "a.png",
        "mimeType": mime,
        "createdAt": datetime.now(UTC),
    }
    inserted: ObjectId = (await db.documents.insert_one(doc)).inserted_id
    return inserted


async def run_doc(
    db: Any, make_user: Any, buf: bytes = PNG, mime: str = "image/png"
) -> dict[str, Any]:
    did = await _doc(db, make_user, mime)
    await asyncio.wait_for(pipeline.process_document(did, buf, mime, "Delivery Challan"), 10)
    d: dict[str, Any] = await db.documents.find_one({"_id": did})
    return d


def failed_with(d: dict[str, Any], code: str, msg: str) -> None:
    assert d["uploadStatus"] == "failed", d
    assert d["processingErrorCode"] == code
    assert d["processingError"] == msg


class Logs:
    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []
        self._id = logger.add(lambda m: self.records.append((m.record["level"].name, str(m))))

    def close(self) -> None:
        logger.remove(self._id)

    def failed_lines(self) -> list[str]:
        return [m for lvl, m in self.records if lvl == "ERROR" and "OCR failed:" in m]


@pytest.fixture
def logs() -> Iterator[Logs]:
    lg = Logs()
    yield lg
    lg.close()


# ---------------- codes ----------------


def test_codes_and_messages() -> None:
    assert errors.user_message("OCR_ENGINE_ERROR") == ENGINE_MSG
    assert errors.user_message("OCR_TIMEOUT") == TIMEOUT_MSG
    assert errors.user_message("NO_TEXT") == NO_TEXT_MSG
    assert errors.user_message("OCR_STUCK") == STUCK_MSG
    assert {"OCR_ENGINE_ERROR", "OCR_TIMEOUT", "NO_TEXT", "OCR_STUCK"} <= set(errors.CODES)


# ---------------- 1 engine error + log ----------------


async def test_engine_runtime_error(fake: Fake, logs: Logs, db: Any, make_user: Any) -> None:
    fake.plan = raiser(RuntimeError(f"boom {SECRET}"))
    d = await run_doc(db, make_user)
    failed_with(d, "OCR_ENGINE_ERROR", ENGINE_MSG)
    lines = logs.failed_lines()
    assert len(lines) == 1, logs.records
    line = lines[0]
    assert "code=OCR_ENGINE_ERROR" in line and "class=RuntimeError" in line
    assert "Delivery Challan" in line and "image/png" in line


async def test_log_never_contains_ocr_text(fake: Fake, logs: Logs, db: Any, make_user: Any) -> None:
    await run_doc(db, make_user)  # OCR text is SECRET; never logged
    fake.plan = lambda _n: None
    await run_doc(db, make_user)
    assert not any(SECRET in m for _, m in logs.records)


# ---------------- 2 model load ----------------


async def test_get_ocr_failure(
    db: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch, logs: Logs
) -> None:
    def broken() -> Any:
        raise FileNotFoundError("model missing")

    monkeypatch.setattr(paddle_runner, "_get_ocr", broken)
    d = await run_doc(db, make_user)
    failed_with(d, "OCR_ENGINE_ERROR", ENGINE_MSG)
    assert "class=FileNotFoundError" in logs.failed_lines()[0]


# ---------------- 3 MemoryError, slot released ----------------


async def test_memory_error_then_next_ok(fake: Fake, db: Any, make_user: Any) -> None:
    fake.plan = lambda n: (_ for _ in ()).throw(MemoryError()) if n == 0 else f"T{n}"
    d1 = await run_doc(db, make_user)
    failed_with(d1, "OCR_ENGINE_ERROR", ENGINE_MSG)
    d2 = await run_doc(db, make_user)
    assert d2["uploadStatus"] == "processed"
    await until(lambda: not st()["held"])


# ---------------- 4 timeout ----------------


async def test_timeout_keeps_lock_then_second_runs(
    fake: Fake, db: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline, "_LOCK_WEDGED_THRESHOLD_SECONDS", 10.0)
    fake.block_first = True
    d = await run_doc(db, make_user)
    failed_with(d, "OCR_TIMEOUT", TIMEOUT_MSG)
    assert st()["held"] is True
    did2 = await _doc(db, make_user)
    second = asyncio.create_task(pipeline.process_document(did2, PNG, "image/png", "x"))
    await asyncio.sleep(0.2)
    assert fake.calls == 1 and not second.done()
    fake.gate.set()
    await asyncio.wait_for(second, 5)
    assert (await db.documents.find_one({"_id": did2}))["uploadStatus"] == "processed"
    assert fake.max_active == 1
    await until(lambda: not st()["held"])


# ---------------- 5 blank result ----------------


@pytest.mark.parametrize("blank", [None, "", "  \n"])
async def test_blank_result_is_no_text(fake: Fake, db: Any, make_user: Any, blank: Any) -> None:
    fake.plan = lambda _n: blank
    d = await run_doc(db, make_user)
    failed_with(d, "NO_TEXT", NO_TEXT_MSG)


# ---------------- 6 bad files never reach the engine ----------------


@pytest.mark.parametrize(
    "buf", [b"\x89PNG\r\n\x1a\n" + b"garbage" * 20, b"", b"just some text\n" * 10]
)
async def test_bad_image_bytes_skip_engine(fake: Fake, db: Any, make_user: Any, buf: bytes) -> None:
    d = await run_doc(db, make_user, buf)
    failed_with(d, "NO_TEXT", NO_TEXT_MSG)
    assert fake.calls == 0
    assert eng()["consecutiveFailures"] == 0


# ---------------- 7 PDFs ----------------


def _blank_pdf() -> bytes:
    doc = fitz.open()
    doc.new_page(width=300, height=300)
    out: bytes = doc.tobytes()
    doc.close()
    return out


async def test_pdf_unopenable(fake: Fake, logs: Logs, db: Any, make_user: Any) -> None:
    d = await run_doc(db, make_user, b"%PDF-1.4 garbage garbage", "application/pdf")
    failed_with(d, "NO_TEXT", NO_TEXT_MSG)
    assert fake.calls == 0
    line = logs.failed_lines()[0]
    assert "code=NO_TEXT" in line and "class=" in line


async def test_pdf_blank_page(fake: Fake, db: Any, make_user: Any) -> None:
    fake.plan = lambda _n: None
    d = await run_doc(db, make_user, _blank_pdf(), "application/pdf")
    failed_with(d, "NO_TEXT", NO_TEXT_MSG)


# ---------------- 8 stuck ----------------


async def test_wedged_slot_is_stuck(fake: Fake, db: Any, make_user: Any) -> None:
    fake.block_first = True
    await run_doc(db, make_user)  # times out, orphans the slot
    waiting = asyncio.create_task(
        pipeline.process_document(await _doc(db, make_user), PNG, "image/png", "x")
    )
    await until(lambda: st()["wedged"], 3)
    await asyncio.wait_for(waiting, 2)
    d = await run_doc(db, make_user)
    failed_with(d, "OCR_STUCK", STUCK_MSG)
    fake.gate.set()
    await until(lambda: not st()["held"])


# ---------------- 9 counters ----------------


async def test_engine_counters(fake: Fake, db: Any, make_user: Any) -> None:
    assert eng() == {"consecutiveFailures": 0, "lastErrorClass": None, "lastErrorAt": None}
    fake.plan = raiser(RuntimeError("x"))
    for _ in range(3):
        await run_doc(db, make_user)
    s = eng()
    assert s["consecutiveFailures"] == 3 and s["lastErrorClass"] == "RuntimeError"
    datetime.fromisoformat(s["lastErrorAt"])

    fake.plan = lambda _n: None  # completes without raising (empty) -> reset
    await run_doc(db, make_user)
    assert eng()["consecutiveFailures"] == 0

    fake.plan = raiser(RuntimeError("x"))
    await run_doc(db, make_user)
    assert eng()["consecutiveFailures"] == 1
    # NO_TEXT from a bad file: neither counts nor resets
    await run_doc(db, make_user, b"")
    assert eng()["consecutiveFailures"] == 1
    # timeout: neither counts nor resets
    fake.plan = lambda _n: f"T{_n}"
    fake.block_first = True
    fake.calls = 0
    await run_doc(db, make_user)
    assert eng()["consecutiveFailures"] == 1
    fake.gate.set()
    await until(lambda: not st()["held"])


# ---------------- 10 reprocess ----------------


async def test_reprocess_after_engine_error(
    fake: Fake, client: Any, db: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.features.documents import router as docs_router

    async def fake_download(_file_id: Any) -> bytes:
        return PNG

    monkeypatch.setattr(docs_router, "download_buffer", fake_download)
    user = await make_user()
    doc_id = (
        await db.documents.insert_one(
            {
                "userId": user.id,
                "uploadStatus": "failed",
                "documentType": "Delivery Challan",
                "isDeleted": False,
                "originalName": "a.png",
                "gridFsFileId": ObjectId(),
                "mimeType": "image/png",
                "createdAt": datetime.now(UTC),
                "processingError": ENGINE_MSG,
                "processingErrorCode": "OCR_ENGINE_ERROR",
            }
        )
    ).inserted_id
    res = await client.post(f"/api/documents/{doc_id}/reprocess", headers=user.headers)
    assert res.status_code < 400, res.text

    async def done() -> bool:
        d = await db.documents.find_one({"_id": doc_id})
        return bool(d["uploadStatus"] == "processed")

    end = time.monotonic() + 10
    while not await done():
        assert time.monotonic() < end, "reprocess did not finish"
        await asyncio.sleep(0.05)
    d = await db.documents.find_one({"_id": doc_id})
    assert d["processingError"] is None and d["processingErrorCode"] is None


# ---------------- 11 bulk ----------------


async def test_bulk_one_engine_error(fake: Fake, db: Any, make_user: Any) -> None:
    fake.plan = lambda n: (_ for _ in ()).throw(RuntimeError("x")) if n == 1 else f"T{n}"
    docs = [await run_doc(db, make_user) for _ in range(5)]
    assert [d["uploadStatus"] for d in docs] == ["processed", "failed"] + ["processed"] * 3
    assert docs[1]["processingErrorCode"] == "OCR_ENGINE_ERROR"
    assert st()["held"] is False


# ---------------- 12 health / admin ----------------


async def test_health_and_admin_system(fake: Fake, client: Any, make_user: Any) -> None:
    admin = await make_user(role="admin")
    h = (await client.get("/health")).json()
    assert h["status"] == "ok" and h["ocrLockWedged"] is False
    body = (await client.get("/api/admin/system", headers=admin.headers)).json()
    assert {"db", "ocrLockWedged", "storage", "checkedAt", "ocrEngine"} <= set(body)
    assert body["ocrEngine"] == {
        "consecutiveFailures": 0,
        "lastErrorClass": None,
        "lastErrorAt": None,
    }


# ---------------- 13 file-caused engine exceptions ----------------


async def test_file_caused_engine_exception(fake: Fake, db: Any, make_user: Any) -> None:
    fake.plan = raiser(Exception("Image read Error: x"))
    d = await run_doc(db, make_user)
    failed_with(d, "NO_TEXT", NO_TEXT_MSG)
    assert eng()["consecutiveFailures"] == 0


@pytest.mark.parametrize("exc", [cv2.error("bad op"), UnidentifiedImageError("cannot identify")])
async def test_cv2_or_pillow_error_inside_the_engine_is_an_engine_error(
    fake: Fake, db: Any, make_user: Any, exc: BaseException
) -> None:
    """The image was already decoded fine before the engine ran, so this is not the file's fault."""
    fake.plan = raiser(exc)
    d = await run_doc(db, make_user)
    failed_with(d, "OCR_ENGINE_ERROR", ENGINE_MSG)
    assert eng()["consecutiveFailures"] == 1


@pytest.mark.parametrize("exc", [SystemExit(3), KeyboardInterrupt()])
async def test_base_exception_from_the_engine_fails_the_document_not_the_batch(
    fake: Fake, db: Any, make_user: Any, exc: BaseException
) -> None:
    fake.plan = raiser(exc)
    bad = await run_doc(db, make_user)
    failed_with(bad, "OCR_ENGINE_ERROR", ENGINE_MSG)
    fake.plan = lambda n: "TAX INVOICE No. 123456\nDate 01/01/2026"
    good = await run_doc(db, make_user)
    assert good["uploadStatus"] == "processed"
    assert not pipeline.ocr_lock_status()["held"]


def test_user_names_with_spaces_do_not_leak() -> None:
    from app.features.ocr.paddle_runner import short_error_message

    for raw in (
        "failed at C:\\Users\\John Smith\\AppData\\Local\\x.png",
        "failed at C:/Users/John Smith/AppData/x.png",
        "failed at /home/bob smith/x/y.png",
        "failed at C:\\Documents and Settings\\bob\\Local Settings\\x.png",
    ):
        out = short_error_message(RuntimeError(raw))
        assert "Smith" not in out and "smith" not in out and "bob" not in out, out
        assert "John" not in out, out


# ---------------- 14 run_ocr direct ----------------


class _FakeOcr:
    def __init__(self, result: Any = None, exc: BaseException | None = None) -> None:
        self.result, self.exc = result, exc

    def predict(self, *_a: Any, **_k: Any) -> Any:
        if self.exc:
            raise self.exc
        return self.result


def test_run_ocr_predict_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paddle_runner, "_get_ocr", lambda: _FakeOcr(exc=RuntimeError("boom")))
    with pytest.raises(paddle_runner.OcrEngineError) as ei:
        paddle_runner.run_ocr("x.png")
    assert ei.value.cls_name == "RuntimeError"


def test_run_ocr_empty_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paddle_runner, "_get_ocr", lambda: _FakeOcr(result=[]))
    assert paddle_runner.run_ocr("x.png") is None


def test_run_ocr_get_ocr_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> Any:
        raise FileNotFoundError("model missing")

    monkeypatch.setattr(paddle_runner, "_get_ocr", broken)
    with pytest.raises(paddle_runner.OcrEngineError) as ei:
        paddle_runner.run_ocr("x.png")
    assert ei.value.cls_name == "FileNotFoundError"


def test_run_ocr_message_sanitized(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    msg = f"fail at {tmp_path}\\x.png and C:\\Users\\SomeName\\secret\\f.png " + "z" * 500
    monkeypatch.setattr(paddle_runner, "_get_ocr", lambda: _FakeOcr(exc=RuntimeError(msg)))
    with pytest.raises(paddle_runner.OcrEngineError) as ei:
        paddle_runner.run_ocr("x.png")
    short = ei.value.short
    assert len(short) <= 200
    assert "SomeName" not in short and str(tmp_path) not in short
