"""T13: upload size is capped before/while reading the body, not after.

No test here uploads a *valid* document (that would start real OCR); they all
use over-limit or wrong-type payloads so nothing reaches the OCR pipeline."""

from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.core.upload_limit import UploadSizeLimitMiddleware

MB = 1024 * 1024


async def test_declared_content_length_over_limit_rejected_before_body_read() -> None:
    body_reads = 0
    sent: list[dict[str, Any]] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:  # must never run
        raise AssertionError("route must not be reached")

    async def receive() -> Any:
        nonlocal body_reads
        body_reads += 1
        return {"type": "http.request", "body": b"x", "more_body": False}

    async def send(message: Any) -> None:
        sent.append(message)

    mw = UploadSizeLimitMiddleware(app, {"/up": 1 * MB})
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/up",
        "headers": [(b"content-length", str(50 * MB).encode())],
    }
    await mw(scope, receive, send)
    assert body_reads == 0  # refused without reading a single body byte
    assert sent[0]["status"] == 413


async def test_streamed_body_without_content_length_cut_off() -> None:
    chunks_read = 0
    sent: list[dict[str, Any]] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        while True:  # a greedy route that reads the whole body
            message = await receive()
            if not message.get("more_body"):
                break

    async def receive() -> Any:
        nonlocal chunks_read
        chunks_read += 1
        return {"type": "http.request", "body": b"x" * MB, "more_body": True}

    async def send(message: Any) -> None:
        sent.append(message)

    mw = UploadSizeLimitMiddleware(app, {"/up": 3 * MB})
    scope = {"type": "http", "method": "POST", "path": "/up", "headers": []}
    await mw(scope, receive, send)
    assert chunks_read <= 5  # stopped right after crossing 3 MB, did not read forever
    assert sent[0]["status"] == 413


async def test_other_paths_and_methods_untouched() -> None:
    called: list[str] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        called.append(scope["path"])

    mw = UploadSizeLimitMiddleware(app, {"/up": 10})
    big = {
        "type": "http",
        "method": "POST",
        "path": "/other",
        "headers": [(b"content-length", b"999999")],
    }
    await mw(big, None, None)  # type: ignore[arg-type]
    get = {
        "type": "http",
        "method": "GET",
        "path": "/up",
        "headers": [(b"content-length", b"999999")],
    }
    await mw(get, None, None)  # type: ignore[arg-type]
    assert called == ["/other", "/up"]


async def _gen(total: int) -> AsyncIterator[bytes]:
    """A syntactically valid multipart body whose file part is `total` bytes, so
    the server's parser keeps reading until the middleware cuts it off."""
    crlf = bytes([13, 10])
    yield (
        b"--zz"
        + crlf
        + b'Content-Disposition: form-data; name="document"; filename="a.pdf"'
        + crlf
        + b"Content-Type: application/pdf"
        + crlf
        + crlf
    )
    sent = 0
    while sent < total:
        yield b"y" * min(MB, total - sent)
        sent += MB
    yield crlf + b"--zz--" + crlf


@pytest.mark.parametrize("path", ["/api/documents/upload", "/api/documents/bulk-upload"])
async def test_endpoint_rejects_huge_streamed_request_with_413(
    client: Any, make_user: Any, path: str
) -> None:
    u = await make_user()
    huge = 60 * MB if path.endswith("bulk-upload") else 8 * MB
    headers = {**u.headers, "content-type": "multipart/form-data; boundary=zz"}
    r = await client.post(path, headers=headers, content=_gen(huge))
    assert r.status_code == 413
    assert r.json()["detail"] == "File size must be 5 MB or less."


async def test_single_upload_over_5mb_gets_400_message(client: Any, make_user: Any) -> None:
    u = await make_user()
    big = b"%PDF-1.4 " + b"0" * int(5.5 * MB)
    r = await client.post(
        "/api/documents/upload",
        headers=u.headers,
        files={"document": ("big.pdf", big, "application/pdf")},
        data={"documentType": "Tax Invoice"},
    )
    assert r.status_code == 400 and r.json()["detail"] == "File size must be 5 MB or less."


async def test_bulk_upload_oversize_file_reported_per_file_without_ocr(
    client: Any, make_user: Any, db: Any
) -> None:
    u = await make_user()
    big = b"%PDF-1.4 " + b"0" * int(5.5 * MB)
    r = await client.post(
        "/api/documents/bulk-upload",
        headers=u.headers,
        files=[("documents", ("big.pdf", big, "application/pdf"))],
        data={"documentTypes": "Tax Invoice"},
    )
    assert r.status_code == 201
    (result,) = r.json()["results"]
    assert result["error"] == "File size must be 5 MB or less."
    assert await db.documents.count_documents({}) == 0


async def test_wrong_type_small_file_still_gets_normal_validation_error(
    client: Any, make_user: Any
) -> None:
    u = await make_user()
    r = await client.post(
        "/api/documents/upload",
        headers=u.headers,
        files={"document": ("a.txt", b"hello", "text/plain")},
        data={"documentType": "Tax Invoice"},
    )
    assert r.status_code == 400 and "JPG" in r.json()["detail"]
