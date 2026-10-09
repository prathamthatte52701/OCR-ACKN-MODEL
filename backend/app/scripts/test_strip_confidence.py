from typing import Any

import pytest
from bson import ObjectId

from app.scripts import strip_confidence as sc

OLD = {
    "taxInvoiceNoConfidence": 5,
    "referenceNoConfidence": 5,
    "numberConfidence": 100,
    "dateConfidence": 40,
}
KEEP = {
    "number": "820000001",
    "date": "05/10/2026",
    "edited": True,
    "exported": True,
    "numberAutoCorrected": True,
}


async def test_dry_run_apply_idempotent_and_other_fields_untouched(db: Any) -> None:
    await db.documents.insert_many([{**OLD, **KEEP}, {**OLD, **KEEP}, {**KEEP}])
    await db.exportedrows.insert_one({"userId": ObjectId(), "number": "1", "dateConfidence": 7})
    assert await sc.strip_confidence(db) == {"documents": 2, "exportedrows": 1}
    assert await sc.strip_confidence(db) == {
        "documents": 2,
        "exportedrows": 1,
    }  # dry-run changes nothing
    assert await db.documents.count_documents({"numberConfidence": {"$exists": True}}) == 2
    assert await sc.strip_confidence(db, apply=True) == {"documents": 2, "exportedrows": 1}
    assert await sc.strip_confidence(db, apply=True) == {"documents": 0, "exportedrows": 0}
    assert await sc.strip_confidence(db) == {"documents": 0, "exportedrows": 0}
    async for doc in db.documents.find({}):
        assert not [k for k in doc if k.endswith("Confidence")]
        assert {k: doc[k] for k in KEEP} == KEEP


async def test_refuses_when_db_flag_does_not_match(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["x", "--db", "some_other_db", "--apply"])
    with pytest.raises(SystemExit) as exc:
        await sc.main()
    assert "Refusing" in str(exc.value)
