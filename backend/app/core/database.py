from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorGridFSBucket

from app.core.config import settings

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None
_gridfs: AsyncIOMotorGridFSBucket | None = None


async def connect_to_mongo() -> None:
    global _client, _db, _gridfs
    # tz_aware=True: without it, PyMongo/Motor decodes BSON dates as naive
    # datetimes (no tzinfo) even though they're stored as UTC - FastAPI then
    # serializes them with no offset suffix (e.g. "2026-07-24T03:47:22" instead
    # of "...+00:00"), and `new Date(...)` in the browser silently treats that
    # ambiguous string as LOCAL time instead of UTC, corrupting every IST
    # timestamp display in the frontend. This makes every datetime read back
    # as a proper UTC-aware datetime, so serialization includes the offset.
    _client = AsyncIOMotorClient(settings.mongo_uri, serverSelectionTimeoutMS=10000, tz_aware=True)
    _db = _client[settings.mongo_db_name]
    _gridfs = AsyncIOMotorGridFSBucket(_db)
    await _client.admin.command("ping")
    await _ensure_indexes(_db)


async def _ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    """No index existed on any collection except users.email (a leftover
    unique constraint) - confirmed by listing indexes directly. Every list/
    search query filters by userId and sorts by createdAt, so without this
    every GET was a full collection scan - the other confirmed contributor
    to "all GET APIs are slow" alongside the CPU-thread-cap fix in
    paddle_runner.py. create_index is idempotent (no-op if already present),
    safe to call on every startup."""
    await db.documents.create_index([("userId", 1), ("isDeleted", 1), ("createdAt", -1)])
    await db.documents.create_index([("userId", 1), ("documentType", 1)])
    await db.workbooks.create_index([("userId", 1), ("year", -1)])
    await db.exportedrows.create_index([("userId", 1), ("exportedAt", -1)])
    await db.settings.create_index([("userId", 1), ("key", 1)], unique=True)
    await db.corrections.create_index([("documentId", 1)])
    await db.auditlogs.create_index([("userId", 1), ("createdAt", -1)])
    await db.auditlogs.create_index([("action", 1)])
    # unique on gridFsFileId - record_orphaned_file() upserts on this key so a
    # repeated failure on the same file (e.g. a failed retry) updates the
    # existing record instead of creating a duplicate.
    await db.orphanedfiles.create_index([("gridFsFileId", 1)], unique=True)
    await db.orphanedfiles.create_index([("createdAt", -1)])


async def close_mongo_connection() -> None:
    global _client
    if _client is not None:
        _client.close()


def get_database() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("Database not initialized - connect_to_mongo() must run first.")
    return _db


def get_gridfs() -> AsyncIOMotorGridFSBucket:
    if _gridfs is None:
        raise RuntimeError("GridFS not initialized - connect_to_mongo() must run first.")
    return _gridfs
