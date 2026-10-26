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
    # Save-Again and purge look rows up by documentId (userId is only a secondary filter).
    await db.exportedrows.create_index([("documentId", 1), ("userId", 1)])
    # Duplicate-warning lookup on Save: all of one user's exported rows for the batch's dates.
    await db.exportedrows.create_index([("userId", 1), ("date", 1)])
    await db.settings.create_index([("userId", 1), ("key", 1)], unique=True)
    await db.corrections.create_index([("documentId", 1)])
    await db.auditlogs.create_index([("userId", 1), ("createdAt", -1)])
    await db.chatmessages.create_index([("threadUserId", 1), ("updatedAt", 1)])
    await db.chatmessages.create_index([("threadUserId", 1), ("createdAt", 1)])
    await db.chatmessages.create_index([("toAdminId", 1), ("readAt", 1)])
    await db.auditlogs.create_index([("action", 1)])
    await _ensure_audit_ttl(db, settings.audit_log_retention_days)
    # unique on gridFsFileId - record_orphaned_file() upserts on this key so a
    # repeated failure on the same file (e.g. a failed retry) updates the
    # existing record instead of creating a duplicate.
    await db.orphanedfiles.create_index([("gridFsFileId", 1)], unique=True)
    await db.orphanedfiles.create_index([("createdAt", -1)])
    # One OPEN password-reset request per user (atomic upsert relies on this).
    await db.passwordresetrequests.create_index(
        [("userId", 1)], unique=True, partialFilterExpression={"status": "open"}
    )
    await db.passwordresetrequests.create_index([("status", 1), ("createdAt", -1)])
    # Email uniqueness was only a check-then-insert in the routers. The old
    # database carried a unique index from an earlier version, but a fresh
    # cluster has none, so two concurrent signups/profile updates could
    # create duplicate accounts. Enforce it in the database; if legacy
    # duplicates already exist the index can't build - warn, don't crash
    # startup (the router-level checks still apply).
    try:
        await db.users.create_index([("email", 1)], unique=True)
    except Exception as exc:  # noqa: BLE001
        from loguru import logger

        logger.warning(
            "Could not create unique users.email index (duplicates present?): "
            f"class={type(exc).__name__}"
        )


async def _ensure_audit_ttl(db: AsyncIOMotorDatabase, days: int) -> None:
    """Single-field createdAt TTL index on auditlogs (TTL only works on a single field and on real
    datetimes; audit_log.py writes datetime.now(UTC)). A changed retention is applied by dropping
    and recreating it; 0 = keep forever = no TTL index. Never crashes startup."""
    try:
        existing = None
        async for ix in db.auditlogs.list_indexes():
            if list(ix["key"]) == ["createdAt"]:
                existing = ix
        seconds = days * 86400
        current = existing.get("expireAfterSeconds") if existing else None
        if existing and (current == seconds if days else current is None):
            return
        if existing:
            await db.auditlogs.drop_index(existing["name"])
        if days:
            await db.auditlogs.create_index([("createdAt", 1)], expireAfterSeconds=seconds)
    except Exception as exc:  # noqa: BLE001
        from loguru import logger

        logger.warning(f"Could not set the audit-log retention index: class={type(exc).__name__}")


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
