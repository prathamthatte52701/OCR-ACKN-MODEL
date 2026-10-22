"""DIFFERENTIAL PARITY: the batched save must be indistinguishable from the old per-document save.

Each scenario is built once (DB + exports dir), snapshotted, run through the ORACLE
(old_excel_oracle: verbatim old code, sequential) on copy A, restored, then run through the real
HTTP API on copy B. Responses, workbook cells (sheet by sheet, in order), exportedrows, documents,
settings, workbooks and audit entries must be equal."""

import random
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from bson import ObjectId

from app.features.excel import old_excel_oracle as oracle
from app.features.excel import service as excel_service
from app.features.excel.batch_test_support import (
    BASE,
    CLOCK,
    Files,
    capture,
    make_doc,
    number_cell,
    physical,
    read_dir,
    restore,
    snapshot,
    write_files,
    xlsx_path,
)

WB26 = "Book2026"
WB25 = "Book2025"


@pytest.fixture(autouse=True)
def _clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(excel_service, "now_ist", lambda: CLOCK)


class Builder:
    def __init__(self, rng: random.Random, db: Any, user: Any, other: Any, d: Path) -> None:
        self.rng, self.db, self.user, self.other, self.d = rng, db, user, other, d
        self.files: Files = {}
        self.wb_ids: dict[str, ObjectId | None] = {}
        self.clock = datetime(2026, 1, 1, tzinfo=UTC)

    def tick(self) -> datetime:
        self.clock += timedelta(minutes=1)
        return self.clock

    def add_row(self, wb: str, sheet: str, row: list[Any]) -> None:
        self.files.setdefault(physical(self.user.id, wb), {}).setdefault(sheet, []).append(row)

    def ensure_sheet(self, wb: str, sheet: str) -> None:
        self.files.setdefault(physical(self.user.id, wb), {}).setdefault(sheet, [])

    async def workbook(self, name: str, year: int, active: bool, file_on_disk: bool = True) -> None:
        now = datetime.now(UTC)
        res = await self.db.workbooks.insert_one(
            {
                "userId": self.user.id,
                "year": year,
                "filename": name,
                "isActive": active,
                "archivedAt": None if active else now,
                "createdAt": now,
                "updatedAt": now,
            }
        )
        self.wb_ids[name] = res.inserted_id
        if file_on_disk:
            self.ensure_sheet(name, excel_service.MONTHS[2])
            for _ in range(3):  # unrelated pre-existing rows
                self.add_row(
                    name,
                    self.rng.choice(list(self.files[physical(self.user.id, name)])),
                    ["Delivery Challan", f"PRE{self.rng.randint(1, 99)}", "02/02/2026", "t0"],
                )

    async def settings(self, name: str, year: int) -> None:
        await self.db.settings.insert_one(
            {
                "userId": self.user.id,
                "key": "excelState",
                "activeWorkbookName": name,
                "activeYear": year,
                "updatedAt": datetime.now(UTC),
            }
        )


def _pick_date(rng: random.Random) -> str | None:
    roll = rng.random()
    if roll < 0.45:
        return f"{rng.randint(1, 9):02d}/{rng.randint(1, 3):02d}/2026"
    if roll < 0.72:
        return f"{rng.randint(1, 28):02d}/{rng.randint(1, 12):02d}/2025"
    if roll < 0.80:
        return f"{rng.randint(1, 28):02d}/{rng.randint(1, 12):02d}/2024"  # year workbook created
    if roll < 0.88:
        return None
    return rng.choice(["garbled", "01/01/2052", "05/05/1999", "31/02/2026"])


