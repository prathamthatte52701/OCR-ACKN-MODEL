"""Contract tests for scripts/wipe_all_except_admins.py (written from the spec).
SAFETY: every DB name used here must end in "_test" (see _guard)."""

import ast
import asyncio
import io
import os
import re
import subprocess
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import openpyxl
import pytest
import pytest_asyncio
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket
from PIL import Image

from app.core.config import settings
from app.core.database import _ensure_indexes
from app.features.excel import service as excel_service
from app.features.ocr import extraction as ex
from app.features.ocr import paddle_runner, pipeline
from app.scripts import wipe_all_except_admins as wipe

SUB_DB = "ackn_wipe_check_test"
BACKEND = Path(__file__).resolve().parents[2]
PW_HASH_MARK = "$2b$"
FILE_MARK = b"SECRET-FILE-CONTENT-7731"
NON_ADMIN_DOMAIN = "nonadmin-secret.example"
ROW_COLLECTIONS = [
    "documents",
    "corrections",
    "exportedrows",
    "workbooks",
    "auditlogs",
    "orphanedfiles",
    "settings",
]
COUNTS = {
    "documents": 3,
    "corrections": 4,
    "exportedrows": 5,
    "workbooks": 2,
    "auditlogs": 6,
    "orphanedfiles": 7,
    "settings": 8,
}
INDEXED = ["documents", "users", "settings", "orphanedfiles"]


def _guard(name: str) -> str:
    assert name.endswith("_test"), f"refusing non-test DB name {name!r}"
    return name


async def _run(name: str, *flags: str, exports: Path | None = None) -> int:
    return await wipe.run(["--db", _guard(name), *flags], exports_dir=exports)


# ---------- seeding / snapshots ----------


async def _seed(db: Any, make_user: Any, tmp_path: Path) -> dict[str, Any]:
    _guard(db.name)
    await _ensure_indexes(db)
    a1 = await make_user(role="admin", email="boss1@looptest.local")
    a2 = await make_user(role="admin", status="pending", email="boss2@looptest.local")
    await db.users.update_one({"_id": a1.id}, {"$set": {"tokenVersion": 7}})
    users = [
        await make_user(status="approved", email=f"ok@{NON_ADMIN_DOMAIN}"),
        await make_user(status="pending", email=f"wait@{NON_ADMIN_DOMAIN}"),
        await make_user(status="rejected", email=f"no@{NON_ADMIN_DOMAIN}"),
    ]
    await db.users.insert_one(  # legacy user with no role/status at all
        {"username": "legacy", "email": f"old@{NON_ADMIN_DOMAIN}", "tokenVersion": 0}
    )
    now = datetime.now(UTC)
    for name in ROW_COLLECTIONS:
        rows = []
        for n in range(COUNTS[name]):
            row: dict[str, Any] = {"userId": users[0].id, "n": n, "createdAt": now}
            if name == "orphanedfiles":
                row["gridFsFileId"] = ObjectId()
            if name == "settings":
                row["key"] = f"k{n}"
            rows.append(row)
        await db[name].insert_many(rows)
    bucket = AsyncIOMotorGridFSBucket(db)
    for i in range(3):
        await bucket.upload_from_stream(f"f{i}.png", FILE_MARK * (i + 1))
    exports = tmp_path / "exports"
    exports.mkdir()
    for fname in ("1_Book.xlsx", "1_Book.xlsx.lock", "1_Book.tmp123.xlsx", "2_Other.xlsx"):
        (exports / fname).write_bytes(FILE_MARK)
    (exports / "notes.txt").write_text("keep me")
    (exports / ".gitkeep").write_text("")
    (exports / "~$1_Book.xlsx").write_bytes(b"owner")
    (exports / "sub").mkdir()
    (exports / "sub" / "inner.xlsx").write_bytes(b"inner")
    return {"admins": [a1, a2], "users": users, "exports": exports}


async def _snapshot(db: Any) -> dict[str, list[dict[str, Any]]]:
    out = {}
    for name in sorted(await db.list_collection_names()):
        out[name] = await db[name].find({}).sort("_id", 1).to_list(None)
    return out


def _tree(path: Path) -> list[tuple[str, bytes | None]]:
    return sorted(
        (str(p.relative_to(path)), p.read_bytes() if p.is_file() else None) for p in path.rglob("*")
    )


