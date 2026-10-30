"""Chat file attachments: validation, re-encoding, storage in the separate `chatfs` GridFS bucket,
serving, the 30-day expiry sweep and the delete cascades. Never logs file names or message text.

Files are checked by their BYTES (never the file name or browser type). Images are re-encoded
(metadata gone, shrunk to 1920 px); PDFs are stored as is and only ever served as bytes."""

import asyncio
import io
import re
import unicodedata
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote

from bson import ObjectId
from gridfs.errors import CorruptGridFile, NoFile
from loguru import logger
from PIL import Image, ImageOps

from app.core.config import settings
from app.core.database import get_chat_gridfs, get_database
from app.features.chat.errors import ChatError

MB = 1024 * 1024
IMAGE_MAX_BYTES = 2 * MB
PDF_MAX_BYTES = 3 * MB
MAX_PIXELS = 25_000_000
MAX_SIDE = 1920
QUALITY = 82
RETENTION = timedelta(days=30)
SWEEP_BATCH = 200
SWEEP_EVERY_SECONDS = 3600
FILE_SENDS_PER_HOUR = {"user": 20, "admin": 60}
READ_CHUNK = 64 * 1024

BAD_TYPE = "This file type is not allowed. Use JPG, PNG, WebP or PDF."
BAD_FILE = "This file could not be read."
IMAGE_TOO_BIG = "Images can be up to 2 MB."
PDF_TOO_BIG = "PDFs can be up to 3 MB."
STORAGE_FULL = "File storage is full. Please ask an admin."
EXPIRED = "This file has expired."

_KINDS = {
    "jpeg": ("image", "image/jpeg", "jpg"),
    "png": ("image", "image/png", "png"),
    "webp": ("image", "image/webp", "webp"),
    "pdf": ("pdf", "application/pdf", "pdf"),
}


@dataclass
class Checked:
    data: bytes  # what gets stored (re-encoded for images)
    kind: str  # "image" | "pdf"
    content_type: str
    ext: str
    name: str


_REENCODE_SLOTS = asyncio.Semaphore(2)


def max_total_bytes() -> int:
    return settings.chat_files_max_total_mb * MB


def detect_format(data: bytes) -> str | None:
    """From the bytes only. Returns jpeg | png | webp | pdf | None."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if b"%PDF-" in data[:1024] and b"%%EOF" in data[-1024:]:
        return "pdf"
    return None


def clean_name(raw: str | None, kind: str, ext: str | None = None) -> str:
    """Display name only: no path, no control or bidi characters, 100 characters at most. With
    `ext` (from the detected type) the extension is forced, so a script can never keep a .hta name.
    """
    name = PurePosixPath((raw or "").replace("\\", "/")).name
    name = "".join(c for c in name if unicodedata.category(c) not in ("Cc", "Cf", "Zl", "Zp"))
    name = re.sub(r"\s+", " ", name).strip()
    if not name.strip(". "):
        return "image" if kind == "image" else "document"
    if ext is not None:
        stem, dot, old = name.rpartition(".")
        if old.lower() != ext:
            name = f"{stem if dot and stem else name}.{ext}"
    if len(name) > 100:
        stem, dot, tail = name.rpartition(".")
        tail = tail[:10]
        if dot and stem:
            name = stem[: 100 - len(tail) - 1] + "." + tail
        else:
            name = name[:100]
    return name


def content_disposition(kind: str, name: str) -> str:
    """inline for images, attachment for PDFs; ASCII-only quoted name plus RFC 5987 filename*."""
    fallback = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip() or "file"
    mode = "inline" if kind == "image" else "attachment"
    return f"{mode}; filename=\"{fallback}\"; filename*=UTF-8''{quote(name, safe='')}"


def _reencode(data: bytes, fmt: str) -> bytes:
    """Open, verify, refuse bombs and animation, rotate by EXIF, shrink to 1920 px, save fresh
    with no metadata. Raises ChatError."""
    try:
        with Image.open(io.BytesIO(data)) as probe:
            actual = (probe.format or "").lower()
            if actual != fmt and not (fmt == "jpeg" and actual == "mpo"):
                raise ChatError(422, BAD_FILE)
            w, h = probe.size
            if w <= 0 or h <= 0 or w * h > MAX_PIXELS:
                raise ChatError(422, BAD_FILE)
            if actual != "mpo" and getattr(probe, "n_frames", 1) > 1:  # MPO = phone JPEG
                raise ChatError(422, BAD_FILE)
            probe.verify()
        with Image.open(io.BytesIO(data)) as opened:
            opened.load()
            img = ImageOps.exif_transpose(opened)
            img.thumbnail((MAX_SIDE, MAX_SIDE))  # only ever shrinks
            img.info = {}  # drops ICC profile, text chunks, EXIF carried in info
            out = io.BytesIO()
            if fmt == "jpeg":
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")
                img.save(out, "JPEG", quality=QUALITY)
            elif fmt == "webp":
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGBA" if "A" in img.mode else "RGB")
                img.save(out, "WEBP", quality=QUALITY)
            else:
                img.save(out, "PNG", optimize=True)
            return out.getvalue()
    except ChatError:
        raise
    except Exception:  # noqa: BLE001 - truncated, corrupt, bomb error: all "could not be read"
        raise ChatError(422, BAD_FILE) from None


async def read_upload(upload: Any, limit: int) -> bytes | None:
    """Chunked read that stops as soon as `limit` is crossed (None = too big)."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(READ_CHUNK):
        total += len(chunk)
        if total > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


