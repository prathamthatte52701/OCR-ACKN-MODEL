"""cleanup_orphan_corrections: dry-run by default, --apply deletes only orphans.
SAFETY: only the "_test" database from the db fixture is used."""

from datetime import UTC, datetime
from typing import Any

import pytest

from app.core.config import settings
from app.scripts import cleanup_orphan_corrections as script


async def _seed(db: Any) -> None:
    assert db.name.endswith("_test")
    now = datetime.now(UTC)
    kept = (await db.documents.insert_one({"createdAt": now})).inserted_id
    gone = (await db.documents.insert_one({"createdAt": now})).inserted_id
    await db.documents.delete_one({"_id": gone})
    await db.corrections.insert_many(
        [{"documentId": kept}, {"documentId": gone}, {"documentId": gone}]
    )


async def test_dry_run_changes_nothing(db: Any, capsys: pytest.CaptureFixture[str]) -> None:
    await _seed(db)
    assert await script.run(["--db", settings.mongo_db_name]) == 0
    assert await db.corrections.count_documents({}) == 3
    assert "orphaned (document gone): 2" in capsys.readouterr().out


async def test_apply_deletes_only_orphans(db: Any) -> None:
    await _seed(db)
    assert await script.run(["--db", settings.mongo_db_name, "--apply"]) == 0
    assert await db.corrections.count_documents({}) == 1
    assert await script.run(["--db", settings.mongo_db_name, "--apply"]) == 0  # idempotent


async def test_refuses_wrong_db(db: Any) -> None:
    await _seed(db)
    assert await script.run(["--db", "some_other_db", "--apply"]) == 2
    assert await db.corrections.count_documents({}) == 3
