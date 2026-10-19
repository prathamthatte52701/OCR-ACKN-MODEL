"""OCR slot: the lock stays held until the OCR thread really ends (no second run_ocr on the
same model after a timeout), waiting jobs never time out, a wedged slot fails fast and heals."""

import asyncio
import io
import random
import re
import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from bson import ObjectId
from loguru import logger
from PIL import Image

from app.features.ocr import pipeline

SECRET = "SECRET-OCR-TEXT-9f3a"
STUCK_MSG = (
    "The text reader is stuck. Please tell the administrator to restart the app, "
    "then press Reprocess."
)
NO_TEXT_MSG = (
    "We could not read any text from this document. Try a clearer photo or scan, "
    "or a higher-quality PDF."
)


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (200, 200), "white").save(buf, format="PNG")
    return buf.getvalue()


PNG = _png()


class Fake:
    """Thread-safe stand-in for run_ocr / classify_page_orientation."""

    def __init__(self) -> None:
        self.gate = threading.Event()
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.calls = 0
        self.paths: list[str] = []
        self.sleep_for: Callable[[int], float] = lambda _n: 0.0
        self.block_first = False  # first call waits on the gate
        self.raises = False

    def _enter(self) -> int:
        with self._lock:
            n = self.calls
            self.calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        return n

    def _run(self, n: int) -> None:
        try:
            if self.raises:
                raise RuntimeError("boom")
            if self.block_first and n == 0:
                self.gate.wait(15)
            else:
                time.sleep(self.sleep_for(n))
        finally:
            with self._lock:
                self.active -= 1

    def run_ocr(self, path: str, **_kw: Any) -> str:
        self.paths.append(path)
        n = self._enter()
        self._run(n)
        return f"{SECRET} T{n}"

    def classify(self, _png: bytes) -> tuple[int, float]:
        self._run(self._enter())
        return (0, 1.0)