async def _indexes(db: Any) -> dict[str, set[str]]:
    return {c: {i["name"] async for i in db[c].list_indexes()} for c in INDEXED}


def _line(out: str, name: str) -> str:
    return next(ln for ln in out.splitlines() if name in ln.split())


# ---------- 1. dry run ----------


async def test_dry_run_changes_nothing_and_prints_counts(
    db: Any, make_user: Any, tmp_path: Path, capsys: Any
) -> None:
    s = await _seed(db, make_user, tmp_path)
    before, tree = await _snapshot(db), _tree(s["exports"])
    capsys.readouterr()
    assert await _run(db.name, exports=s["exports"]) == 0
    assert await _snapshot(db) == before
    assert _tree(s["exports"]) == tree
    out = capsys.readouterr().out
    for name, n in {**COUNTS, "users": 4}.items():
        assert re.search(rf"(?<!\d){n}(?!\d)", _line(out, name)), (name, _line(out, name))
    for admin in s["admins"]:
        assert admin.email in out


# ---------- 2. apply ----------


async def test_apply_keeps_admins_wipes_rest(db: Any, make_user: Any, tmp_path: Path) -> None:
    s = await _seed(db, make_user, tmp_path)
    admins_before = await db.users.find({"role": "admin"}).sort("_id", 1).to_list(None)
    idx_before = await _indexes(db)
    exports = s["exports"]
    assert await _run(db.name, "--apply", "--i-have-a-backup", exports=exports) == 0
    assert await db.users.find({"role": "admin"}).sort("_id", 1).to_list(None) == admins_before
    assert await db.users.count_documents({}) == 2
    for name in ROW_COLLECTIONS + ["fs.files", "fs.chunks"]:
        assert await db[name].count_documents({}) == 0, name
    assert {p.name for p in exports.iterdir()} == {"notes.txt", ".gitkeep", "~$1_Book.xlsx", "sub"}
    assert (exports / "sub" / "inner.xlsx").read_bytes() == b"inner"
    assert (exports / "notes.txt").read_text() == "keep me"
    assert await _indexes(db) == idx_before
    assert "email_1" in idx_before["users"]
    dup = {"username": "dup", "email": s["admins"][0].email, "role": "user"}
    with pytest.raises(Exception, match="E11000"):
        await db.users.insert_one(dup)


# ---------- 3. refusals ----------


async def _assert_refused(db: Any, exports: Path, code: int, name: str, *flags: str) -> None:
    before, tree = await _snapshot(db), _tree(exports)
    assert await _run(name, *flags, exports=exports) == code
    assert await _snapshot(db) == before
    assert _tree(exports) == tree


async def test_apply_without_backup_flag_refused(db: Any, make_user: Any, tmp_path: Path) -> None:
    s = await _seed(db, make_user, tmp_path)
    await _assert_refused(db, s["exports"], 4, db.name, "--apply")


async def test_wrong_db_refused(db: Any, make_user: Any, tmp_path: Path) -> None:
    s = await _seed(db, make_user, tmp_path)
    await _assert_refused(
        db, s["exports"], 2, "ackn_some_other_test", "--apply", "--i-have-a-backup"
    )


@pytest.mark.parametrize("variant", ["none", "role_user", "no_role_field"])
async def test_no_admin_refused(db: Any, make_user: Any, tmp_path: Path, variant: str) -> None:
    s = await _seed(db, make_user, tmp_path)
    await db.users.delete_many({"role": "admin"})
    if variant == "role_user":
        await db.users.insert_one({"username": "fake", "email": "f@x.example", "role": "user"})
    elif variant == "no_role_field":
        await db.users.insert_one({"username": "fake", "email": "f@x.example"})
    await _assert_refused(db, s["exports"], 3, db.name, "--apply", "--i-have-a-backup")
    await _assert_refused(db, s["exports"], 3, db.name)  # dry run refuses too


# ---------- 4. idempotent / orphan chunks / missing dir / locked file ----------


