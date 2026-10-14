"""POST /documents/download-all: id/size caps, per-user single flight, skip rules,
temp-file + slot cleanup (success, error, 413, client disconnect)."""

import asyncio
import io
import json
import os
import zipfile
from collections.abc import MutableMapping
from datetime import UTC, datetime
from typing import Any

import pytest
from bson import ObjectId

from app.features.documents import router as docs_router
from app.features.documents.gridfs_service import upload_buffer
from app.main import app

URL = "/api/documents/download-all"


async def _doc(db: Any, user: Any, data: bytes | None = b"hello", **over: Any) -> ObjectId:
    now = datetime.now(UTC)
    d: dict[str, Any] = {
        "userId": user.id,
        "documentType": "Delivery Challan",
        "number": str(ObjectId())[-8:],
        "date": "15/03/2026",
        "originalFilename": "scan.pdf",
        "mimeType": "application/pdf",
        "size": len(data or b""),
        "createdAt": now,
        "updatedAt": now,
    }
    if data is not None:
        d["gridFsFileId"] = await upload_buffer(data, "scan.pdf", "application/pdf")
    d.update(over)
    return (await db.documents.insert_one(d)).inserted_id


def _ids(ids: list[ObjectId]) -> dict[str, Any]:
    return {"documentIds": [str(i) for i in ids]}


@pytest.fixture(autouse=True)
def _clean_state() -> Any:
    docs_router._active_downloads.clear()
    yield
    docs_router._active_downloads.clear()


