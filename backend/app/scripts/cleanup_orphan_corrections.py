"""One-off: delete `corrections` rows whose document no longer exists (left behind by deletes
before corrections were removed with their document). Stop the backend first. Run with:
    python -m app.scripts.cleanup_orphan_corrections --db <name>            # dry-run
    python -m app.scripts.cleanup_orphan_corrections --db <name> --apply    # delete
`--db` must equal the configured MONGO_DB_NAME. Prints counts only. Idempotent.
Exit codes: 0 ok, 1 database error, 2 --db mismatch.
"""

import argparse
import asyncio
import sys

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import PyMongoError

from app.core.config import settings


async def _orphan_ids(db: AsyncIOMotorDatabase) -> list:
    doc_ids = {d["documentId"] async for d in db.corrections.find({}, {"documentId": 1})}
    existing = {
        d["_id"] async for d in db.documents.find({"_id": {"$in": list(doc_ids)}}, {"_id": 1})
    }
    return list(doc_ids - existing)


async def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="cleanup_orphan_corrections")
    parser.add_argument("--db", required=True, help="database name; must match MONGO_DB_NAME")
    parser.add_argument("--apply", action="store_true", help="delete (default: dry-run)")
    args = parser.parse_args(argv)

    if args.db != settings.mongo_db_name:
        print(
            f"REFUSED: --db {args.db!r} does not match the configured database "
            f"{settings.mongo_db_name!r}. Nothing changed."
        )
        return 2

    print(f"Database: {args.db}  mode: {'APPLY' if args.apply else 'dry-run'}")
    client: AsyncIOMotorClient = AsyncIOMotorClient(
        settings.mongo_uri, serverSelectionTimeoutMS=10000, tz_aware=True
    )
    try:
        db = client[args.db]
        try:
            total = await db.corrections.count_documents({})
            orphan_ids = await _orphan_ids(db)
            orphans = await db.corrections.count_documents({"documentId": {"$in": orphan_ids}})
            print(f"  corrections total: {total}")
            print(f"  orphaned (document gone): {orphans}")
            if not args.apply:
                print("Dry-run only - nothing changed. Re-run with --apply.")
                return 0
            res = await db.corrections.delete_many({"documentId": {"$in": orphan_ids}})
            print(f"  deleted: {res.deleted_count}")
        except PyMongoError as exc:
            print(f"ERROR: database error ({type(exc).__name__}). Re-run to finish.")
            return 1
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
