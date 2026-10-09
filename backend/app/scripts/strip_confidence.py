"""One-off, idempotent cleanup: remove the retired AI-confidence fields
(taxInvoiceNoConfidence, referenceNoConfidence, numberConfidence, dateConfidence)
from `documents` and `exportedrows`. Run with:
    python -m app.scripts.strip_confidence --db <name>           # dry-run (default), counts only
    python -m app.scripts.strip_confidence --db <name> --apply   # actually write
`--db` must equal the MONGO_DB_NAME this process is configured with, otherwise the
script refuses to run. Take a backup before --apply. Nothing else is touched.
"""

import argparse
import asyncio
import sys
from typing import Any

from app.core.config import settings
from app.core.database import close_mongo_connection, connect_to_mongo, get_database

FIELDS = ("taxInvoiceNoConfidence", "referenceNoConfidence", "numberConfidence", "dateConfidence")
COLLECTIONS = ("documents", "exportedrows")


async def strip_confidence(db: Any, apply: bool = False) -> dict[str, int]:
    """Returns {collection: rows that carry (dry-run) / had (apply) any of the fields}."""
    query = {"$or": [{f: {"$exists": True}} for f in FIELDS]}
    counts: dict[str, int] = {}
    for name in COLLECTIONS:
        if apply:
            result = await db[name].update_many(query, {"$unset": {f: "" for f in FIELDS}})
            counts[name] = result.modified_count
        else:
            counts[name] = await db[name].count_documents(query)
    return counts


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, help="database name; must match MONGO_DB_NAME")
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = parser.parse_args()
    if args.db != settings.mongo_db_name:
        sys.exit(
            f"Refusing to run: --db {args.db!r} does not match the configured "
            f"MONGO_DB_NAME {settings.mongo_db_name!r}."
        )
    print(f"Database: {settings.mongo_db_name}  mode: {'APPLY' if args.apply else 'dry-run'}")
    await connect_to_mongo()
    try:
        counts = await strip_confidence(get_database(), args.apply)
    finally:
        await close_mongo_connection()
    verb = "Updated" if args.apply else "Would update"
    for name, count in counts.items():
        print(f"{verb} {count} row(s) in {name}.")
    if not args.apply:
        print("Dry-run only - re-run with --apply to write.")


if __name__ == "__main__":
    asyncio.run(main())