async def build(
    variant: str, seed: int, db: Any, user: Any, other: Any, d: Path
) -> tuple[list[ObjectId], Builder]:
    rng = random.Random(seed)
    b = Builder(rng, db, user, other, d)
    if variant == "no_active":
        await b.workbook(WB26, 2026, False)
    elif variant == "rollover":
        await b.workbook(WB25, 2025, True)
        await b.settings(WB25, 2025)
    else:
        await b.workbook(WB26, 2026, True, file_on_disk=variant != "active_file_missing")
        if variant != "missing_old_year":
            await b.workbook(WB25, 2025, False)
        await b.settings(WB26, 2026)

    ids: list[ObjectId] = []
    specs: list[dict[str, Any]] = []
    for i in range(rng.randint(14, 20)):
        is_ti = rng.random() < 0.4
        spec: dict[str, Any] = {
            "doc_type": "Tax Invoice" if is_ti else "Delivery Challan",
            "number": None if is_ti else f"S{seed}-{i:02d}",
            "tin": f"INV{seed}-{i:02d}" if is_ti else None,
            "ref": f"R{i}" if is_ti and rng.random() < 0.5 else None,
            "date": _pick_date(rng),
        }
        specs.append(spec)
        if (
            variant not in ("active_file_missing", "rollover", "no_active")
            and specs
            and rng.random() < 0.12
            and len(specs) > 2
        ):
            specs.append(dict(rng.choice(specs[:-1])))  # duplicate (type, number, date) document
    for spec in specs:
        doc_id = await make_doc(
            db,
            user.id,
            spec["number"],
            spec["date"],
            spec["doc_type"],
            tax_invoice_no=spec["tin"],
            reference_no=spec["ref"],
        )
        ids.append(doc_id)
        await _old_records(b, doc_id, spec, variant)
    write_files(d, b.files)

    # specials: not processed, soft-deleted, foreign, unknown id, duplicate ids in the request
    specials = [
        await make_doc(db, user.id, "NOTDONE", "05/03/2026", status="failed"),
        await make_doc(db, user.id, "UPLOADING", "05/03/2026", status="uploaded"),
        await make_doc(db, user.id, "DELETED", "05/03/2026", is_deleted=True),
        await make_doc(db, other.id, "FOREIGN", "05/03/2026"),
        ObjectId(),
    ]
    order = ids + specials
    rng.shuffle(order)
    order += rng.sample(order, 3)  # duplicate ids: first occurrence wins
    return order, b


async def _old_records(b: Builder, doc_id: ObjectId, spec: dict[str, Any], variant: str) -> None:
    """0/1/2 earlier exports of the document, each with a REAL row in the workbook (except a few
    deliberately dangling ones with a unique key, which exercise the 'not found' warning)."""
    rng = b.rng
    count = rng.choices([0, 1, 2], weights=[50, 35, 15])[0]
    if variant in ("no_active",):
        count = 0
    year, month, _ = excel_service.document_period(spec["date"], CLOCK)
    dest = {2026: WB26, 2025: WB25}.get(year)
    if variant == "rollover":
        dest = {2025: WB25}.get(year)
    if variant == "missing_old_year" and year == 2025:
        dest = None
    for k in range(count):
        roll = rng.random()
        unchanged = dest is not None and roll < 0.4 and variant != "active_file_missing"
        wb: str
        if unchanged and dest is not None:
            wb, sheet = dest, month
            rec = {
                "number": spec["number"],
                "tin": spec["tin"],
                "ref": spec["ref"],
                "date": spec["date"],
            }
        else:
            wb = rng.choice([w for w in (WB26, WB25) if w in b.wb_ids] or [WB25])
            sheet = rng.choice(excel_service.MONTHS[:4])
            old_date = f"0{rng.randint(1, 9)}/0{rng.randint(1, 3)}/2026"
            rec = {
                "number": None if spec["tin"] else f"OLD-{doc_id}-{k}",
                "tin": f"OLDINV-{doc_id}-{k}" if spec["tin"] else None,
                "ref": None,
                "date": old_date,
            }
        file_exists = physical(b.user.id, wb) in b.files
        dangling = (not file_exists) or (not unchanged and rng.random() < 0.15)
        if file_exists and not dangling:
            b.ensure_sheet(wb, sheet)
            b.add_row(
                wb,
                sheet,
                [
                    spec["doc_type"],
                    number_cell(spec["doc_type"], rec["tin"], rec["ref"], rec["number"]),
                    rec["date"],
                    "t-old",
                ],
            )
        workbook_id: ObjectId | None = b.wb_ids.get(wb)
        r2 = rng.random()
        if r2 < 0.05:
            workbook_id = ObjectId()  # record of a workbook that no longer exists
        elif r2 < 0.10 and wb == WB26:
            workbook_id = None  # saved while the workbook record was missing
        if variant == "rollover" and wb == WB26:
            workbook_id = None
        stamp = b.tick()
        await b.db.exportedrows.insert_one(
            {
                "documentId": doc_id,
                "userId": b.user.id,
                "workbookId": workbook_id,
                "workbookFilename": wb,
                "worksheet": sheet,
                "documentType": spec["doc_type"],
                "taxInvoiceNo": rec["tin"],
                "referenceNo": rec["ref"],
                "number": rec["number"],
                "date": rec["date"],
                "exportedAt": stamp,
                "createdAt": stamp,
                "updatedAt": stamp,
            }
        )


