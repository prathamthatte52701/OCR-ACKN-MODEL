"""find_duplicate_workbooks: report-only. SAFETY: only the "_test" db from the db fixture."""

from typing import Any

import pytest

from app.core.config import settings
from app.scripts import find_duplicate_workbooks as script


async def _add(db: Any, uid: str, names: list[str]) -> None:
    assert db.name.endswith("_test")
    await db.workbooks.insert_many(
        [{"userId": uid, "filename": n, "year": 2026, "isActive": True} for n in names]
    )


async def test_no_duplicates(db: Any, capsys: pytest.CaptureFixture[str]) -> None:
    await _add(db, "u1", ["A", "B"])
    assert await script.run(["--db", settings.mongo_db_name]) == 0
    assert "users with duplicates: 0, duplicate groups: 0" in capsys.readouterr().out


async def test_group_of_three(db: Any, capsys: pytest.CaptureFixture[str]) -> None:
    await _add(db, "u1", ["Bills", "Bills.xlsx", "bills", "Other"])
    assert await script.run(["--db", settings.mongo_db_name]) == 0
    out = capsys.readouterr().out
    assert "records: 3" in out
    assert "same physical path (case-insensitive): True" in out
    assert "users with duplicates: 1, duplicate groups: 1" in out


async def test_same_name_different_users(db: Any, capsys: pytest.CaptureFixture[str]) -> None:
    await _add(db, "u1", ["Bills"])
    await _add(db, "u2", ["Bills"])
    assert await script.run(["--db", settings.mongo_db_name]) == 0
    assert "duplicate groups: 0" in capsys.readouterr().out


async def test_refuses_wrong_db(db: Any) -> None:
    assert await script.run(["--db", "some_other_db"]) == 2


async def test_db_unchanged(db: Any) -> None:
    await _add(db, "u1", ["Bills", "bills"])
    before = await db.workbooks.find({}).sort("_id").to_list(None)
    assert await script.run(["--db", settings.mongo_db_name]) == 0
    assert await db.workbooks.find({}).sort("_id").to_list(None) == before
