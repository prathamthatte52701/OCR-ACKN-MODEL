"""Upload file names that clean to nothing (empty, spaces, only dots, only path separators) must be
rejected with a clean 4xx, for document upload, bulk upload and chat attachments, and must create
nothing (no document, no GridFS file, no chat message). Real names - plain, unicode, long, with a
path part - keep working. Fake Mongo; OCR is stubbed out."""

import io
from typing import Any

import pytest
from PIL import Image

import app.features.documents.router as docs_router

DOC_TYPE = "Tax Invoice"
NO_NAME_DOC = "This file has no usable name. Rename it and try again."
NO_FILE = "No file uploaded."
# (a raw tab is not tested: httpx sends it percent-encoded, i.e. as the usable name "%09")
UNUSABLE = ["", " ", "   ", ".", "..", "...", "/", "\\", "../", "..\\", " . ", "//", "./"]
USABLE = [
    "normal.png",
    "файл 日本.png",  # unicode
    "..png",
    ".png",
    "a/b.png",  # a path part: the file name b.png is used
    "x" * 300 + ".png",  # long names are accepted as before
]


def _png() -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (300, 200), "white").save(b, "PNG")
    return b.getvalue()


PNG = _png()


@pytest.fixture(autouse=True)
def no_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    async def noop(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(docs_router, "process_document", noop)


async def _nothing_stored(db: Any) -> bool:
    for name in (
        "documents",
        "fs.files",
        "fs.chunks",
        "chatmessages",
        "chatattachments",
        "chatfs.files",
        "chatfs.chunks",
    ):
        if await db[name].count_documents({}) != 0:
            return False
    return True


async def _upload(client: Any, user: Any, name: str) -> Any:
    return await client.post(
        "/api/documents/upload",
        headers=user.headers,
        files={"document": (name, PNG, "image/png")},
        data={"documentType": DOC_TYPE},
    )


async def _bulk(client: Any, user: Any, name: str) -> Any:
    return await client.post(
        "/api/documents/bulk-upload",
        headers=user.headers,
        files=[("documents", (name, PNG, "image/png"))],
        data={"documentTypes": [DOC_TYPE]},
    )


async def _chat(client: Any, user: Any, admin: Any, name: str) -> Any:
    return await client.post(
        "/api/chat/messages/file",
        headers=user.headers,
        files={"file": (name, PNG, "image/png")},
        data={"toAdminId": str(admin.id)},
    )


@pytest.mark.parametrize("name", UNUSABLE)
async def test_document_upload_rejects_unusable_name(
    name: str, client: Any, db: Any, make_user: Any
) -> None:
    u = await make_user()
    r = await _upload(client, u, name)
    assert r.status_code == 400, (name, r.status_code, r.text[:160])
    assert r.json()["detail"] in (NO_NAME_DOC, NO_FILE)
    assert await _nothing_stored(db)


@pytest.mark.parametrize("name", UNUSABLE)
async def test_bulk_upload_rejects_unusable_name_and_creates_nothing(
    name: str, client: Any, db: Any, make_user: Any
) -> None:
    u = await make_user()
    r = await _bulk(client, u, name)
    if name == "":  # nothing was selected: the whole request is refused
        assert r.status_code == 400 and r.json()["detail"] == NO_FILE
    else:  # like any other bad file in a batch: 201 with that file's own error
        assert r.status_code == 201, (name, r.status_code, r.text[:160])
        item = r.json()["results"][0]
        assert item.get("error") == NO_NAME_DOC and "document" not in item
    assert await _nothing_stored(db)


@pytest.mark.parametrize("name", UNUSABLE)
async def test_chat_attachment_rejects_unusable_name(
    name: str, client: Any, db: Any, make_user: Any
) -> None:
    u, a = await make_user(), await make_user("admin")
    r = await _chat(client, u, a, name)
    assert r.status_code == 422, (name, r.status_code, r.text[:160])
    assert r.json()["detail"] in (NO_NAME_DOC, "Attach exactly one file.")
    assert await _nothing_stored(db)


@pytest.mark.parametrize("name", USABLE)
async def test_real_names_still_work_everywhere(
    name: str, client: Any, db: Any, make_user: Any
) -> None:
    u, a = await make_user(), await make_user("admin")
    assert (await _upload(client, u, name)).status_code == 201
    bulk = await _bulk(client, u, name)
    assert bulk.status_code == 201
    assert (await _chat(client, u, a, name)).status_code == 201
    assert await db.documents.count_documents({}) == 2
    assert await db.chatattachments.count_documents({}) == 1


async def test_good_and_bad_names_in_one_batch_only_the_bad_one_fails(
    client: Any, db: Any, make_user: Any
) -> None:
    u = await make_user()
    r = await client.post(
        "/api/documents/bulk-upload",
        headers=u.headers,
        files=[("documents", ("ok.png", PNG, "image/png")), ("documents", (" ", PNG, "image/png"))],
        data={"documentTypes": [DOC_TYPE, DOC_TYPE]},
    )
    assert r.status_code == 201
    body = r.json()
    items = body["results"]
    assert "document" in items[0] and items[1].get("error") == NO_NAME_DOC
    assert await db.documents.count_documents({}) == 1
    assert await db["fs.files"].count_documents({}) == 1
