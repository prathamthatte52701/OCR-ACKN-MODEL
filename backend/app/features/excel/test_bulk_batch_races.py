"""Batch save: race B (edit between PREPARE and the final write), a locked workbook,
deadlock-freedom of overlapping bulk saves, and the small invariants (cap, duplicates, audit)."""

import asyncio
import shutil
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from bson import ObjectId

from app.features.excel import old_excel_oracle as oracle
from app.features.excel import router as excel_router
from app.features.excel import service as excel_service
from app.features.excel.batch_test_support import (
    BASE,
    CLOCK,
    capture,
    data_rows,
    make_doc,
    physical,
    post_bulk,
    restore,
    seed_book,
    seed_old_record,
    seed_settings,
    snapshot,
    write_files,
    xlsx_path,
)

WB26 = "Book2026"
WB25 = "Book2025"
STALE_TEXT = "was edited while it was being saved"


@pytest.fixture(autouse=True)
def _clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(excel_service, "now_ist", lambda: CLOCK)


@pytest.fixture
def exports_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "exports"
    d.mkdir()
    monkeypatch.setattr(excel_service, "EXPORT_DIR", d)
    return d


async def _one_book(db: Any, user: Any, d: Path) -> ObjectId:
    wb = await seed_book(db, user.id, WB26, 2026, True)
    await seed_settings(db, user.id, WB26, 2026)
    write_files(d, {physical(user.id, WB26): {"March": []}})
    return wb


# ------------------------------------------------------------------------------ RACE B

Editor = Callable[[Any, Any, ObjectId, Any], Awaitable[None]]


async def _direct_edit(db: Any, client: Any, doc_id: ObjectId, user: Any) -> None:
    await db.documents.update_one(
        {"_id": doc_id},
        {"$set": {"number": "EDITED", "exported": False, "updatedAt": datetime.now(UTC)}},
    )


async def _user_route_edit(db: Any, client: Any, doc_id: ObjectId, user: Any) -> None:
    r = await client.patch(
        f"{BASE}/{doc_id}/correct", headers=user.headers, json={"field": "number", "value": "EDIT2"}
    )
    assert r.status_code == 200, r.text


async def _admin_route_edit(db: Any, client: Any, doc_id: ObjectId, user: Any) -> None:
    admin = user.admin
    r = await client.patch(
        f"/api/admin/documents/{doc_id}",
        headers=admin.headers,
        json={"field": "number", "value": "EDIT3"},
    )
    assert r.status_code == 200, r.text


def _edit_during_append(
    monkeypatch: pytest.MonkeyPatch, edit: Editor, db: Any, client: Any, target: ObjectId, user: Any
) -> None:
    """Between PREPARE (document read, updatedAt captured) and the final write the document is
    edited: the edit lands right before the batched append, exactly where a real concurrent
    request can slip in."""
    real = excel_service.append_rows

    async def wrapper(filename: str, items: list) -> Path:
        await edit(db, client, target, user)
        return await real(filename, items)

    monkeypatch.setattr(excel_service, "append_rows", wrapper)


@pytest.mark.parametrize("edit", [_direct_edit, _user_route_edit, _admin_route_edit])
async def test_single_save_edited_during_save_stays_unexported_with_warning(
    client: Any,
    db: Any,
    make_user: Any,
    exports_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    edit: Editor,
) -> None:
    user = await make_user()
    user.admin = await make_user(role="admin")
    await _one_book(db, user, exports_dir)
    doc = await make_doc(db, user.id, "ORIG1", "01/01/2026")
    _edit_during_append(monkeypatch, edit, db, client, doc, user)

    r = await client.post(f"{BASE}/{doc}/save", headers=user.headers)
    assert r.status_code == 200, r.text
    warning = r.json()["staleRowWarning"]
    assert STALE_TEXT in warning and "Save Again" in warning
    stored = await db.documents.find_one({"_id": doc})
    assert stored["exported"] is False and stored["number"] != "ORIG1"
    rows = data_rows(exports_dir, user.id, WB26)
    assert [r_[1][1] for r_ in rows] == ["ORIG1"]  # the Excel row has the OLD values
    assert await db.exportedrows.count_documents({"documentId": doc}) == 1
    assert not list(exports_dir.glob("*.tmp*"))

    # and Save Again (no more interference) repairs it: new values in, old row out, exported True
    monkeypatch.undo()
    monkeypatch.setattr(excel_service, "EXPORT_DIR", exports_dir)
    monkeypatch.setattr(excel_service, "now_ist", lambda: CLOCK)
    again = await client.post(f"{BASE}/{doc}/save", headers=user.headers)
    assert again.status_code == 200 and again.json()["replaced"] == 1
    assert "staleRowWarning" not in again.json()
    assert (await db.documents.find_one({"_id": doc}))["exported"] is True
    rows = data_rows(exports_dir, user.id, WB26)
    assert len(rows) == 1 and rows[0][1][1] == stored["number"]