async def _new_bulk(client: Any, user: Any, ids: list[ObjectId]) -> tuple[int, dict]:
    r = await client.post(
        f"{BASE}/bulk-save", headers=user.headers, json={"documentIds": [str(i) for i in ids]}
    )
    return r.status_code, r.json()


async def _new_single(client: Any, user: Any, ids: list[ObjectId]) -> list[tuple[int, dict]]:
    out = []
    for i in ids:
        r = await client.post(f"{BASE}/{i}/save", headers=user.headers)
        out.append((r.status_code, r.json()))
    return out


async def _old_single(user_id: ObjectId, ids: list[ObjectId]) -> list[tuple[int, dict]]:
    return [await oracle.single_save(i, user_id) for i in ids]


async def _parity(
    client: Any,
    db: Any,
    make_user: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    variant: str,
    seed: int,
    mode: str,
) -> dict[str, Any]:
    user, other = await make_user(), await make_user()
    uids = [user.id, other.id]
    init, dir_a, dir_b = tmp_path / "init", tmp_path / "a", tmp_path / "b"
    monkeypatch.setattr(excel_service, "EXPORT_DIR", init)
    ids, _ = await build(variant, seed, db, user, other, init)
    snap = await snapshot(db, uids)
    shutil.copytree(init, dir_a)
    shutil.copytree(init, dir_b)

    monkeypatch.setattr(excel_service, "EXPORT_DIR", dir_a)
    if mode == "bulk":
        old_out: Any = await oracle.bulk_save(ids, user.id)
    else:
        old_out = await _old_single(user.id, ids)
    old_state = await capture(db, uids, dir_a)

    await restore(db, uids, snap)
    monkeypatch.setattr(excel_service, "EXPORT_DIR", dir_b)
    if mode == "bulk":
        new_out: Any = await _new_bulk(client, user, ids)
    else:
        new_out = await _new_single(client, user, ids)
    new_state = await capture(db, uids, dir_b)

    assert new_out[0] == old_out[0]
    if isinstance(old_out[1], dict) and isinstance(new_out[1], dict):
        for field in sorted(set(old_out[1]) | set(new_out[1])):  # name the differing field
            assert new_out[1].get(field) == old_out[1].get(field), (
                field,
                _short(new_out[1].get(field)),
                _short(old_out[1].get(field)),
            )
    assert new_out == old_out
    for key in old_state:
        assert new_state[key] == old_state[key], key
    # sanity: the scenario really did something
    if variant not in ("no_active",) and mode == "bulk":
        assert old_out[1]["succeeded"] or old_out[1]["blocked"]
    return {"out": old_out, "state": old_state}


