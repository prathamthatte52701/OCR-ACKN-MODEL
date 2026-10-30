"""Chat file attachments: validation (by bytes), re-encoding, access, limits, failure cleanup."""

import io
from typing import Any

import pytest
from PIL import Image

from app.features.chat import files, service
from app.features.chat.chat_testkit import BASE, limiter_on  # noqa: F401  (limiter_on: fixture)

MB = 1024 * 1024
FILE_URL = f"{BASE}/messages/file"


def img_bytes(fmt: str = "JPEG", size: tuple[int, int] = (64, 48), **kw: Any) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(out, fmt, **kw)
    return out.getvalue()


def pdf_bytes(total: int = 2000) -> bytes:
    head, tail = b"%PDF-1.4\n", b"\n%%EOF\n"
    return head + b"0" * (total - len(head) - len(tail)) + tail


def padded(data: bytes, total: int) -> bytes:
    return data + b"\x00" * (total - len(data))  # junk after the image data: valid for Pillow


async def up(
    client: Any,
    who: Any,
    data: bytes,
    name: str = "pic.jpg",
    ctype: str = "application/octet-stream",
    *,
    to: Any = None,
    text: str | None = None,
    extra: dict | None = None,
) -> Any:
    fields: dict[str, str] = dict(extra or {})
    if to is not None:
        fields["userId" if who.__dict__.get("_admin") else "toAdminId"] = str(to.id)
    if text is not None:
        fields["text"] = text
    return await client.post(
        FILE_URL, headers=who.headers, files={"file": (name, data, ctype)}, data=fields
    )


async def stored_count(db: Any) -> tuple[int, int]:
    return (
        await db["chatfs.files"].count_documents({}),
        await db.chatattachments.count_documents({}),
    )


async def get_stored(db: Any, att_id: str) -> bytes:
    rec = await db.chatattachments.find_one({"_id": service.parse_object_id(att_id, "x")})
    stream = (
        await __import__("app.core.database", fromlist=["x"])
        .get_chat_gridfs()
        .open_download_stream(rec["storedFileId"])
    )
    return await stream.read()


# ---------- sending and shape ----------


async def test_user_sends_image_with_caption(client: Any, db: Any, trio: Any) -> None:
    u, adm, _ = trio
    r = await up(client, u, img_bytes(), "Invoice 1.jpg", to=adm, text="  see this ")
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["text"] == "see this" and m["mine"] is True
    att = m["attachment"]
    assert att["name"] == "Invoice 1.jpg" and att["kind"] == "image" and att["expired"] is False
    assert att["size"] == len(await get_stored(db, att["id"]))
    assert await stored_count(db) == (1, 1)


async def test_file_without_caption_and_text_message_has_null_attachment(
    client: Any, trio: Any
) -> None:
    u, adm, _ = trio
    r = await up(client, u, pdf_bytes(), "a.pdf", to=adm)
    assert (
        r.status_code == 201 and r.json()["text"] == "" and r.json()["attachment"]["kind"] == "pdf"
    )
    t = await client.post(
        f"{BASE}/messages", headers=u.headers, json={"toAdminId": str(adm.id), "text": "plain"}
    )
    assert t.json()["attachment"] is None
    listing = (await client.get(f"{BASE}/messages", headers=u.headers)).json()["messages"]
    assert [m["attachment"] is not None for m in listing] == [True, False]


async def test_admin_sends_to_user_and_second_admin_can_open(
    client: Any, db: Any, trio: Any
) -> None:
    u, adm, adm2 = trio
    r = await up(client, adm, img_bytes("PNG"), "x.png", to=u)
    assert r.status_code == 201, r.text
    aid = r.json()["attachment"]["id"]
    for who in (u, adm, adm2):
        g = await client.get(f"{BASE}/files/{aid}", headers=who.headers)
        assert g.status_code == 200 and g.headers["content-type"] == "image/png"


async def test_caption_still_limited_to_1000_and_file_required(client: Any, trio: Any) -> None:
    u, adm, _ = trio
    assert (await up(client, u, img_bytes(), to=adm, text="x" * 1001)).status_code == 422
    r = await client.post(FILE_URL, headers=u.headers, data={"toAdminId": str(adm.id)})
    assert r.status_code == 422