@pytest.mark.parametrize("edit", [_direct_edit, _user_route_edit, _admin_route_edit])
async def test_bulk_save_edited_during_save_reports_stale_warning_for_that_document(
    client: Any,
    db: Any,
    make_user: Any,
    exports_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    edit: Editor,
) -> None:
    user = await make_user()
    user.admin = await make_user(role="admin")
    await _one_book(db, user, exports_dir)
    docs = [await make_doc(db, user.id, f"B{i}", "01/01/2026") for i in range(3)]
    _edit_during_append(monkeypatch, edit, db, client, docs[1], user)

    r = await post_bulk(client, user, docs)
    body = r.json()
    assert r.status_code == 200 and body["succeeded"] == [str(d) for d in docs]
    assert [w["documentId"] for w in body["staleWarnings"]] == [str(docs[1])]
    msg = body["staleWarnings"][0]["message"]
    assert STALE_TEXT in msg and "Save Again" in msg
    flags = {d: (await db.documents.find_one({"_id": d}))["exported"] for d in docs}
    assert flags == {docs[0]: True, docs[1]: False, docs[2]: True}
    rows = [row[1][1] for row in data_rows(exports_dir, user.id, WB26)]
    assert rows == ["B0", "B1", "B2"]  # the edited document's row has the OLD value
    assert not list(exports_dir.glob("*.tmp*"))