PARITY_CASES = (
    [("base", s, "bulk") for s in range(1, 7)]
    + [("base", s, "single") for s in (1, 2)]
    + [("missing_old_year", 11, "bulk"), ("missing_old_year", 12, "bulk")]
    + [("no_active", 21, "bulk"), ("no_active", 22, "single")]
    + [("rollover", 31, "bulk"), ("rollover", 32, "bulk"), ("rollover", 33, "single")]
    + [("active_file_missing", 41, "bulk"), ("active_file_missing", 42, "bulk")]
)


def _short(value: Any) -> Any:
    """Readable form of a response field for assertion messages."""
    if isinstance(value, list):
        return " ".join(
            (
                f"{v['documentId'][-4:]}/{v['message'].split('(')[-1][:3]}"
                if isinstance(v, dict) and "message" in v
                else str(v)[-6:]
            )
            for v in value
        )
    return value


@pytest.mark.parametrize(("variant", "seed", "mode"), PARITY_CASES)
async def test_batched_save_matches_old_per_document_save(
    client: Any,
    db: Any,
    make_user: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    variant: str,
    seed: int,
    mode: str,
) -> None:
    res = await _parity(client, db, make_user, tmp_path, monkeypatch, variant, seed, mode)
    out = res["out"]
    if variant == "rollover" and mode == "bulk":
        assert out[1]["blocked"]["error"] == "NEED_NEW_WORKBOOK"
    if variant == "no_active" and mode == "bulk":
        assert out[1]["blocked"]["error"] == "NO_ACTIVE_WORKBOOK"