@pytest.fixture(autouse=True)
def slot(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    async def same(b: bytes) -> bytes:
        return b

    monkeypatch.setattr(pipeline, "_normalize_photo_page", same)
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
    try:
        yield f
    finally:
        f.gate.set()  # never leak a blocked thread


async def until(cond: Callable[[], bool], timeout: float = 5.0) -> None:
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, "condition not reached"
        await asyncio.sleep(0.01)


def job() -> Any:
    return pipeline._extract_header_text(PNG, "image/png")


def st() -> dict[str, Any]:
    return dict(pipeline.ocr_lock_status())


async def timed_out_orphan(fake: Fake) -> None:
    """Run a job whose thread never ends; return once it timed out (slot orphaned)."""
    fake.block_first = True
    assert await asyncio.wait_for(job(), 3) is None


# ---------------- 1-3 ----------------


async def test_normal_job(fake: Fake) -> None:
    text = await job()
    assert text is not None and "T0" in text
    assert st()["held"] is False and st()["orphan"] is False


async def test_timeout_keeps_slot_until_thread_ends(fake: Fake) -> None:
    fake.block_first = True
    t0 = time.monotonic()
    assert await asyncio.wait_for(job(), 3) is None
    assert time.monotonic() - t0 < 1.0
    assert st()["held"] is True and st()["orphan"] is True

    second = asyncio.create_task(job())
    await asyncio.sleep(0.2)  # < wedged threshold, second must be waiting
    assert fake.calls == 1 and not second.done()

    fake.gate.set()
    text = await asyncio.wait_for(second, 3)
    assert text is not None and "T1" in text
    assert fake.max_active == 1
    await until(lambda: not st()["held"])
    assert st()["orphan"] is False


# ---------------- 4 wedged ----------------


async def test_wedged_fails_fast_and_self_heals(fake: Fake) -> None:
    await timed_out_orphan(fake)
    waiter = asyncio.create_task(job())  # arrives before wedged
    await asyncio.sleep(0.05)
    assert not waiter.done()
    await until(lambda: st()["wedged"], 3)
    with pytest.raises(pipeline.OcrStuckError):
        await asyncio.wait_for(waiter, 1)
    t0 = time.monotonic()
    with pytest.raises(pipeline.OcrStuckError):
        await asyncio.wait_for(job(), 1)  # new job while wedged
    assert time.monotonic() - t0 < 0.3

    fake.gate.set()
    await until(lambda: not st()["held"])
    assert st()["wedged"] is False and st()["orphan"] is False
    assert await asyncio.wait_for(job(), 3) is not None


async def _doc(db: Any, make_user: Any) -> ObjectId:
    user = await make_user()
    doc = {
        "userId": user.id,
        "uploadStatus": "uploaded",
        "documentType": "Delivery Challan",
        "isDeleted": False,
        "originalName": "a.png",
        "mimeType": "image/png",
        "createdAt": datetime.now(UTC),
    }
    inserted: ObjectId = (await db.documents.insert_one(doc)).inserted_id
    return inserted


@pytest.fixture
def fake_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    async def ai(_t: str, _text: str) -> dict[str, Any]:
        return {"number": "123", "date": "01/01/2026"}

    monkeypatch.setattr(pipeline, "extract_header", ai)


async def test_process_document_wedged_stuck(
    fake: Fake, fake_ai: None, db: Any, make_user: Any
) -> None:
    await timed_out_orphan(fake)
    waiting_id = await _doc(db, make_user)
    waiting = asyncio.create_task(pipeline.process_document(waiting_id, PNG, "image/png", "x"))
    await until(lambda: st()["wedged"], 3)
    await asyncio.wait_for(waiting, 2)
    new_id = await _doc(db, make_user)
    await asyncio.wait_for(pipeline.process_document(new_id, PNG, "image/png", "x"), 2)
    for did in (waiting_id, new_id):
        d = await db.documents.find_one({"_id": did})
        assert d["uploadStatus"] == "failed"
        assert d["processingErrorCode"] == "OCR_STUCK"
        assert d["processingError"] == STUCK_MSG
    fake.gate.set()
    await until(lambda: not st()["held"])
    heal_id = await _doc(db, make_user)
    await pipeline.process_document(heal_id, PNG, "image/png", "x")
    assert (await db.documents.find_one({"_id": heal_id}))["uploadStatus"] == "processed"


async def test_process_document_plain_timeout(
    fake: Fake, fake_ai: None, db: Any, make_user: Any
) -> None:
    fake.block_first = True
    did = await _doc(db, make_user)
    await asyncio.wait_for(pipeline.process_document(did, PNG, "image/png", "x"), 3)
    d = await db.documents.find_one({"_id": did})
    assert d["uploadStatus"] == "failed"
    assert d["processingError"] == NO_TEXT_MSG
    assert not d.get("processingErrorCode")


# ---------------- 5 queue ----------------


async def test_queue_waits_in_order(fake: Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "OCR_TIMEOUT_SECONDS_IMAGE", 2.0)
    monkeypatch.setattr(pipeline, "_LOCK_WEDGED_THRESHOLD_SECONDS", 5.0)
    fake.sleep_for = lambda n: 0.4 if n == 0 else 0.01
    tasks = []
    for _ in range(6):  # 1 long holder + 5 waiters
        tasks.append(asyncio.create_task(job()))
        await asyncio.sleep(0.06)
    results = await asyncio.gather(*tasks)
    for i, text in enumerate(results):
        assert text is not None and text.endswith(f"T{i}"), (i, text)
    assert fake.max_active == 1


# ---------------- 6, 7 cancellation ----------------


async def test_cancelled_caller_keeps_slot_until_thread_ends(fake: Fake) -> None:
    fake.block_first = True
    t = asyncio.create_task(job())
    await until(lambda: fake.calls == 1)
    t.cancel()
    await asyncio.gather(t, return_exceptions=True)
    assert st()["held"] is True
    nxt = asyncio.create_task(job())
    await asyncio.sleep(0.15)
    assert fake.calls == 1 and not nxt.done()
    fake.gate.set()
    assert await asyncio.wait_for(nxt, 3) is not None
    await until(lambda: not st()["held"])
    assert await asyncio.wait_for(job(), 3) is not None
    assert fake.max_active == 1


async def test_random_waiter_cancellation_never_leaks(
    fake: Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline, "OCR_TIMEOUT_SECONDS_IMAGE", 2.0)
    monkeypatch.setattr(pipeline, "_LOCK_WEDGED_THRESHOLD_SECONDS", 20.0)
    fake.sleep_for = lambda _n: 0.01
    rng = random.Random(1234)
    for _round in range(3):
        tasks = [asyncio.create_task(job()) for _ in range(50)]
        order = list(range(50))
        rng.shuffle(order)
        for i in order:
            for _ in range(rng.randint(0, 3)):
                await asyncio.sleep(0)
            if rng.random() < 0.3:
                await asyncio.sleep(rng.uniform(0, 0.004))
            tasks[i].cancel()
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 20)
        await until(lambda: not st()["held"], 10)
        assert fake.active == 0
        assert await asyncio.wait_for(job(), 3) is not None
        await until(lambda: not st()["held"])
    assert fake.max_active == 1


