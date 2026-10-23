"""REPORT-ONLY: list users who have 2+ `workbooks` records whose names map to the same canonical
file (excel_service.workbook_key). Changes nothing (no writes, no deletes, no file changes). Run:
    python -m app.scripts.find_duplicate_workbooks --db <name> [--exports-dir <dir>]
`--db` must equal the configured MONGO_DB_NAME. Prints counts and record ids only.
Exit codes: 0 ok (even when duplicates are found), 1 database error, 2 --db mismatch.
"""

import argparse
import asyncio
import sys
from collections import defaultdict
from pathlib import Path

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import PyMongoError

from app.core.config import settings
from app.features.excel import service as excel_service


async def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="find_duplicate_workbooks")
    parser.add_argument("--db", required=True, help="database name; must match MONGO_DB_NAME")
    parser.add_argument("--exports-dir", default=None, help="exports dir (default: service's)")
    args = parser.parse_args(argv)

    if args.db != settings.mongo_db_name:
        print(
            f"REFUSED: --db {args.db!r} does not match the configured database "
            f"{settings.mongo_db_name!r}. Nothing changed."
        )
        return 2

    exports = Path(args.exports_dir) if args.exports_dir else excel_service.EXPORT_DIR
    print(f"Database: {args.db}  mode: report-only (nothing is changed)")
    client: AsyncIOMotorClient = AsyncIOMotorClient(
        settings.mongo_uri, serverSelectionTimeoutMS=10000, tz_aware=True
    )
    try:
        db = client[args.db]
        try:
            groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
            async for w in db.workbooks.find(
                {}, {"userId": 1, "filename": 1, "year": 1, "isActive": 1}
            ):
                key = excel_service.workbook_key(str(w.get("filename", "")))
                groups[(str(w.get("userId")), key)].append(w)
        except PyMongoError as exc:
            print(f"ERROR: database error ({type(exc).__name__}).")
            return 1

        users = set()
        n_groups = 0
        for (uid, key), recs in sorted(groups.items()):
            if len(recs) < 2:
                continue
            n_groups += 1
            users.add(uid)
            print(f"user {uid}  key {key!r}  records: {len(recs)}")
            paths: dict[str, int] = defaultdict(int)
            for r in recs:
                name = str(r.get("filename", ""))
                phys = excel_service.file_path(excel_service.physical_workbook_filename(uid, name))
                # exports dir may differ from the service default
                phys = exports / phys.name
                paths[str(phys).lower()] += 1
                print(
                    f"  _id {r['_id']}  filename {name!r}  year {r.get('year')}  "
                    f"isActive {r.get('isActive')}  file exists: {phys.exists()}"
                )
            shared = any(c > 1 for c in paths.values())
            print(f"  same physical path (case-insensitive): {shared}")
        print(f"users with duplicates: {len(users)}, duplicate groups: {n_groups}")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
