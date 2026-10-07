"""One-off, idempotent migration: give every pre-approval-era user
`status: "approved"` so the admin-approval gate does not lock out existing
accounts. Run with:
    python -m app.scripts.migrate_user_status [--dry-run]
Users that already have a status are never touched.
"""

import argparse
import asyncio

from app.core.database import close_mongo_connection, connect_to_mongo, get_database


async def migrate(dry_run: bool = False) -> int:
    db = get_database()
    query = {"status": {"$exists": False}}
    if dry_run:
        return await db.users.count_documents(query)
    result = await db.users.update_many(query, {"$set": {"status": "approved"}})
    return result.modified_count


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="count only, change nothing")
    args = parser.parse_args()
    await connect_to_mongo()
    try:
        count = await migrate(args.dry_run)
    finally:
        await close_mongo_connection()
    verb = "Would update" if args.dry_run else "Updated"
    print(f"{verb} {count} user(s) to status=approved.")


if __name__ == "__main__":
    asyncio.run(main())
