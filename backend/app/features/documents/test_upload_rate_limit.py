"""Per-IP rate limits: single upload 120/h, bulk 30/h (separate budgets), signup 15/h,
new-excel-file 20/h. The limiter is switched on only for these tests. OCR is mocked."""

import io
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from PIL import Image

from app.core.rate_limit import limiter
from app.features.documents import router as docs_router
from app.main import app


@pytest.fixture(autouse=True)
def _limiter_on(monkeypatch: Any) -> Iterator[None]:
    async def fake(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(docs_router, "process_document", fake)
    old = limiter.enabled
    limiter.enabled = True
    limiter.reset()
    try:
        yield
    finally:
        limiter.reset()
        limiter.enabled = old


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


PNG = _png()


async def _upload(client: Any, headers: dict[str, str]) -> Any:
    return await client.post(
        "/api/documents/upload",
        headers=headers,
        files={"document": ("a.png", PNG, "image/png")},
        data={"documentType": "Tax Invoice"},
    )


async def _bulk(client: Any, headers: dict[str, str]) -> Any:
    return await client.post(
        "/api/documents/bulk-upload",
        headers=headers,
        files=[("documents", ("a.png", PNG, "image/png"))],
        data={"documentTypes": ["Tax Invoice"]},
    )


def _assert_clean_429(res: Any) -> None:
    assert res.status_code == 429
    body = res.json()  # must be JSON
    text = res.text
    assert "Traceback" not in text
    assert 'File "' not in text
    assert "\\backend" not in text and "/backend/" not in text and "site-packages" not in text
    assert body is not None


def _other_ip_client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, client=("10.9.8.7", 4321))
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_single_upload_120_ok_121_limited(client: Any, make_user: Any) -> None:
    u = await make_user()
    for i in range(1, 121):
        res = await _upload(client, u.headers)
        assert res.status_code == 201, f"request {i}: {res.status_code} {res.text}"
    _assert_clean_429(await _upload(client, u.headers))


async def test_other_ip_unaffected_when_first_limited(client: Any, make_user: Any) -> None:
    u = await make_user()
    for _ in range(120):
        await _upload(client, u.headers)
    _assert_clean_429(await _upload(client, u.headers))
    async with _other_ip_client() as other:
        assert (await _upload(other, u.headers)).status_code == 201


async def test_bulk_30_ok_31_limited_and_budgets_separate(client: Any, make_user: Any) -> None:
    u = await make_user()
    for i in range(1, 31):
        res = await _bulk(client, u.headers)
        assert res.status_code == 201, f"bulk {i}: {res.status_code} {res.text}"
    _assert_clean_429(await _bulk(client, u.headers))
    assert (await _upload(client, u.headers)).status_code == 201


async def test_signup_16th_limited(client: Any) -> None:
    for i in range(16):
        tag = uuid.uuid4().hex[:8]
        res = await client.post(
            "/api/auth/signup",
            json={
                "username": f"usr{tag}",
                "email": f"s{tag}@looptest.local",
                "password": "Xq7!mZv#4Lp2",
            },
        )
        if i < 15:
            assert res.status_code != 429, f"signup {i + 1}: {res.text}"
        else:
            _assert_clean_429(res)


async def test_new_excel_file_21st_limited(client: Any, make_user: Any) -> None:
    u = await make_user()
    for i in range(21):
        res = await client.post(
            "/api/documents/new-excel-file",
            headers=u.headers,
            json={"filename": f"book{i}_{uuid.uuid4().hex[:6]}"},
        )
        if i < 20:
            assert res.status_code != 429, f"call {i + 1}: {res.text}"
        else:
            _assert_clean_429(res)


async def test_reset_gives_fresh_counter(client: Any, make_user: Any) -> None:
    u = await make_user()
    for _ in range(30):
        assert (await _bulk(client, u.headers)).status_code == 201
    assert (await _bulk(client, u.headers)).status_code == 429
    limiter.reset()
    assert (await _bulk(client, u.headers)).status_code == 201