async def test_wrong_role_fields_and_two_files(client: Any, db: Any, trio: Any) -> None:
    u, adm, _ = trio
    r = await up(client, u, img_bytes(), extra={"toAdminId": str(adm.id), "userId": str(u.id)})
    assert r.status_code == 422
    r = await up(client, adm, img_bytes(), extra={"userId": str(u.id), "toAdminId": str(adm.id)})
    assert r.status_code == 422
    r = await client.post(
        FILE_URL,
        headers=u.headers,
        data={"toAdminId": str(adm.id)},
        files=[
            ("file", ("a.jpg", img_bytes(), "image/jpeg")),
            ("file", ("b.jpg", img_bytes(), "image/jpeg")),
        ],
    )
    assert r.status_code == 422
    assert await stored_count(db) == (0, 0)


async def test_bad_recipient_leaves_no_file(
    client: Any, db: Any, trio: Any, make_user: Any
) -> None:
    u, adm, _ = trio
    ghost = await make_user(role="admin", status="rejected")
    for to in (ghost, u):  # a rejected admin, and a plain user as the "admin"
        assert (await up(client, u, img_bytes(), to=to)).status_code == 422
    assert (await up(client, u, img_bytes(), extra={"toAdminId": "nope"})).status_code == 422
    assert await stored_count(db) == (0, 0)


async def test_failure_after_store_removes_the_file(
    client: Any, db: Any, trio: Any, monkeypatch: Any
) -> None:
    u, adm, _ = trio

    async def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("db down")

    monkeypatch.setattr(service, "_insert", boom)
    with pytest.raises(RuntimeError):
        await up(client, u, img_bytes(), to=adm)
    assert await stored_count(db) == (0, 0)


# ---------- size boundaries ----------


async def test_image_exactly_2mb_ok_one_more_byte_rejected(client: Any, db: Any, trio: Any) -> None:
    u, adm, _ = trio
    base = img_bytes()
    ok = await up(client, u, padded(base, 2 * MB), to=adm)
    assert ok.status_code == 201, ok.text
    n = await stored_count(db)
    big = await up(client, u, padded(base, 2 * MB + 1), to=adm)
    assert big.status_code == 413 and big.json()["detail"] == "Images can be up to 2 MB."
    assert await stored_count(db) == n


async def test_pdf_exactly_3mb_ok_one_more_byte_rejected(client: Any, db: Any, trio: Any) -> None:
    u, adm, _ = trio
    assert (await up(client, u, pdf_bytes(3 * MB), "d.pdf", to=adm)).status_code == 201
    n = await stored_count(db)
    big = await up(client, u, pdf_bytes(3 * MB + 1), "d.pdf", to=adm)
    assert big.status_code == 413
    assert await stored_count(db) == n


async def test_pdf_between_2_and_3mb_ok_but_image_of_that_size_is_not(
    client: Any, trio: Any
) -> None:
    u, adm, _ = trio
    assert (await up(client, u, pdf_bytes(2 * MB + 5), "d.pdf", to=adm)).status_code == 201
    r = await up(client, u, padded(img_bytes(), 2 * MB + 5), to=adm)
    assert r.status_code == 413


async def test_oversize_body_cut_by_middleware(client: Any, db: Any, trio: Any) -> None:
    u, adm, _ = trio
    r = await up(client, u, b"%PDF-" + b"0" * (5 * MB), "big.pdf", to=adm)
    assert r.status_code == 413 and "too large" in r.json()["detail"]
    assert await stored_count(db) == (0, 0)


# ---------- disguises ----------


async def test_kind_follows_bytes_not_name_or_browser_type(client: Any, trio: Any) -> None:
    u, adm, _ = trio
    r = await up(client, u, img_bytes("PNG"), "fake.pdf", "application/pdf", to=adm)
    assert r.status_code == 201 and r.json()["attachment"]["kind"] == "image"
    r = await up(client, u, pdf_bytes(), "fake.jpg", "image/jpeg", to=adm)
    assert r.status_code == 201 and r.json()["attachment"]["kind"] == "pdf"


