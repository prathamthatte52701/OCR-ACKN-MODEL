"""A client that disconnects in the middle of a bulk save must not leave a half-done state.

Half-done means rows written to the workbook but no exportedrows records: a later Save Again would
then append them a second time."""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from app.features.excel import service as excel_service
from app.features.excel.batch_test_support import (
    CLOCK,
    data_rows,
    make_doc,
    physical,
    post_bulk,
    seed_book,
    seed_settings,
    write_files,
)

WB26 = "Book2026"


@pytest.fixture(autouse=True)
def _clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(excel_service, "now_ist", lambda: CLOCK)


@pytest.fixture
def exports_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "exports"
    d.mkdir()
    monkeypatch.setattr(excel_service, "EXPORT_DIR", d)
    return d


async def test_cancelled_request_still_finishes_the_batch(
    client: Any, db: Any, make_user: Any, exports_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await make_user()
    await seed_book(db, user.id, WB26, 2026, True)
    await seed_settings(db, user.id, WB26, 2026)
    write_files(exports_dir, {physical(user.id, WB26): {"March": []}})
    docs = [await make_doc(db, user.id, f"C{i:03d}", "05/03/2026") for i in range(5)]

    real_append_rows = excel_service.append_rows
    written = asyncio.Event()

    async def append_then_wait(filename: str, items: list) -> Any:
        result = await real_append_rows(filename, items)
        written.set()  # the rows are in the workbook; the records are not inserted yet
        await asyncio.sleep(1.5)  # a cancellation point inside the vulnerable window
        return result

    monkeypatch.setattr(excel_service, "append_rows", append_then_wait)

    task = asyncio.ensure_future(post_bulk(client, user, docs))
    await asyncio.wait_for(written.wait(), timeout=60)
    task.cancel()  # the client gave up
    with pytest.raises(asyncio.CancelledError):
        await task

    # the work keeps running to completion in the background: wait for its LAST step (the audit
    # entry is written after the records, the exported flag and the old-row removal)
    for _ in range(240):
        if await db.auditlogs.count_documents({"action": "document_exported"}) == len(docs):
            break
        await asyncio.sleep(0.5)

    assert await db.exportedrows.count_documents({"userId": user.id}) == len(docs)
    for d in docs:
        assert (await db.documents.find_one({"_id": d}))["exported"] is True
    assert len(data_rows(exports_dir, user.id, WB26)) == len(docs)
    assert await db.auditlogs.count_documents({"action": "document_exported"}) == len(docs)
    assert not list(exports_dir.glob("*.tmp*"))

    # and a later Save Again replaces, it does not duplicate
    monkeypatch.setattr(excel_service, "append_rows", real_append_rows)
    again = await post_bulk(client, user, docs)
    assert again.status_code == 200 and again.json()["replaced"] == len(docs)
    assert len(data_rows(exports_dir, user.id, WB26)) == len(docs)