async def read_and_validate(upload: Any) -> Checked:
    raw = await read_upload(upload, PDF_MAX_BYTES)
    if raw is None:
        raise ChatError(413, "This file is too large. Images can be up to 2 MB, PDFs up to 3 MB.")
    if not raw:
        raise ChatError(422, BAD_FILE)
    fmt = detect_format(raw)
    if fmt is None:
        raise ChatError(422, BAD_TYPE)
    kind, content_type, ext = _KINDS[fmt]
    if kind == "image" and len(raw) > IMAGE_MAX_BYTES:
        raise ChatError(413, IMAGE_TOO_BIG)
    data = raw
    if kind == "image":
        async with _REENCODE_SLOTS:  # a decode can take hundreds of MB: two at a time
            data = await asyncio.to_thread(_reencode, raw, fmt)
        if len(data) > IMAGE_MAX_BYTES:
            raise ChatError(413, IMAGE_TOO_BIG)
    return Checked(data, kind, content_type, ext, clean_name(upload.filename, kind, ext))


async def used_bytes(db: Any) -> int:
    agg = await db.chatattachments.aggregate(
        [{"$match": {"expired": False}}, {"$group": {"_id": None, "n": {"$sum": "$size"}}}]
    ).to_list(1)
    return int(agg[0]["n"]) if agg else 0


async def check_capacity(db: Any, adding: int) -> None:
    # ponytail: check-then-store, two simultaneous uploads can overshoot the cap by one file
    if await used_bytes(db) + adding > max_total_bytes():
        raise ChatError(507, STORAGE_FULL)


async def store_bytes(checked: Checked) -> ObjectId:
    bucket = get_chat_gridfs()
    stored = bucket.open_upload_stream(
        f"{uuid.uuid4().hex}.{checked.ext}", metadata={"contentType": checked.content_type}
    )
    try:
        await stored.write(checked.data)
        await stored.close()
    except BaseException:
        await stored.abort()
        raise
    return stored._id


async def insert_record(
    db: Any,
    checked: Checked,
    stored_id: ObjectId,
    message_id: ObjectId,
    thread_user_id: ObjectId,
    uploader_id: ObjectId,
    now: datetime | None = None,
) -> None:
    now = now or datetime.now(UTC)
    await db.chatattachments.insert_one(
        {
            "messageId": message_id,
            "threadUserId": thread_user_id,
            "uploaderId": uploader_id,
            "storedFileId": stored_id,
            "name": checked.name,
            "kind": checked.kind,
            "contentType": checked.content_type,
            "size": len(checked.data),
            "createdAt": now,
            "expiresAt": now + RETENTION,
            "expired": False,
        }
    )


async def delete_stored(db: Any, stored_id: ObjectId) -> bool:
    """Deletes the stored bytes. A failure is tracked in chatfileorphans (never the Orphaned
    files page, which only knows the document bucket) and retried by the sweep. Never raises."""
    try:
        await get_chat_gridfs().delete(stored_id)
    except NoFile:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"chat file delete failed: class={type(exc).__name__}")
        try:
            await db.chatfileorphans.update_one(
                {"storedFileId": stored_id},
                {"$setOnInsert": {"createdAt": datetime.now(UTC)}, "$inc": {"attempts": 1}},
                upsert=True,
            )
        except Exception:  # noqa: BLE001
            pass
        return False
    return True


