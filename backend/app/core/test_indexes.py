"""Index creation on the _test DB: exportedrows (documentId, userId) and the audit-log TTL.
The TTL monitor is never waited for - only the index definition is checked."""

from typing import Any

import pytest
from pymongo.errors import OperationFailure

from app.core import database as database_module
from app.core.database import _ensure_audit_ttl, _ensure_indexes

DAY = 86400


async def _single_created_at(db: Any) -> dict | None:
    async for ix in db.auditlogs.list_indexes():
        if list(ix["key"]) == ["createdAt"]:
            return ix
    return None


async def _clear_created_at(db: Any) -> None:
    ix = await _single_created_at(db)
    if ix:
        await db.auditlogs.drop_index(ix["name"])


async def test_exportedrows_document_user_index_exists(db: Any) -> None:
    await _ensure_indexes(db)
    await _ensure_indexes(db)  # idempotent
    keys = [list(ix["key"].items()) async for ix in db.exportedrows.list_indexes()]
    assert [("documentId", 1), ("userId", 1)] in keys
    assert [("userId", 1), ("date", 1)] in keys
    assert [("userId", 1), ("exportedAt", -1)] in keys  # existing one kept


async def test_default_creates_ttl_on_single_field_created_at(db: Any) -> None:
    await _clear_created_at(db)
    await _ensure_indexes(db)
    ix = await _single_created_at(db)
    assert ix is not None and ix["expireAfterSeconds"] == 365 * DAY
    # the existing compound indexes are untouched
    names = [list(i["key"]) async for i in db.auditlogs.list_indexes()]
    assert ["userId", "createdAt"] in names and ["action"] in names


async def test_changed_setting_updates_ttl(db: Any) -> None:
    await _ensure_audit_ttl(db, 365)
    await _ensure_audit_ttl(db, 30)
    ix = await _single_created_at(db)
    assert ix is not None and ix["expireAfterSeconds"] == 30 * DAY
    await _ensure_audit_ttl(db, 30)  # same value: no-op
    ix = await _single_created_at(db)
    assert ix is not None and ix["expireAfterSeconds"] == 30 * DAY


async def test_zero_removes_ttl_and_keeps_none(db: Any) -> None:
    await _ensure_audit_ttl(db, 365)
    await _ensure_audit_ttl(db, 0)
    assert await _single_created_at(db) is None
    await _ensure_audit_ttl(db, 0)  # nothing to drop: fine


async def test_plain_created_at_index_is_replaced_by_ttl(db: Any) -> None:
    await _clear_created_at(db)
    await db.auditlogs.create_index([("createdAt", 1)])
    await _ensure_audit_ttl(db, 10)
    ix = await _single_created_at(db)
    assert ix is not None and ix["expireAfterSeconds"] == 10 * DAY


async def test_index_conflict_does_not_crash(db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(*_a: Any, **_k: Any) -> None:
        raise OperationFailure("IndexOptionsConflict")

    await _ensure_audit_ttl(db, 365)
    monkeypatch.setattr(type(db.auditlogs), "create_index", boom)
    monkeypatch.setattr(type(db.auditlogs), "drop_index", boom)
    await _ensure_audit_ttl(db, 7)  # must swallow and log
    await _ensure_audit_ttl(db, 0)


def test_module_exposes_settings_retention() -> None:
    assert hasattr(database_module.settings, "audit_log_retention_days")