async def test_no_edit_means_exported_true_and_no_warning(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    user = await make_user()
    await _one_book(db, user, exports_dir)
    single = await make_doc(db, user.id, "N0", "01/01/2026")
    r = await client.post(f"{BASE}/{single}/save", headers=user.headers)
    assert r.status_code == 200 and "staleRowWarning" not in r.json()
    assert (await db.documents.find_one({"_id": single}))["exported"] is True
    docs = [await make_doc(db, user.id, f"N{i}", "01/01/2026") for i in range(1, 4)]
    body = (await post_bulk(client, user, docs)).json()
    assert body["staleWarnings"] == [] and len(body["succeeded"]) == 3
    assert await db.documents.count_documents({"userId": user.id, "exported": True}) == 4


# ------------------------------------------------------------------------------ LOCKED FILE


async def _two_books(db: Any, user: Any, d: Path) -> dict[str, Any]:
    """Book2026 (active) and Book2025, pre-existing rows, and documents on both. `old26` and
    `old25` are Save Again documents that already have a row in the 2026 / 2025 book."""
    wb26 = await seed_book(db, user.id, WB26, 2026, True)
    wb25 = await seed_book(db, user.id, WB25, 2025, False)
    await seed_settings(db, user.id, WB26, 2026)
    d26 = await make_doc(db, user.id, "OLD26", "05/03/2026")
    d25 = await make_doc(db, user.id, "OLD25", "05/06/2025")
    await seed_old_record(db, user.id, d26, wb26, WB26, "March", "OLD26", "05/03/2026")
    await seed_old_record(db, user.id, d25, wb25, WB25, "June", "OLD25", "05/06/2025")
    write_files(
        d,
        {
            physical(user.id, WB26): {"March": [["Delivery Challan", "OLD26", "05/03/2026", "t0"]]},
            physical(user.id, WB25): {"June": [["Delivery Challan", "OLD25", "05/06/2025", "t0"]]},
        },
    )
    docs = {
        "a1": await make_doc(db, user.id, "A1", "02/03/2026"),
        "b1": await make_doc(db, user.id, "B1", "02/06/2025"),
        "a2": await make_doc(db, user.id, "A2", "03/03/2026"),
        "b2": await make_doc(db, user.id, "B2", "03/07/2025"),
        "old26": d26,
        "old25": d25,
    }
    return docs


async def test_locked_workbook_fails_only_its_documents_and_matches_old_path(
    client: Any,
    db: Any,
    make_user: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await make_user()
    uids = [user.id]
    init, dir_a, dir_b = tmp_path / "init", tmp_path / "a", tmp_path / "b"
    monkeypatch.setattr(excel_service, "EXPORT_DIR", init)
    docs = await _two_books(db, user, init)
    snap = await snapshot(db, uids)
    shutil.copytree(init, dir_a)
    shutil.copytree(init, dir_b)
    request = [docs[k] for k in ("a1", "b1", "old25", "a2", "b2", "old26")]
    locked_name = xlsx_path(init, user.id, WB25).name

    monkeypatch.setattr(excel_service, "EXPORT_DIR", dir_a)
    with open(dir_a / locked_name, "rb"):
        _, old = await oracle.bulk_save(request, user.id)
    old_state = await capture(db, uids, dir_a)
    await restore(db, uids, snap)

    monkeypatch.setattr(excel_service, "EXPORT_DIR", dir_b)
    before = (dir_b / locked_name).read_bytes()
    with open(dir_b / locked_name, "rb"):
        r = await post_bulk(client, user, request)
    new = r.json()
    new_state = await capture(db, uids, dir_b)
    assert (dir_b / locked_name).read_bytes() == before  # locked file content unchanged

    busy = excel_router.FILE_BUSY_MESSAGE
    assert r.status_code == 200
    assert new["succeeded"] == [str(docs[k]) for k in ("a1", "a2", "old26")]
    assert sorted(new["failed"], key=lambda f: f["documentId"]) == sorted(
        ({"documentId": str(docs[k]), "reason": busy} for k in ("b1", "old25", "b2")),
        key=lambda f: f["documentId"],
    )
    assert new["message"] == "3/6 saved successfully." and new["replaced"] == 1
    # old path: same reasons, same everything (failed order compared sorted: it is per file now)
    assert sorted(old["failed"], key=lambda f: f["documentId"]) == sorted(
        new["failed"], key=lambda f: f["documentId"]
    )
    old["failed"] = new["failed"] = []
    assert new == old
    assert new_state == old_state
    # the locked file's Save Again document keeps its OLD record, gets no new one, stays unexported
    recs = await db.exportedrows.find({"documentId": docs["old25"]}).to_list(None)
    assert len(recs) == 1 and recs[0]["number"] == "OLD25"
    assert (await db.documents.find_one({"_id": docs["old25"]}))["exported"] is False
    assert (await db.documents.find_one({"_id": docs["b1"]}))["exported"] is False
    assert await db.exportedrows.count_documents({"documentId": docs["b1"]}) == 0
    # the other workbook was written normally (old row replaced by the new one)
    assert [row[1][1] for row in data_rows(dir_b, user.id, WB26)] == ["A1", "A2", "OLD26"]
    assert not list(dir_b.glob("*.tmp*"))


async def test_single_save_into_locked_workbook_is_409_file_busy(
    client: Any,
    db: Any,
    make_user: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await make_user()
    init = tmp_path / "init"
    monkeypatch.setattr(excel_service, "EXPORT_DIR", init)
    docs = await _two_books(db, user, init)
    path = xlsx_path(init, user.id, WB25)
    before = path.read_bytes()
    with open(path, "rb"):
        r = await client.post(f"{BASE}/{docs['b1']}/save", headers=user.headers)
        again = await client.post(f"{BASE}/{docs['old25']}/save", headers=user.headers)
        old = await oracle.single_save(docs["b1"], user.id)
    assert r.status_code == 409 and r.json() == {"detail": excel_router.FILE_BUSY_MESSAGE}
    assert again.status_code == 409
    assert old == (409, {"detail": excel_router.FILE_BUSY_MESSAGE})
    assert path.read_bytes() == before and not list(init.glob("*.tmp*"))
    assert await db.exportedrows.count_documents({"documentId": docs["old25"]}) == 1
    ok = await client.post(f"{BASE}/{docs['a1']}/save", headers=user.headers)
    assert ok.status_code == 200


async def test_old_row_removal_blocked_by_lock_keeps_old_record_and_warns(
    client: Any,
    db: Any,
    make_user: Any,
    exports_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The file is writable for the append but the removal pass finds it locked: the new row stays,
    the old record is kept for the next Save Again, and the user gets the 'open in Excel' text."""
    user = await make_user()
    docs = await _two_books(db, user, exports_dir)
    real_remove = excel_service.remove_rows

    async def locked_remove(*a: Any, **kw: Any) -> Any:
        raise excel_service.FileLockedError("open")

    monkeypatch.setattr(excel_service, "remove_rows", locked_remove)
    if hasattr(excel_service, "remove_rows_detailed"):
        monkeypatch.setattr(excel_service, "remove_rows_detailed", locked_remove)
    r = await post_bulk(client, user, [docs["old26"]])
    body = r.json()
    assert body["succeeded"] == [str(docs["old26"])] and body["replaced"] == 0
    assert "open in Excel. Close it and press Save Again to finish." in (
        body["staleWarnings"][0]["message"]
    )
    assert await db.exportedrows.count_documents({"documentId": docs["old26"]}) == 2
    monkeypatch.setattr(excel_service, "remove_rows", real_remove)


# ------------------------------------------------------------------------------ DEADLOCK


@pytest.mark.parametrize("partial", [False, True])
async def test_overlapping_bulk_saves_in_opposite_order_do_not_deadlock(
    client: Any, db: Any, make_user: Any, exports_dir: Path, partial: bool
) -> None:
    user = await make_user()
    await _one_book(db, user, exports_dir)
    docs = [await make_doc(db, user.id, f"D{i}", "01/01/2026") for i in range(6)]
    first = docs[:4] if partial else docs
    second = (docs[3:] if partial else docs)[::-1]
    r1, r2 = await asyncio.wait_for(
        asyncio.gather(post_bulk(client, user, first), post_bulk(client, user, second)),
        timeout=120,
    )
    assert r1.status_code == 200 and r2.status_code == 200
    assert not r1.json()["failed"] and not r2.json()["failed"]
    touched = set(first) | set(second)
    for d in touched:
        assert await db.exportedrows.count_documents({"documentId": d}) == 1
        assert (await db.documents.find_one({"_id": d}))["exported"] is True
    rows = [row[1][1] for row in data_rows(exports_dir, user.id, WB26)]
    assert sorted(rows) == sorted(f"D{docs.index(d)}" for d in touched)  # one row per document
    assert not list(exports_dir.glob("*.tmp*"))


async def test_concurrent_single_and_bulk_save_of_same_document_leave_one_row(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    user = await make_user()
    await _one_book(db, user, exports_dir)
    d = await make_doc(db, user.id, "ONE", "01/01/2026")
    results = await asyncio.wait_for(
        asyncio.gather(
            client.post(f"{BASE}/{d}/save", headers=user.headers),
            post_bulk(client, user, [d]),
            client.post(f"{BASE}/{d}/save", headers=user.headers),
        ),
        timeout=120,
    )
    assert all(r.status_code == 200 for r in results)
    assert await db.exportedrows.count_documents({"documentId": d}) == 1
    assert len(data_rows(exports_dir, user.id, WB26)) == 1


# ------------------------------------------------------------------------------ OTHER


async def test_bulk_cap_boundary_and_message_match_old_path(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    user = await make_user()
    await _one_book(db, user, exports_dir)
    ok = await post_bulk(client, user, [ObjectId() for _ in range(100)])
    assert ok.status_code == 200 and len(ok.json()["failed"]) == 100
    too_many = await post_bulk(client, user, [ObjectId() for _ in range(101)])
    old_status, old_body = await oracle.bulk_save([ObjectId() for _ in range(101)], user.id)
    assert too_many.status_code == 400 == old_status
    assert too_many.json() == old_body == {"detail": "You can save at most 100 documents at once."}
    assert (await post_bulk(client, user, [ObjectId() for _ in range(201)])).status_code in (
        400,
        422,
    )


async def test_duplicate_ids_write_one_row_and_one_audit_entry(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    user = await make_user()
    await _one_book(db, user, exports_dir)
    a = await make_doc(db, user.id, "DA", "01/01/2026")
    b = await make_doc(db, user.id, "DB", "01/01/2026")
    body = (await post_bulk(client, user, [a, b, a, b, a])).json()
    assert body["succeeded"] == [str(a), str(b)] and body["message"] == "2/2 saved successfully."
    assert len(data_rows(exports_dir, user.id, WB26)) == 2
    assert await db.auditlogs.count_documents({"action": "document_exported"}) == 2


async def test_audit_log_has_one_entry_per_saved_document_with_same_context(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    user = await make_user()
    await _one_book(db, user, exports_dir)
    wb = await db.workbooks.find_one({"userId": user.id})
    again = await make_doc(db, user.id, "AGAIN", "02/03/2026")
    await seed_old_record(db, user.id, again, wb["_id"], WB26, "March", "AGAIN", "02/03/2026")
    write_files(
        exports_dir,
        {physical(user.id, WB26): {"March": [["Delivery Challan", "AGAIN", "02/03/2026", "t0"]]}},
    )
    fresh = await make_doc(db, user.id, "FRESH", "03/03/2026")
    bad = await make_doc(db, user.id, "BAD", "03/03/2026", status="failed")
    body = (await post_bulk(client, user, [again, bad, fresh])).json()
    assert body["succeeded"] == [str(again), str(fresh)]
    logs = await db.auditlogs.find({"action": "document_exported"}).to_list(None)
    assert len(logs) == 2
    by_doc = {entry["context"]["documentId"]: entry for entry in logs}
    assert set(by_doc) == {str(again), str(fresh)}
    for entry in logs:
        assert entry["userId"] == user.id
        assert set(entry["context"]) == {"documentId", "worksheet", "workbook", "replaced"}
        assert entry["context"]["worksheet"] == "March" and entry["context"]["workbook"] == WB26
    assert by_doc[str(again)]["context"]["replaced"] == 1
    assert by_doc[str(fresh)]["context"]["replaced"] == 0


async def test_no_temp_files_after_a_mixed_bulk_save(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    user = await make_user()
    docs = await _two_books(db, user, exports_dir)
    r = await post_bulk(client, user, list(docs.values()))
    assert r.status_code == 200 and len(r.json()["succeeded"]) == len(docs)
    assert not list(exports_dir.glob("*.tmp*"))
    assert len(list(exports_dir.glob("*.xlsx"))) == 2
