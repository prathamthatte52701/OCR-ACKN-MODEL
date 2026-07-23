"""One-off admin account seed. Run with:
    python -m app.scripts.seed_admin
Idempotent - does nothing if an account with a given email already exists.
Passwords come from env vars (ADMIN_1_PASSWORD / ADMIN_2_PASSWORD in .env) -
never hardcode real credentials in source, this file is committed to git.
"""

import asyncio
import sys
from datetime import UTC, datetime

from app.core.config import settings
from app.core.database import close_mongo_connection, connect_to_mongo, get_database
from app.core.security import hash_password

ADMINS = [
    {
        "name": "Arjav Jain",
        "email": "arjav99jain@gmail.com",
        "password": settings.admin_1_password,
    },
    {
        "name": "Pratham Thatte",
        "email": "prathamthatte527@gmail.com",
        "password": settings.admin_2_password,
    },
]


async def main() -> None:
    missing = [a["email"] for a in ADMINS if not a["password"]]
    if missing:
        sys.exit(
            "Missing password env var(s) for: "
            + ", ".join(missing)
            + ". Set ADMIN_1_PASSWORD / ADMIN_2_PASSWORD in .env before seeding."
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
                "tokenVersion": 0,
                "createdAt": now,
                "updatedAt": now,
            }
        )
        print(f"Admin account created: {admin['email']} (role: admin).")

    await close_mongo_connection()


if __name__ == "__main__":
    asyncio.run(main())
