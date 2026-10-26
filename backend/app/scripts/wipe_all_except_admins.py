"""Wipe every non-admin user and ALL data (documents, workbooks, GridFS, export files), keeping only
admin accounts. Stop the backend first. Take a database backup before --apply. Run with:
    python -m app.scripts.wipe_all_except_admins --db <name>                              # dry-run
    python -m app.scripts.wipe_all_except_admins --db <name> --apply --i-have-a-backup      # wipe
    (optional) --exports-dir PATH   workbook folder; default is the app's backend/exports
`--db` must equal the configured MONGO_DB_NAME. Collections and indexes are kept (delete_many only).
Idempotent: after an interruption just re-run. Exit codes: 0 ok, 1 verification failed,
2 --db mismatch, 3 no admin user, 4 --apply without --i-have-a-backup.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import PyMongoError

from app.core.config import settings
from app.features.excel import service as excel_service

DATA_COLLECTIONS = (
    "documents",
    "corrections",
    "exportedrows",
    "workbooks",
    "auditlogs",
    "orphanedfiles",
    "settings",
    "passwordresetrequests",
    "chatmessages",
)
GRIDFS_COLLECTIONS = ("fs.files", "fs.chunks")
EXPORT_SUFFIXES = (".xlsx", ".lock")  # also covers .tmp{pid}.xlsx swap files
NON_ADMIN = {"role": {"$ne": "admin"}}


def _list_export_files(exports_dir: Path) -> tuple[list[Path], list[str]]:
    """(deletable files, refused entries). Only regular files directly inside the folder are
    deletable; symlinks and anything resolving outside it are refused, never followed."""
    if not exports_dir.exists():
        return [], []
    if exports_dir.is_symlink():
        return [], ["<exports folder itself is a symlink>"]
    root = exports_dir.resolve()
    files: list[Path] = []
    refused: list[str] = []
    for entry in os.scandir(root):
        name = entry.name
        if name.startswith("~$") or not name.lower().endswith(EXPORT_SUFFIXES):
            continue  # Excel owner files, .gitkeep and anything else stay
        if entry.is_dir(follow_symlinks=False):
            continue  # a real folder is not a workbook file; it stays
        if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
            refused.append(f"{name} (symlink or not a regular file)")
        elif Path(entry.path).resolve().parent != root:
            refused.append(f"{name} (resolves outside the exports folder)")
        else:
            files.append(Path(entry.path))
    return sorted(files), sorted(refused)


async def _snapshot(db: AsyncIOMotorDatabase, exports_dir: Path) -> dict[str, Any]:
    agg = (
        await db["fs.files"]
        .aggregate([{"$group": {"_id": None, "n": {"$sum": "$length"}}}])
        .to_list(1)
    )
    files, refused = _list_export_files(exports_dir)
    return {
        "admins": sorted(
            await db.users.find({"role": "admin"}).to_list(None), key=lambda a: a["_id"]
        ),
        "non_admin": await db.users.count_documents(NON_ADMIN),
        "counts": {n: await db[n].count_documents({}) for n in DATA_COLLECTIONS},
        "gridfs_files": await db["fs.files"].count_documents({}),
        "gridfs_chunks": await db["fs.chunks"].count_documents({}),
        "gridfs_bytes": agg[0]["n"] if agg else 0,
        "export_files": files,
        "export_refused": refused,
    }


def _print_table(s: dict[str, Any], exports_dir: Path, applied: bool) -> None:
    verb = "deleted" if applied else "to delete"
    print(f"\n  {'collection':<22}{verb:>12}{'kept':>8}")
    print(f"  {'users':<22}{s['non_admin']:>12}{len(s['admins']):>8}   (non-admin / admin)")
    for name, n in s["counts"].items():
        print(f"  {name:<22}{n:>12}{0:>8}")
    print(
        f"  GridFS: {s['gridfs_files']} files, {s['gridfs_chunks']} chunks, "
        f"{s['gridfs_bytes']} bytes {verb}"
    )
    print(f"  Export files {verb} in {exports_dir}: {len(s['export_files'])}")
    for p in s["export_files"]:
        print(f"    {p.name}")
    for r in s["export_refused"]:
        print(f"    REFUSED: {r}")
    print(f"  Admin accounts that stay ({len(s['admins'])}):")
    for a in s["admins"]:
        print(f"    {a.get('email')}")


async def _wipe(db: AsyncIOMotorDatabase, files: list[Path]) -> list[str]:
    """Order: non-admin users (kills their tokens at once), data, GridFS, export files.
    Returns names of export files that could not be deleted."""
    await db.users.delete_many(NON_ADMIN)
    for name in DATA_COLLECTIONS:
        await db[name].delete_many({})
    for name in GRIDFS_COLLECTIONS:  # files first, then chunks; a rerun clears any orphan chunks
        await db[name].delete_many({})
    failed: list[str] = []
    for path in files:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            failed.append(path.name)
    return failed


async def run(argv: list[str], *, exports_dir: Path | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wipe_all_except_admins")
    parser.add_argument("--db", required=True, help="database name; must match MONGO_DB_NAME")
    parser.add_argument("--apply", action="store_true", help="delete (default: dry-run)")
    parser.add_argument("--i-have-a-backup", action="store_true", dest="backup")
    parser.add_argument("--exports-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    exports_dir = exports_dir or args.exports_dir or excel_service.EXPORT_DIR

    if args.db != settings.mongo_db_name:
        print(
            f"REFUSED: --db {args.db!r} does not match the configured database "
            f"{settings.mongo_db_name!r}. Nothing changed."
        )
        return 2
    if args.apply and not args.backup:
        print("REFUSED: --apply requires --i-have-a-backup (back up the database first).")
        return 4

    print("STOP THE BACKEND FIRST (it must not be writing while this runs).")
    print(f"Database: {args.db}  mode: {'APPLY' if args.apply else 'dry-run'}")
    client: AsyncIOMotorClient = AsyncIOMotorClient(
        settings.mongo_uri, serverSelectionTimeoutMS=10000, tz_aware=True
    )
    try:
        db = client[args.db]
        try:
            await client.admin.command("ping")
            before = await _snapshot(db, exports_dir)
        except PyMongoError as exc:
            print(f"ERROR: could not talk to MongoDB ({type(exc).__name__}). Nothing changed.")
            return 1
        if not before["admins"]:
            print(
                "REFUSED: no admin user exists - the wipe would lock everyone out. "
                "Run `python -m app.scripts.seed_admin` first. Nothing changed."
            )
            return 3
        _print_table(before, exports_dir, applied=False)
        if not args.apply:
            print("\nDry-run only - nothing changed. Re-run with --apply --i-have-a-backup.")
            return 0

        try:
            failed = await _wipe(db, before["export_files"])
            after = await _snapshot(db, exports_dir)
        except PyMongoError as exc:
            print(f"FAIL: database error mid-wipe ({type(exc).__name__}). Re-run to finish.")
            return 1
        problems = [f"could not delete export file: {n}" for n in failed]
        problems += [f"refused export entry remains: {r}" for r in after["export_refused"]]
        if after["admins"] != before["admins"]:
            problems.append("admin accounts changed or missing")
        problems += [f"{n} still has {c} rows" for n, c in after["counts"].items() if c]
        if after["non_admin"]:
            problems.append(f"{after['non_admin']} non-admin users remain")
        if after["gridfs_files"] or after["gridfs_chunks"]:
            problems.append("GridFS is not empty")
        leftovers = [p.name for p in after["export_files"] if p.name not in failed]
        problems += [f"export file remains: {n}" for n in leftovers]

        print("\n=== RESULT ===")
        if problems:
            print("FAIL")
            for p in problems:
                print(f"  - {p}")
            return 1
        print(f"PASS - only {len(before['admins'])} admin account(s) remain; all else is empty.")
        print("Restart the backend (clears in-memory login rate limits).")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
