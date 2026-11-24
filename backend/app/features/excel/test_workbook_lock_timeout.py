"""A workbook lock that stays busy longer than its timeout (30 s in production) must give the same
clean 409 as a workbook that is open in Excel - never a 500 from filelock.Timeout - and change
nothing. The timeout is shortened to 0.2 s by wrapping FileLock (never by waiting 30 s); the lock is
held by the test through its own FileLock on the sidecar .lock file."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import filelock
import openpyxl
import pytest
from bson import ObjectId

from app.features.excel import router as excel_router
from app.features.excel import service as excel_service

YEAR = excel_service.current_period()[0]
REAL_FILELOCK = filelock.FileLock


@pytest.fixture
def exports_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(excel_service, "EXPORT_DIR", tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def short_lock_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def short(path: str, timeout: float = -1, **kw: Any) -> Any:
        return REAL_FILELOCK(path, timeout=0.2, **kw)

    monkeypatch.setattr(excel_service, "FileLock", short)


def _lock_file(user_id: Any, name: str = "Book") -> str:
    physical = excel_service.physical_workbook_filename(user_id, name)
    return str(excel_service._lock_path(excel_service.file_path(physical)))


@contextmanager
def held(user_id: Any, name: str = "Book") -> Iterator[None]:
    lock = REAL_FILELOCK(_lock_file(user_id, name), timeout=5)
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


def assert_lock_is_free(user_id: Any, name: str = "Book") -> None:
    lock = REAL_FILELOCK(_lock_file(user_id, name), timeout=2)
    lock.acquire()  # raises filelock.Timeout when the code under test leaked the lock
    lock.release()


async def _doc(db: Any, owner: Any, number: str) -> ObjectId:
    now = datetime.now(UTC)
    res = await db.documents.insert_one(
        {
            "userId": owner.id,
            "autoName": number,
            "originalFilename": f"{number}.pdf",
            "mimeType": "application/pdf",
            "size": 10,
            "uploadStatus": "processed",
            "documentType": "Delivery Challan",
            "number": number,
            "date": f"05/10/{YEAR}",
            "edited": False,
            "exported": False,
            "isDeleted": False,
            "filePurged": True,
            "createdAt": now,
            "updatedAt": now,
        }
    )
    return res.inserted_id


async def _new_workbook(client: Any, user: Any, name: str = "Book") -> Any:
    return await client.post(
        "/api/documents/new-excel-file", headers=user.headers, json={"filename": name}
    )


def _rows(exports_dir: Path, user: Any, name: str = "Book") -> list[str]:
    path = exports_dir / f"{excel_service.physical_workbook_filename(user.id, name)}.xlsx"
    wb = openpyxl.load_workbook(path)
    return [str(r[1]) for ws in wb.worksheets for r in ws.iter_rows(min_row=2, values_only=True)]


def _leftovers(exports_dir: Path) -> list[str]:
    return sorted(p.name for p in exports_dir.iterdir() if ".tmp" in p.name)


# ---------------------------------------------------------------- routes
async def test_new_workbook_while_lock_busy_is_409_and_creates_nothing(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    u = await make_user()
    with held(u.id):
        r = await _new_workbook(client, u)
    assert r.status_code == 409, r.text
    assert "open in Excel" in r.json()["detail"]
    assert await db.workbooks.count_documents({}) == 0
    assert not list(exports_dir.glob("*.xlsx")) and not _leftovers(exports_dir)
    assert_lock_is_free(u.id)
    assert (await _new_workbook(client, u)).status_code == 200  # works once the lock is free


async def test_single_save_while_lock_busy_is_409_document_kept_then_retry_works(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    u = await make_user()
    assert (await _new_workbook(client, u)).status_code == 200
    first = await _doc(db, u, "820000001")
    second = await _doc(db, u, "820000002")
    assert (await client.post(f"/api/documents/{first}/save", headers=u.headers)).status_code == 200
    rows_before = _rows(exports_dir, u)
    with held(u.id):
        r = await client.post(f"/api/documents/{second}/save", headers=u.headers)
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == excel_router.FILE_BUSY_MESSAGE
    assert _rows(exports_dir, u) == rows_before and not _leftovers(exports_dir)
    doc = await db.documents.find_one({"_id": second})
    assert doc is not None and doc["exported"] is False  # the document is not lost or half-saved
    assert await db.exportedrows.count_documents({"documentId": second}) == 0
    assert_lock_is_free(u.id)
    retry = await client.post(f"/api/documents/{second}/save", headers=u.headers)
    assert retry.status_code == 200
    assert sorted(_rows(exports_dir, u)) == ["820000001", "820000002"]


async def test_bulk_save_while_lock_busy_fails_every_document_and_writes_nothing(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    u = await make_user()
    assert (await _new_workbook(client, u)).status_code == 200
    ids = [await _doc(db, u, n) for n in ("820000011", "820000012")]
    body = {"documentIds": [str(i) for i in ids]}
    with held(u.id):
        r = await client.post("/api/documents/bulk-save", headers=u.headers, json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["succeeded"] == []
    expected = [{"documentId": str(i), "reason": excel_router.FILE_BUSY_MESSAGE} for i in ids]
    assert out["failed"] == expected
    assert _rows(exports_dir, u) == [] and await db.exportedrows.count_documents({}) == 0
    assert_lock_is_free(u.id)
    r = await client.post("/api/documents/bulk-save", headers=u.headers, json=body)
    assert len(r.json()["succeeded"]) == 2


async def test_save_again_when_only_the_cleanup_lock_is_busy_keeps_both_rows_and_warns(
    client: Any, db: Any, make_user: Any, exports_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Save Again appends the new row, then removes the old one. If the second step cannot get the
    lock the new row stays, the old row stays, and the user is told; a retry cleans up."""
    u = await make_user()
    assert (await _new_workbook(client, u)).status_code == 200
    d = await _doc(db, u, "820000021")
    assert (await client.post(f"/api/documents/{d}/save", headers=u.headers)).status_code == 200
    real_append = excel_service.append_rows
    grabbed: list[Any] = []

    async def append_then_hold(filename: str, items: list) -> Path:
        out = await real_append(filename, items)
        lock = REAL_FILELOCK(_lock_file(u.id), timeout=5)
        lock.acquire()  # the cleanup step that follows cannot get it
        grabbed.append(lock)
        return out

    monkeypatch.setattr(excel_service, "append_rows", append_then_hold)
    try:
        r = await client.post(f"/api/documents/{d}/save", headers=u.headers)
    finally:
        for lock in grabbed:
            lock.release()
    assert r.status_code == 200, r.text
    assert "could not be removed" in r.json()["staleRowWarning"], r.text
    assert _rows(exports_dir, u) == ["820000021", "820000021"]  # old + new, nothing lost
    assert_lock_is_free(u.id)
    monkeypatch.setattr(excel_service, "append_rows", real_append)
    assert (await client.post(f"/api/documents/{d}/save", headers=u.headers)).status_code == 200
    assert _rows(exports_dir, u) == ["820000021"]  # the retry removed the stale rows