async def test_second_run_deletes_nothing_and_orphan_chunks_cleaned(
    db: Any, make_user: Any, tmp_path: Path, capsys: Any
) -> None:
    s = await _seed(db, make_user, tmp_path)
    flags = ("--apply", "--i-have-a-backup")
    assert await _run(db.name, *flags, exports=s["exports"]) == 0
    await db["fs.chunks"].insert_one({"files_id": ObjectId(), "n": 0, "data": b"orphan"})
    assert await _run(db.name, *flags, exports=s["exports"]) == 0
    assert await db["fs.chunks"].count_documents({}) == 0
    assert await db.users.count_documents({}) == 2
    capsys.readouterr()
    assert await _run(db.name, *flags, exports=s["exports"]) == 0
    assert await _run(db.name, exports=s["exports"]) == 0
    out = capsys.readouterr().out
    for name in ROW_COLLECTIONS:
        assert not re.search(r"[1-9]", _line(out, name).replace(name, "")), _line(out, name)


async def test_missing_exports_dir_ok(db: Any, make_user: Any, tmp_path: Path) -> None:
    await _seed(db, make_user, tmp_path)
    gone = tmp_path / "does-not-exist"
    assert await _run(db.name, exports=gone) == 0
    assert await _run(db.name, "--apply", "--i-have-a-backup", exports=gone) == 0
    assert not gone.exists()


async def test_folder_named_like_workbook_is_left_alone_and_run_passes(
    db: Any, make_user: Any, tmp_path: Path
) -> None:
    s = await _seed(db, make_user, tmp_path)
    (s["exports"] / "dir.xlsx").mkdir()
    (s["exports"] / "dir.xlsx" / "inner.txt").write_text("keep")
    assert await _run(db.name, "--apply", "--i-have-a-backup", exports=s["exports"]) == 0
    assert (s["exports"] / "dir.xlsx" / "inner.txt").read_text() == "keep"
    assert await _run(db.name, "--apply", "--i-have-a-backup", exports=s["exports"]) == 0


@pytest.mark.skipif(os.name != "nt", reason="open handle blocks delete on Windows only")
async def test_locked_file_exit_1_lists_name(
    db: Any, make_user: Any, tmp_path: Path, capsys: Any
) -> None:
    s = await _seed(db, make_user, tmp_path)
    capsys.readouterr()
    with open(s["exports"] / "2_Other.xlsx", "rb"):  # Windows forbids deleting an open file
        code = await _run(db.name, "--apply", "--i-have-a-backup", exports=s["exports"])
    assert code == 1
    assert "2_Other.xlsx" in capsys.readouterr().out
    assert await db.users.count_documents({}) == 2


# ---------- 5. DB-name safety ----------


def test_no_non_test_db_name_in_this_file() -> None:
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if re.fullmatch(r"ackn\w*", node.value):
                assert node.value.endswith("_test"), node.value
    assert SUB_DB.endswith("_test") and settings.mongo_db_name.endswith("_test")


# ---------- 6. nothing sensitive in output ----------


async def test_output_has_no_secrets(db: Any, make_user: Any, tmp_path: Path, capsys: Any) -> None:
    s = await _seed(db, make_user, tmp_path)
    hashes = [u["passwordHash"] async for u in db.users.find({"passwordHash": {"$exists": True}})]
    tokens = [a._token for a in s["admins"] + s["users"]]
    capsys.readouterr()
    await _run(db.name, exports=s["exports"])
    await _run(db.name, "--apply", exports=s["exports"])  # refusal path
    await _run(db.name, "--apply", "--i-have-a-backup", exports=s["exports"])
    cap = capsys.readouterr()
    out = cap.out + cap.err
    assert hashes and PW_HASH_MARK not in out
    for secret in hashes + tokens + [FILE_MARK.decode(), NON_ADMIN_DOMAIN]:
        assert secret not in out
    for u in s["users"]:
        assert u.email not in out and u.password not in out


# ---------- subprocess (real CLI, throwaway DB) ----------