# ---------------- 8 raises ----------------


async def test_run_ocr_raises(fake: Fake) -> None:
    fake.raises = True
    assert await asyncio.wait_for(job(), 3) is None
    await until(lambda: not st()["held"], 1)
    assert st()["orphan"] is False
    fake.raises = False
    assert await asyncio.wait_for(job(), 3) is not None


# ---------------- 9 classifier ----------------


async def test_classifier_shares_slot(fake: Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "OCR_TIMEOUT_SECONDS_IMAGE", 2.0)
    fake.block_first = True
    ocr = asyncio.create_task(job())
    await until(lambda: fake.calls == 1)
    cls = asyncio.create_task(pipeline._classify_under_lock(PNG))
    await asyncio.sleep(0.2)
    assert fake.calls == 1 and not cls.done()
    fake.gate.set()
    assert await asyncio.wait_for(cls, 3) == (0, 1.0)
    await asyncio.wait_for(ocr, 3)
    assert fake.max_active == 1


async def test_classifier_timeout_keeps_slot(fake: Fake) -> None:
    fake.block_first = True
    try:
        await asyncio.wait_for(pipeline._classify_under_lock(PNG), 3)
    except Exception:  # noqa: BLE001 - what a timed-out classify surfaces is unspecified
        pass
    assert st()["held"] is True and st()["orphan"] is True
    nxt = asyncio.create_task(job())
    await asyncio.sleep(0.15)
    assert fake.calls == 1
    fake.gate.set()
    assert await asyncio.wait_for(nxt, 3) is not None
    assert fake.max_active == 1


# ---------------- 10 logs ----------------


async def test_log_lines_once_and_clean(fake: Fake) -> None:
    records: list[tuple[str, str]] = []
    sink = logger.add(
        lambda m: records.append((m.record["level"].name, m.record["message"])),
        level="INFO",
        filter=lambda r: r["name"] == pipeline.__name__,
    )
    try:
        await timed_out_orphan(fake)
        await asyncio.sleep(0.1)
        fake.gate.set()
        await until(lambda: not st()["held"])
        await asyncio.sleep(0.1)
    finally:
        logger.remove(sink)
    warns = [m for lvl, m in records if lvl == "WARNING"]
    ends = [
        m
        for lvl, m in records
        if lvl == "INFO" and not re.search("preprocessing|normalization", m, re.I)
    ]
    assert len(warns) == 1, records
    assert len(ends) == 1 and re.search(r"\d", ends[0]), records
    blob = " ".join(m for _, m in records)
    assert SECRET not in blob
    assert all(p not in blob and re.split(r"[\\/]", p)[-1] not in blob for p in fake.paths)


# ---------------- 11 health / admin ----------------


async def test_health_and_admin_follow_state(fake: Fake, client: Any, make_user: Any) -> None:
    admin = await make_user(role="admin")
    body = (await client.get("/health")).json()
    assert body["status"] == "ok" and body["ocrLockWedged"] is False
    sysbody = (await client.get("/api/admin/system", headers=admin.headers)).json()
    assert sysbody["ocrLockWedged"] is False and "db" in sysbody and "storage" in sysbody

    await timed_out_orphan(fake)
    await until(lambda: st()["wedged"], 3)
    assert (await client.get("/health")).json()["ocrLockWedged"] is True
    sysbody = (await client.get("/api/admin/system", headers=admin.headers)).json()
    assert sysbody["ocrLockWedged"] is True
    fake.gate.set()
    await until(lambda: not st()["held"])
    assert (await client.get("/health")).json()["ocrLockWedged"] is False


async def test_status_keys(fake: Fake) -> None:
    assert set(st()) >= {"held", "wedged", "orphan", "orphanSeconds"}
    assert st()["orphanSeconds"] is None
    await timed_out_orphan(fake)
    s = st()
    assert s["held"] and s["orphan"] and isinstance(s["orphanSeconds"], float)
    fake.gate.set()
    await until(lambda: not st()["held"])


# ---------------- 12 boundary race ----------------


async def test_timeout_boundary_race(fake: Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "OCR_TIMEOUT_SECONDS_IMAGE", 0.02)
    monkeypatch.setattr(pipeline, "_LOCK_WEDGED_THRESHOLD_SECONDS", 30.0)
    fake.sleep_for = lambda _n: 0.02
    async with asyncio.timeout(60):
        for _ in range(200):
            await job()
            await until(lambda: not st()["held"], 3)
            assert st()["orphan"] is False
    assert fake.max_active == 1