@pytest.fixture
def tmp_paths(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Records every temp file the route creates."""
    paths: list[str] = []
    real = docs_router.tempfile.mkstemp

    def spy(*a: Any, **k: Any) -> Any:
        fd, p = real(*a, **k)
        paths.append(p)
        return fd, p

    monkeypatch.setattr(docs_router.tempfile, "mkstemp", spy)
    return paths


@pytest.fixture
def spy_download(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    calls: list[Any] = []
    real = docs_router.download_buffer

    async def spy(fid: Any) -> bytes:
        calls.append(fid)
        return await real(fid)

    monkeypatch.setattr(docs_router, "download_buffer", spy)
    return calls


async def test_zero_ids_is_422(client: Any, make_user: Any) -> None:
    u = await make_user()
    res = await client.post(URL, headers=u.headers, json={"documentIds": []})
    assert res.status_code == 422


async def test_over_id_cap_is_400(client: Any, make_user: Any) -> None:
    u = await make_user()
    res = await client.post(URL, headers=u.headers, json=_ids([ObjectId() for _ in range(51)]))
    assert res.status_code == 400
    assert res.json()["detail"] == "Select fewer documents."
    assert not docs_router._active_downloads


async def test_exactly_id_cap_ok(client: Any, make_user: Any) -> None:
    u = await make_user()
    res = await client.post(URL, headers=u.headers, json=_ids([ObjectId() for _ in range(50)]))
    assert res.status_code == 200
    assert res.headers["x-download-included"] == "0"
    assert res.headers["x-download-skipped"] == "50"
    assert res.headers["x-download-total"] == "50"


async def test_over_size_cap_is_413_and_reads_nothing(
    db: Any, client: Any, make_user: Any, spy_download: list[Any], tmp_paths: list[str]
) -> None:
    u = await make_user()
    big = docs_router.MAX_DOWNLOAD_ALL_BYTES // 2 + 1
    ids = [await _doc(db, u, size=big) for _ in range(2)]
    res = await client.post(URL, headers=u.headers, json=_ids(ids))
    assert res.status_code == 413
    assert res.json()["detail"] == (
        "Selected files are too large to download together. Select fewer documents."
    )
    assert spy_download == []
    assert tmp_paths == []
    assert not docs_router._active_downloads  # slot released after 413
    again = await client.post(URL, headers=u.headers, json=_ids(ids[:1]))
    assert again.status_code == 200


async def test_happy_path_zip_and_headers(
    db: Any, client: Any, make_user: Any, tmp_paths: list[str]
) -> None:
    u = await make_user()
    payloads = [os.urandom(1000 + i) for i in range(3)]
    # Same number+date twice (names must stay unique) and a traversal-style number.
    ids = [
        await _doc(db, u, payloads[0], number="X1"),
        await _doc(db, u, payloads[1], number="X1"),
        await _doc(db, u, payloads[2], number="../../evil:name"),
    ]
    res = await client.post(URL, headers=u.headers, json=_ids(ids))
    assert res.status_code == 200
    h = res.headers
    assert h["content-type"] == "application/zip"
    assert 'filename="documents.zip"' in h["content-disposition"]
    assert (h["x-download-included"], h["x-download-skipped"], h["x-download-total"]) == (
        "3",
        "0",
        "3",
    )
    assert int(h["content-length"]) == len(res.content)
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        assert zf.testzip() is None
        names = zf.namelist()
        assert len(set(names)) == 3
        assert all("/" not in n and "\\" not in n and ":" not in n for n in names)
        assert sorted(zf.read(n) for n in names) == sorted(payloads)
    assert not docs_router._active_downloads
    assert len(tmp_paths) == 1 and not os.path.exists(tmp_paths[0])


async def test_other_users_ids_skipped(db: Any, client: Any, make_user: Any) -> None:
    a, b = await make_user(), await make_user()
    mine = await _doc(db, a, b"mine-data")
    theirs = await _doc(db, b, b"secret-data")
    res = await client.post(URL, headers=a.headers, json=_ids([mine, theirs]))
    assert res.status_code == 200
    assert res.headers["x-download-included"] == "1"
    assert res.headers["x-download-skipped"] == "1"
    assert res.headers["x-download-total"] == "2"
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        assert [zf.read(n) for n in zf.namelist()] == [b"mine-data"]


async def test_unusable_docs_skipped(
    db: Any, client: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    u = await make_user()
    good = await _doc(db, u, b"good")
    purged = await _doc(db, u, b"x", filePurged=True)
    nofile = await _doc(db, u, None)
    deleted = await _doc(db, u, b"x", isDeleted=True)
    gone = await _doc(db, u, b"x", gridFsFileId=ObjectId())  # GridFS NoFile
    broken = await _doc(db, u, b"boom")
    broken_fid = (await db.documents.find_one({"_id": broken}))["gridFsFileId"]
    real = docs_router.download_buffer

    async def flaky(fid: Any) -> bytes:
        if fid == broken_fid:
            raise RuntimeError("gridfs down")
        return await real(fid)

    monkeypatch.setattr(docs_router, "download_buffer", flaky)
    ids = [good, purged, nofile, deleted, gone, broken, ObjectId()]
    res = await client.post(URL, headers=u.headers, json=_ids(ids))
    assert res.status_code == 200
    assert res.headers["x-download-included"] == "1"
    assert res.headers["x-download-skipped"] == "6"
    assert res.headers["x-download-total"] == "7"
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        assert [zf.read(n) for n in zf.namelist()] == [b"good"]


async def test_duplicate_ids_deduplicated(
    db: Any, client: Any, make_user: Any, spy_download: list[Any]
) -> None:
    u = await make_user()
    d = await _doc(db, u, b"once")
    res = await client.post(URL, headers=u.headers, json=_ids([d, d, d]))
    assert res.status_code == 200
    assert len(spy_download) == 1
    assert res.headers["x-download-included"] == "1"
    assert res.headers["x-download-skipped"] == "0"
    assert res.headers["x-download-total"] == "3"
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        assert len(zf.namelist()) == 1


async def test_second_request_429_while_running_other_user_not_blocked(
    db: Any, client: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = await make_user(), await make_user()
    da, dbid = await _doc(db, a, b"a"), await _doc(db, b, b"b")
    entered, release = asyncio.Event(), asyncio.Event()
    real = docs_router.download_buffer

    async def held(fid: Any) -> bytes:
        entered.set()
        await release.wait()
        return await real(fid)

    monkeypatch.setattr(docs_router, "download_buffer", held)
    first = asyncio.create_task(client.post(URL, headers=a.headers, json=_ids([da])))
    await asyncio.wait_for(entered.wait(), 10)
    second = await client.post(URL, headers=a.headers, json=_ids([da]))
    assert second.status_code == 429
    assert second.json()["detail"] == "A download is already running."
    monkeypatch.setattr(docs_router, "download_buffer", real)
    other = await client.post(URL, headers=b.headers, json=_ids([dbid]))
    assert other.status_code == 200
    release.set()
    assert (await first).status_code == 200
    assert not docs_router._active_downloads
    assert (await client.post(URL, headers=a.headers, json=_ids([da]))).status_code == 200


async def test_slot_and_tempfile_released_after_build_failure(
    db: Any,
    client: Any,
    make_user: Any,
    tmp_paths: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    u = await make_user()
    d = await _doc(db, u, b"data")
    real_log = docs_router.log_action

    async def boom(*_: Any, **__: Any) -> None:
        raise RuntimeError("audit down")

    monkeypatch.setattr(docs_router, "log_action", boom)
    with pytest.raises(RuntimeError):
        await client.post(URL, headers=u.headers, json=_ids([d]))
    assert not docs_router._active_downloads
    assert len(tmp_paths) == 1 and not os.path.exists(tmp_paths[0])
    monkeypatch.setattr(docs_router, "log_action", real_log)
    assert (await client.post(URL, headers=u.headers, json=_ids([d]))).status_code == 200


async def test_slot_and_tempfile_released_on_client_disconnect(
    db: Any, make_user: Any, tmp_paths: list[str]
) -> None:
    """Drives the ASGI app directly: after the first body chunk the client
    disconnects (receive -> http.disconnect; send keeps dropping, as uvicorn does)."""
    u = await make_user()
    d = await _doc(db, u, os.urandom(1024 * 1024))  # many 64 KB chunks
    body = json.dumps(_ids([d])).encode()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": URL,
        "raw_path": URL.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"test"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"authorization", u.headers["Authorization"].encode()),
        ],
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
    }
    sent_body = asyncio.Event()
    state = {"sent": 0, "req": False}

    async def receive() -> dict[str, Any]:
        if not state["req"]:
            state["req"] = True
            return {"type": "http.request", "body": body, "more_body": False}
        await sent_body.wait()
        return {"type": "http.disconnect"}

    async def send(msg: MutableMapping[str, Any]) -> None:
        if msg["type"] == "http.response.body" and msg.get("body"):
            state["sent"] += 1
            sent_body.set()
            # like uvicorn: once the client is gone, send() silently drops

    await asyncio.wait_for(app(scope, receive, send), 30)
    assert state["sent"] < 10  # stream was cut short, not fully drained
    assert state["sent"] >= 1
    assert not docs_router._active_downloads
    assert len(tmp_paths) == 1 and not os.path.exists(tmp_paths[0])


async def test_stale_slot_is_released_but_fresh_slot_still_429(
    db: Any, client: Any, make_user: Any
) -> None:
    import time

    u = await make_user()
    body = {"documentIds": [str(ObjectId())]}
    timeout = docs_router.DOWNLOAD_SLOT_TIMEOUT_SECONDS

    docs_router._active_downloads[u.id] = time.monotonic() - 5  # fresh: still running
    res = await client.post("/api/documents/download-all", headers=u.headers, json=body)
    assert res.status_code == 429
    assert res.json()["detail"] == "A download is already running."

    docs_router._active_downloads[u.id] = time.monotonic() - timeout - 1  # stale: leaked
    res = await client.post("/api/documents/download-all", headers=u.headers, json=body)
    assert res.status_code == 200
    assert not docs_router._active_downloads  # the new run freed its own slot