@pytest_asyncio.fixture
async def sub_db() -> AsyncIterator[Any]:
    client: Any = AsyncIOMotorClient(settings.mongo_uri)
    database = client[_guard(SUB_DB)]
    try:
        yield database
    finally:
        assert database.name == SUB_DB
        for name in await database.list_collection_names():
            await database[name].delete_many({})
        client.close()


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "MONGO_DB_NAME": _guard(SUB_DB)}
    return subprocess.run(
        [sys.executable, "-m", "app.scripts.wipe_all_except_admins", *args],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


async def test_cli_subprocess(sub_db: Any, tmp_path: Path) -> None:
    await sub_db.users.insert_many(
        [
            {"username": "adm", "email": "adm@looptest.local", "role": "admin"},
            {"username": "usr", "email": f"u@{NON_ADMIN_DOMAIN}", "role": "user"},
        ]
    )
    await sub_db.documents.insert_one({"n": 1})
    exports = tmp_path / "exp"
    exports.mkdir()
    (exports / "1_B.xlsx").write_bytes(b"x")
    ex_args = ["--exports-dir", str(exports)]

    assert _cli("--db", "ackn_other_test").returncode == 2
    assert _cli("--db", SUB_DB, "--apply").returncode == 4
    dry = _cli("--db", SUB_DB, *ex_args)
    assert dry.returncode == 0 and NON_ADMIN_DOMAIN not in dry.stdout + dry.stderr
    assert await sub_db.documents.count_documents({}) == 1 and (exports / "1_B.xlsx").exists()
    done = _cli("--db", SUB_DB, "--apply", "--i-have-a-backup", *ex_args)
    assert done.returncode == 0, done.stdout + done.stderr
    assert await sub_db.documents.count_documents({}) == 0
    assert [u["username"] async for u in sub_db.users.find({})] == ["adm"]
    assert not (exports / "1_B.xlsx").exists()


# ---------- 7. app works after the wipe ----------


async def test_app_flow_after_wipe(
    db: Any,
    client: Any,
    make_user: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = await _seed(db, make_user, tmp_path)
    assert await _run(db.name, "--apply", "--i-have-a-backup", exports=s["exports"]) == 0
    exports = tmp_path / "live"
    exports.mkdir()
    monkeypatch.setattr(excel_service, "EXPORT_DIR", exports)

    year = excel_service.current_period()[0]
    pipeline._reset_slot_for_tests()
    paddle_runner._reset_engine_for_tests()
    monkeypatch.setattr(pipeline, "run_ocr", lambda _p, **_k: "OCR TEXT")
    monkeypatch.setattr(pipeline, "classify_page_orientation", lambda _b: (0, 1.0))

    async def ai(document_type: str, _text: str) -> dict[str, Any]:
        return dict(
            ex.build_extraction_result(
                document_type, {"number": "820000123", "date": f"05/10/{year}"}
            )
        )

    monkeypatch.setattr(pipeline, "extract_header", ai)

    admin = s["admins"][0]
    login = await client.post(
        "/api/auth/login", json={"email": admin.email, "password": admin.password}
    )
    assert login.status_code == 200
    admin_h = {"Authorization": f"Bearer {login.json()['token']}"}

    creds = {"username": "freshie", "email": "fresh@looptest.local", "password": "Xq7!mZv#4Lp2"}
    sg = await client.post("/api/auth/signup", json=creds)
    assert sg.status_code == 201, sg.text
    login_body = {"email": creds["email"], "password": creds["password"]}
    assert (await client.post("/api/auth/login", json=login_body)).status_code == 403
    new = await db.users.find_one({"email": creds["email"]})
    assert new is not None and new["status"] == "pending"
    appr = await client.post(f"/api/admin/users/{new['_id']}/approve", headers=admin_h)
    assert appr.status_code == 200, appr.text
    tok = await client.post("/api/auth/login", json=login_body)
    assert tok.status_code == 200
    h = {"Authorization": f"Bearer {tok.json()['token']}"}

    buf = io.BytesIO()
    Image.new("RGB", (200, 200), "white").save(buf, format="PNG")
    up = await client.post(
        "/api/documents/upload",
        headers=h,
        files={"document": ("a.png", io.BytesIO(buf.getvalue()), "image/png")},
        data={"documentType": "Delivery Challan"},
    )
    assert up.status_code == 201, up.text
    doc_id = ObjectId(up.json()["document"]["_id"])
    doc: dict[str, Any] | None = None
    for _ in range(100):
        doc = await db.documents.find_one({"_id": doc_id})
        if doc and doc.get("uploadStatus") == "processed":
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError(f"document never processed: {doc}")

    r = await client.post("/api/documents/new-excel-file", headers=h, json={"filename": "Book"})
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/documents/{doc_id}/save", headers=h)
    assert r.status_code == 200, r.text
    files = list(exports.glob("*.xlsx"))
    assert len(files) == 1
    book = openpyxl.load_workbook(files[0])
    cells = [str(c) for ws in book for row in ws.iter_rows(values_only=True) for c in row]
    assert any("820000123" in c for c in cells)
    pipeline._reset_slot_for_tests()