# ---------------------------------------------------------------- service level (every lock site)
async def test_every_lock_site_raises_file_locked_error_not_filelock_timeout(
    make_user: Any, db: Any, exports_dir: Path
) -> None:
    u = await make_user()
    name = excel_service.physical_workbook_filename(u.id, "Book")
    await excel_service.create_workbook(name, "October")
    row = {
        "documentType": "Delivery Challan",
        "number": "820000031",
        "date": f"05/10/{YEAR}",
        "timestamp": "2026-10-05T10:00:00",
    }
    before = _rows(exports_dir, u)
    gone = [{"documentType": "x", "number": "1"}]
    with held(u.id):
        with pytest.raises(excel_service.FileLockedError):
            await excel_service.create_workbook(name, "October")  # create (lock site 1)
        with pytest.raises(excel_service.FileLockedError):
            await excel_service.append_rows(name, [("October", row)])  # append (lock site 2)
        with pytest.raises(excel_service.FileLockedError):
            await excel_service.remove_rows(name, gone)  # remove (lock site 3)
        with pytest.raises(excel_service.FileLockedError):
            await excel_service.remove_rows_detailed(name, gone)  # remove, detailed (site 3)
    assert _rows(exports_dir, u) == before and not _leftovers(exports_dir)
    assert_lock_is_free(u.id)
    await excel_service.append_rows(name, [("October", row)])  # and it works once the lock is free
    assert _rows(exports_dir, u) == ["820000031"]