async def test_scenarios_cover_save_again_and_new_year_workbooks(
    client: Any,
    db: Any,
    make_user: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guards the generator itself: seed 1 must exercise replaced rows, and some seed must
    create a late-paper year workbook, so the parity cases above are not vacuous."""
    res = await _parity(client, db, make_user, tmp_path, monkeypatch, "base", 1, "bulk")
    assert res["out"][1]["replaced"] > 0
    names = {w["filename"] for w in res["state"]["workbooks"]}
    assert WB26 in names and WB25 in names
    created = 0
    for seed in range(1, 7):
        d = tmp_path / f"probe{seed}"
        u1, u2 = await make_user(), await make_user()
        monkeypatch.setattr(excel_service, "EXPORT_DIR", d)
        await build("base", seed, db, u1, u2, d)
        created += await db.documents.count_documents(
            {"userId": u1.id, "date": {"$regex": "/2024$"}}
        )
    assert created > 0


# ---- the one DELIBERATE difference ------------------------------------------------------------


async def test_batch_protects_every_row_appended_in_the_batch(
    client: Any,
    db: Any,
    make_user: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Documents A and B in one batch have IDENTICAL (type, number, date). A has an old record
    whose row is already gone from the file. The OLD code's single 'protect' only shielded A's own
    fresh row, so A's removal ate B's fresh identical row. The batch code protects every row
    appended in the batch: both fresh rows survive, A just gets the 'not found' warning.
    (B is saved first, so A's removal runs while B's fresh row is already in the file.)"""
    user = await make_user()
    init, dir_a, dir_b = tmp_path / "init", tmp_path / "a", tmp_path / "b"
    monkeypatch.setattr(excel_service, "EXPORT_DIR", init)
    now = datetime.now(UTC)
    wb = await db.workbooks.insert_one(
        {
            "userId": user.id,
            "year": 2026,
            "filename": WB26,
            "isActive": True,
            "archivedAt": None,
            "createdAt": now,
            "updatedAt": now,
        }
    )
    await db.settings.insert_one(
        {"userId": user.id, "key": "excelState", "activeWorkbookName": WB26, "activeYear": 2026}
    )
    write_files(init, {physical(user.id, WB26): {"March": []}})
    a = await make_doc(db, user.id, "DUP1", "05/03/2026")
    b = await make_doc(db, user.id, "DUP1", "05/03/2026")
    await db.exportedrows.insert_one(
        {
            "documentId": a,
            "userId": user.id,
            "workbookId": wb.inserted_id,
            "workbookFilename": WB26,
            "worksheet": "March",
            "documentType": "Delivery Challan",
            "taxInvoiceNo": None,
            "referenceNo": None,
            "number": "DUP1",
            "date": "05/03/2026",
            "exportedAt": now,
            "createdAt": now,
            "updatedAt": now,
        }
    )
    snap = await snapshot(db, [user.id])
    shutil.copytree(init, dir_a)
    shutil.copytree(init, dir_b)

    monkeypatch.setattr(excel_service, "EXPORT_DIR", dir_a)
    _, old = await oracle.bulk_save([b, a], user.id)
    old_rows = read_dir(dir_a)[xlsx_path(dir_a, user.id, WB26).name][0][1][1:]
    await restore(db, [user.id], snap)
    monkeypatch.setattr(excel_service, "EXPORT_DIR", dir_b)
    status, new = await _new_bulk(client, user, [b, a])
    new_rows = read_dir(dir_b)[xlsx_path(dir_b, user.id, WB26).name][0][1][1:]

    assert status == 200 and new["succeeded"] == [str(b), str(a)]
    assert len(old_rows) == 1 and old["replaced"] == 1  # old: B's fresh row was eaten
    assert len(new_rows) == 2 and new["replaced"] == 0  # new: both fresh rows survive
    assert [w["documentId"] for w in new["staleWarnings"]] == [str(a)]
    assert "was not found in Book2026 (March)" in new["staleWarnings"][0]["message"]


async def test_identical_rows_in_one_batch_with_old_record_matches_old_path(
    client: Any,
    db: Any,
    make_user: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The protect multiset: A and B have IDENTICAL keys, A has an old record whose row EXISTS.
    The old row goes, both fresh rows survive, and the result equals the old path's."""
    user, other = await make_user(), await make_user()
    init, dir_a, dir_b = tmp_path / "init", tmp_path / "a", tmp_path / "b"
    monkeypatch.setattr(excel_service, "EXPORT_DIR", init)
    now = datetime.now(UTC)
    wb = await db.workbooks.insert_one(
        {
            "userId": user.id,
            "year": 2026,
            "filename": WB26,
            "isActive": True,
            "archivedAt": None,
            "createdAt": now,
            "updatedAt": now,
        }
    )
    await db.settings.insert_one(
        {"userId": user.id, "key": "excelState", "activeWorkbookName": WB26, "activeYear": 2026}
    )
    old_row = ["Delivery Challan", "DUP1", "05/03/2026", "t-old"]
    write_files(init, {physical(user.id, WB26): {"March": [old_row]}})
    a = await make_doc(db, user.id, "DUP1", "05/03/2026")
    b = await make_doc(db, user.id, "DUP1", "05/03/2026")
    await db.exportedrows.insert_one(
        {
            "documentId": a,
            "userId": user.id,
            "workbookId": wb.inserted_id,
            "workbookFilename": WB26,
            "worksheet": "March",
            "documentType": "Delivery Challan",
            "taxInvoiceNo": None,
            "referenceNo": None,
            "number": "DUP1",
            "date": "05/03/2026",
            "exportedAt": now,
            "createdAt": now,
            "updatedAt": now,
        }
    )
    uids = [user.id, other.id]
    snap = await snapshot(db, uids)
    shutil.copytree(init, dir_a)
    shutil.copytree(init, dir_b)
    monkeypatch.setattr(excel_service, "EXPORT_DIR", dir_a)
    old_out = await oracle.bulk_save([a, b], user.id)
    old_state = await capture(db, uids, dir_a)
    await restore(db, uids, snap)
    monkeypatch.setattr(excel_service, "EXPORT_DIR", dir_b)
    new_out = await _new_bulk(client, user, [a, b])
    new_state = await capture(db, uids, dir_b)
    assert new_out == old_out and new_state == old_state
    rows = new_state["files"][xlsx_path(dir_b, user.id, WB26).name][0][1][1:]
    assert len(rows) == 2 and new_out[1]["replaced"] == 1  # one old row out, two fresh rows in
    assert await db.exportedrows.count_documents({"userId": user.id}) == 2  # one record each