async def count_files(db: Any, query: dict) -> dict:
    q = {**query, "expired": False}
    agg = await db.chatattachments.aggregate(
        [{"$match": q}, {"$group": {"_id": None, "n": {"$sum": 1}, "b": {"$sum": "$size"}}}]
    ).to_list(1)
    return {"files": agg[0]["n"] if agg else 0, "bytes": agg[0]["b"] if agg else 0}


async def delete_attachments(db: Any, query: dict) -> dict:
    """Removes matching attachment records and their stored files. Returns counts only."""
    recs = await db.chatattachments.find(query).to_list(None)
    files = bytes_ = 0
    for r in recs:
        if not r.get("expired"):
            files += 1
            bytes_ += r["size"]
        await delete_stored(db, r["storedFileId"])
    if recs:
        await db.chatattachments.delete_many({"_id": {"$in": [r["_id"] for r in recs]}})
    return {"files": files, "bytes": bytes_}


async def retry_orphans(db: Any) -> None:
    async for o in db.chatfileorphans.find({}).limit(SWEEP_BATCH):
        if await delete_stored(db, o["storedFileId"]):
            await db.chatfileorphans.delete_one({"_id": o["_id"]})


async def sweep_expired(db: Any, now: datetime | None = None) -> int:
    """One pass: at most 200 attachments past expiresAt, oldest first. Each: delete the stored
    file, mark it expired, bump the message's updatedAt so open chats see it on the next poll.
    Idempotent; never raises."""
    now = now or datetime.now(UTC)
    done = 0
    try:
        await retry_orphans(db)
        due = (
            await db.chatattachments.find({"expired": False, "expiresAt": {"$lte": now}})
            .sort("expiresAt", 1)
            .limit(SWEEP_BATCH)
            .to_list(SWEEP_BATCH)
        )
        for r in due:
            if not await delete_stored(db, r["storedFileId"]):
                continue  # still tracked for retry; try again next pass
            res = await db.chatattachments.update_one(
                {"_id": r["_id"], "expired": False}, {"$set": {"expired": True}}
            )
            if res.modified_count:
                await db.chatmessages.update_one(
                    {"_id": r["messageId"]}, {"$set": {"updatedAt": now}}
                )
                done += 1
    except Exception as exc:  # noqa: BLE001
        logger.error(f"chat file sweep failed: class={type(exc).__name__}")
    return done


async def run_expiry_forever(
    sleep: Callable[[float], Any] = asyncio.sleep, interval: float = SWEEP_EVERY_SECONDS
) -> None:
    """Started at app startup like the other background tasks: once now, then hourly."""
    while True:
        try:
            await sweep_expired(get_database())
        except Exception as exc:  # noqa: BLE001 - get_database() before connect, anything
            logger.error(f"chat file sweep loop error: class={type(exc).__name__}")
        await sleep(interval)


async def open_file(
    db: Any, attachment_id: ObjectId, viewer_id: ObjectId, viewer_role: str
) -> tuple[dict, bytes]:
    """(record, bytes). Raises ChatError 404 for stranger/unknown, 410 for expired."""
    rec = await db.chatattachments.find_one({"_id": attachment_id})
    allowed = rec is not None and (viewer_role == "admin" or rec["threadUserId"] == viewer_id)
    if rec is None or not allowed:
        raise ChatError(404, "File not found.")
    if viewer_role == "admin":
        thread_user = await db.users.find_one(
            {"_id": rec["threadUserId"], "role": {"$ne": "admin"}}, {"status": 1}
        )
        if thread_user is None or thread_user.get("status", "approved") != "approved":
            raise ChatError(404, "File not found.")
    expires = rec["expiresAt"] if rec["expiresAt"].tzinfo else rec["expiresAt"].replace(tzinfo=UTC)
    if rec.get("expired") or expires <= datetime.now(UTC):
        raise ChatError(410, EXPIRED)
    try:
        stream = await get_chat_gridfs().open_download_stream(rec["storedFileId"])
        return rec, await stream.read()
    except (NoFile, CorruptGridFile):
        raise ChatError(410, EXPIRED) from None
