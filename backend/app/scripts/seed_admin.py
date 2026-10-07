"""One-off admin account seed. Run with:
    python -m app.scripts.seed_admin
Idempotent - does nothing if an account with a given email already exists.
Names, emails and passwords all come from env vars (ADMIN_1_NAME / _EMAIL /
_PASSWORD and ADMIN_2_...) - never hardcode real identities or credentials in
source, this file is committed to git.
"""

import asyncio
import sys
from datetime import UTC, datetime

from app.core.config import settings
from app.core.database import close_mongo_connection, connect_to_mongo, get_database
from app.core.security import hash_password

ADMINS = [
    {
        "name": settings.admin_1_name,
        "email": settings.admin_1_email.strip().lower(),
        "password": settings.admin_1_password,
        "vars": "ADMIN_1_NAME / ADMIN_1_EMAIL / ADMIN_1_PASSWORD",
    },
    {
        "name": settings.admin_2_name,
        "email": settings.admin_2_email.strip().lower(),
        "password": settings.admin_2_password,
        "vars": "ADMIN_2_NAME / ADMIN_2_EMAIL / ADMIN_2_PASSWORD",
    },
]


async def main() -> None:
    incomplete = [a["vars"] for a in ADMINS if not (a["name"] and a["email"] and a["password"])]
    if incomplete:
        sys.exit(
            "Missing admin env var(s): "
            + "; ".join(incomplete)
            + ". Set them in .env before seeding."
        )
    await connect_to_mongo()
    db = get_database()

    for admin in ADMINS:
        existing = await db.users.find_one({"email": admin["email"]})
        if existing:
            print(
                f"Admin account already exists ({admin['email']}), "
                f"role: {existing['role']}. Nothing to do."
            )
            continue

        now = datetime.now(UTC)
        await db.users.insert_one(
            {
                "username": admin["name"],
                "email": admin["email"],
                "passwordHash": hash_password(admin["password"]),
                "role": "admin",
                "status": "approved",
                "tokenVersion": 0,
                "createdAt": now,
                "updatedAt": now,
            }
        )
        print(f"Admin account created: {admin['email']} (role: admin).")

    await close_mongo_connection()


if __name__ == "__main__":
    asyncio.run(main())