@pytest.mark.parametrize(
    "name,data",
    [
        ("a.pdf", b"<html><script>alert(1)</script></html>"),
        ("a.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><script>1</script></svg>'),
        ("a.gif", img_bytes("GIF")),
        ("a.txt", b"hello"),
        ("a.jpg", b"\x00\x01"),
    ],
)
async def test_disallowed_types(client: Any, db: Any, trio: Any, name: str, data: bytes) -> None:
    u, adm, _ = trio
    r = await up(client, u, data, name, to=adm)
    assert r.status_code == 422 and r.json()["detail"] == files.BAD_TYPE
    assert await stored_count(db) == (0, 0)


async def test_empty_truncated_corrupt_and_pdf_without_eof(client: Any, db: Any, trio: Any) -> None:
    u, adm, _ = trio
    jpg = img_bytes(size=(400, 300))
    cases = [
        b"",
        jpg[: len(jpg) // 2],
        b"\x89PNG\r\n\x1a\n" + b"garbage" * 20,
        b"%PDF-1.4\nno end marker here",
    ]
    for data in cases:
        r = await up(client, u, data, "x.bin", to=adm)
        assert r.status_code == 422, (data[:12], r.text)
    assert await stored_count(db) == (0, 0)


async def test_decompression_bomb_and_animated_rejected(client: Any, db: Any, trio: Any) -> None:
    u, adm, _ = trio
    out = io.BytesIO()
    Image.new("L", (6000, 6000)).save(out, "PNG", optimize=True)  # 36 Mpx, tiny file
    assert len(out.getvalue()) < 200_000
    assert (await up(client, u, out.getvalue(), "b.png", to=adm)).status_code == 422
    anim = io.BytesIO()
    frames = [Image.new("RGB", (20, 20), c) for c in ("red", "blue")]
    frames[0].save(anim, "WEBP", save_all=True, append_images=frames[1:], duration=50)
    assert (await up(client, u, anim.getvalue(), "a.webp", to=adm)).status_code == 422
    assert await stored_count(db) == (0, 0)


async def test_polyglot_tail_is_dropped_by_reencode(client: Any, db: Any, trio: Any) -> None:
    u, adm, _ = trio
    evil = img_bytes() + b"<script>alert(1)</script>"
    r = await up(client, u, evil, "p.jpg", to=adm)
    assert r.status_code == 201
    stored = await get_stored(db, r.json()["attachment"]["id"])
    assert b"<script" not in stored and stored[:3] == b"\xff\xd8\xff"


# ---------- re-encoding ----------


async def test_exif_gps_removed_and_big_photo_shrunk(client: Any, db: Any, trio: Any) -> None:
    u, adm, _ = trio
    exif = Image.Exif()
    exif[0x010F] = "FakeCam"
    exif[0x8825] = {1: "N", 2: (12.0, 30.0, 0.0), 3: "E", 4: (77.0, 10.0, 0.0)}
    out = io.BytesIO()
    Image.linear_gradient("L").resize((4000, 3000)).convert("RGB").save(
        out, "JPEG", quality=95, exif=exif
    )
    original = out.getvalue()
    assert b"FakeCam" in original
    r = await up(client, u, original, "photo.jpg", to=adm)
    assert r.status_code == 201, r.text
    stored = await get_stored(db, r.json()["attachment"]["id"])
    with Image.open(io.BytesIO(stored)) as im:
        assert max(im.size) == 1920 and im.size == (1920, 1440)
        assert len(im.getexif()) == 0 and b"FakeCam" not in stored
    assert len(stored) < len(original)
    assert r.json()["attachment"]["size"] == len(stored)


async def test_small_image_not_scaled_up_and_png_stays_png(client: Any, db: Any, trio: Any) -> None:
    u, adm, _ = trio
    r = await up(client, u, img_bytes("PNG", (100, 50)), "s.png", to=adm)
    stored = await get_stored(db, r.json()["attachment"]["id"])
    with Image.open(io.BytesIO(stored)) as im:
        assert im.format == "PNG" and im.size == (100, 50)
    r = await up(client, u, img_bytes("WEBP", (30, 20)), "s.webp", to=adm)
    with Image.open(io.BytesIO(await get_stored(db, r.json()["attachment"]["id"]))) as im:
        assert im.format == "WEBP" and im.size == (30, 20)


async def test_pdf_stored_as_is(client: Any, db: Any, trio: Any) -> None:
    u, adm, _ = trio
    pdf = pdf_bytes(3000)
    r = await up(client, u, pdf, "d.pdf", to=adm)
    assert await get_stored(db, r.json()["attachment"]["id"]) == pdf


# ---------- names ----------


@pytest.mark.parametrize(
    "raw,kind,expected",
    [
        ("../../etc/passwd.pdf", "pdf", "passwd.pdf"),
        ("C:\\temp\\x.jpg", "image", "x.jpg"),
        ("a\u202eexe.pdf\u202c", "pdf", "aexe.pdf"),
        ("   ", "image", "image"),
        ("   ", "pdf", "document"),
        ("..", "pdf", "document"),
        ("a   b\t c.png", "image", "a b c.png"),
        ("नमस्ते.pdf", "pdf", "नमस्ते.pdf"),
    ],
)
def test_clean_name(raw: str, kind: str, expected: str) -> None:
    assert files.clean_name(raw, kind) == expected


def test_clean_name_300_chars_keeps_extension() -> None:
    n = files.clean_name("x" * 300 + ".pdf", "pdf")
    assert len(n) == 100 and n.endswith(".pdf")


async def test_nasty_filename_headers_stay_safe(client: Any, trio: Any) -> None:
    u, adm, _ = trio
    r = await up(client, u, pdf_bytes(), 'a";b\'c; x=y"\r\n.pdf', to=adm)
    assert r.status_code == 201
    g = await client.get(f"{BASE}/files/{r.json()['attachment']['id']}", headers=u.headers)
    cd = g.headers["content-disposition"]
    assert cd.startswith("attachment;") and "\n" not in cd and "\r" not in cd
    assert cd.count('"') == 2  # only the two delimiting quotes
    r = await up(client, u, pdf_bytes(), "रिपोर्ट.pdf", to=adm)
    g = await client.get(f"{BASE}/files/{r.json()['attachment']['id']}", headers=u.headers)
    assert "filename*=UTF-8''%E0%A4" in g.headers["content-disposition"]


# ---------- serving and access ----------


async def test_headers_and_dispositions(client: Any, trio: Any) -> None:
    u, adm, _ = trio
    img = await up(client, u, img_bytes(), "i.jpg", to=adm)
    pdf = await up(client, u, pdf_bytes(), "d.pdf", to=adm)
    gi = await client.get(f"{BASE}/files/{img.json()['attachment']['id']}", headers=u.headers)
    gp = await client.get(f"{BASE}/files/{pdf.json()['attachment']['id']}", headers=u.headers)
    for g, ctype, disp in ((gi, "image/jpeg", "inline"), (gp, "application/pdf", "attachment")):
        assert g.status_code == 200 and g.headers["content-type"] == ctype
        assert g.headers["x-content-type-options"] == "nosniff"
        assert g.headers["cache-control"] == "private, no-store"
        assert g.headers["content-security-policy"] == "default-src 'none'; sandbox"
        assert g.headers["content-disposition"].startswith(disp)


async def test_access_rules(client: Any, make_user: Any, trio: Any) -> None:
    u, adm, adm2 = trio
    other = await make_user()
    r = await up(client, u, img_bytes(), to=adm)
    url = f"{BASE}/files/{r.json()['attachment']['id']}"
    assert (await client.get(url)).status_code == 401
    assert (await client.get(url, headers=other.headers)).status_code == 404
    assert (await client.get(url, headers=adm2.headers)).status_code == 200
    assert (await client.get(f"{BASE}/files/not-an-id", headers=u.headers)).status_code == 404
    assert (await client.get(f"{BASE}/files/{'0' * 24}", headers=u.headers)).status_code == 404


async def test_rejected_user_cannot_open(client: Any, db: Any, trio: Any) -> None:
    u, adm, _ = trio
    r = await up(client, u, img_bytes(), to=adm)
    await db.users.update_one({"_id": u.id}, {"$set": {"status": "rejected"}})
    url = f"{BASE}/files/{r.json()['attachment']['id']}"
    assert (await client.get(url, headers=u.headers)).status_code == 403  # approval gate
    assert (await client.get(url, headers=adm.headers)).status_code == 404  # thread not openable


# ---------- limits ----------


@pytest.mark.usefixtures("limiter_on")
async def test_file_send_limits_and_text_unaffected(client: Any, trio: Any) -> None:
    u, adm, _ = trio
    tiny = img_bytes(size=(4, 4))
    for i in range(20):
        r = await up(client, u, tiny, "t.jpg", to=adm)
        assert r.status_code == 201, (i, r.text)
    assert (await up(client, u, tiny, "t.jpg", to=adm)).status_code == 429
    t = await client.post(
        f"{BASE}/messages", headers=u.headers, json={"toAdminId": str(adm.id), "text": "still ok"}
    )
    assert t.status_code == 201


@pytest.mark.usefixtures("limiter_on")
async def test_files_also_count_toward_message_limit(client: Any, trio: Any) -> None:
    u, adm, _ = trio
    for i in range(41):  # 41 text + 19 files = 60, the 20th file is the 61st message
        await client.post(
            f"{BASE}/messages", headers=u.headers, json={"toAdminId": str(adm.id), "text": f"{i}"}
        )
    tiny = img_bytes(size=(4, 4))
    codes = [(await up(client, u, tiny, "t.jpg", to=adm)).status_code for _ in range(20)]
    assert codes == [201] * 19 + [429]


async def test_storage_cap_blocks_files_not_text_and_clearing_frees(
    client: Any, db: Any, trio: Any, monkeypatch: Any
) -> None:
    u, adm, _ = trio
    first = await up(client, u, pdf_bytes(2000), "a.pdf", to=adm)
    assert first.status_code == 201
    monkeypatch.setattr(files, "max_total_bytes", lambda: 2500)
    full = await up(client, u, pdf_bytes(2000), "b.pdf", to=adm)
    assert full.status_code == 507 and full.json()["detail"] == files.STORAGE_FULL
    assert await stored_count(db) == (1, 1)
    t = await client.post(
        f"{BASE}/messages", headers=u.headers, json={"toAdminId": str(adm.id), "text": "text ok"}
    )
    assert t.status_code == 201
    c = await client.post(
        f"{BASE}/clear",
        headers=adm.headers,
        json={"userId": str(u.id), "olderThan": "all", "confirm": "DELETE"},
    )
    assert c.json() == {"deleted": 2, "files": 1, "bytes": 2000}
    assert (await up(client, u, pdf_bytes(2000), "c.pdf", to=adm)).status_code == 201


async def test_edit_keeps_attachment(client: Any, trio: Any) -> None:
    u, adm, _ = trio
    m = (await up(client, u, img_bytes(), to=adm, text="one")).json()
    e = await client.patch(f"{BASE}/messages/{m['id']}", headers=u.headers, json={"text": "two"})
    assert e.status_code == 200 and e.json()["text"] == "two"
    assert e.json()["attachment"] == m["attachment"]


# ---------- break-it ----------


@pytest.mark.usefixtures("limiter_on")
async def test_parallel_uploads_cannot_beat_the_hourly_limit(
    client: Any, db: Any, trio: Any
) -> None:
    import asyncio

    u, adm, _ = trio
    tiny = img_bytes(size=(4, 4))
    codes = await asyncio.gather(*[up(client, u, tiny, "t.jpg", to=adm) for _ in range(26)])
    ok = sum(1 for r in codes if r.status_code == 201)
    assert ok == 20 and sum(1 for r in codes if r.status_code == 429) == 6
    assert await stored_count(db) == (20, 20)


async def test_client_that_dies_mid_upload_stores_nothing(db: Any) -> None:
    class Dying:
        filename = "x.jpg"
        calls = 0

        async def read(self, _n: int) -> bytes:
            self.calls += 1
            if self.calls > 1:
                raise ConnectionError("client went away")
            return b"\xff\xd8\xff" + b"0" * 1000

    with pytest.raises(ConnectionError):
        await files.read_and_validate(Dying())
    assert await stored_count(db) == (0, 0)


async def test_storage_failure_keeps_no_attachment_record(
    client: Any, db: Any, trio: Any, monkeypatch: Any
) -> None:
    u, adm, _ = trio

    async def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("gridfs down")

    monkeypatch.setattr(files, "store_bytes", boom)
    with pytest.raises(RuntimeError):
        await up(client, u, img_bytes(), to=adm)
    assert await stored_count(db) == (0, 0)


def test_clean_name_forces_extension_from_detected_type() -> None:
    assert files.clean_name("invoice.pdf.hta", "pdf", "pdf") == "invoice.pdf.pdf"
    assert files.clean_name("run.bat", "pdf", "pdf") == "run.pdf"
    assert files.clean_name("photo", "image", "jpg") == "photo.jpg"
    assert files.clean_name("a.PDF", "pdf", "pdf") == "a.PDF"
