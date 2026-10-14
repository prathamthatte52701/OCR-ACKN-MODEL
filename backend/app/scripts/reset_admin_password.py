"""Break-glass: set a new password for an ADMIN account. Admins cannot use forgot-password;
this server-side script (run by hand) and the admin's own change-password are the only ways
an admin's password changes. Run with:
    python -m app.scripts.reset_admin_password --db <name> --email <admin email>           # dry-run
    python -m app.scripts.reset_admin_password --db <name> --email <admin email> --apply   # write
The new password is prompted for twice via getpass - never taken from argv/env, never printed
or logged. `--db` must equal the MONGO_DB_NAME this process is configured with. --apply sets
the new hash, bumps tokenVersion (logs out every existing session) and writes an audit entry.
Refuses (non-zero exit) unknown/non-admin/Google-only accounts and passwords failing the rules.
"""

import argparse
import asyncio
import getpass
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.audit_log import log_action
from app.core.config import settings
from app.core.database import close_mongo_connection, connect_to_mongo, get_database
from app.core.security import hash_password
from app.core.validators import normalize_email, validate_password

AUDIT_ACTION = "admin_password_reset_script"


class Refused(Exception):
    pass


async def reset_admin_password(db: Any, email: str, new_password: str, apply: bool = False) -> str:
    """Returns the admin's email on success (dry-run: nothing written). Raises Refused."""
    email = normalize_email(email)
    user = await db.users.find_one({"email": email})
    if not user:
        raise Refused(f"No account with email {email!r}.")
    if user.get("role") != "admin":
        raise Refused(f"{email!r} is not an admin account.")
    if not user.get("passwordHash"):
        raise Refused(f"{email!r} is a Google-only account - it has no password to reset.")
    if err := validate_password(new_password, user.get("username"), email):
        raise Refused(f"Password rejected: {err}")
    if apply:
        result = await db.users.update_one(
            {"_id": user["_id"], "role": "admin"},
            {
                "$set": {
                    "passwordHash": hash_password(new_password),
                    "tokenVersion": user["tokenVersion"] + 1,
                    "updatedAt": datetime.now(UTC),
                }
            },
        )
        if result.modified_count != 1:
            raise Refused("Update did not apply - nothing changed.")
        await log_action(user["_id"], AUDIT_ACTION, {"email": email})
    return email


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, help="database name; must match MONGO_DB_NAME")
    parser.add_argument("--email", required=True, help="email of the admin account")
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = parser.parse_args()
    if args.db != settings.mongo_db_name:
        sys.exit(
            f"Refusing to run: --db {args.db!r} does not match the configured "
            f"MONGO_DB_NAME {settings.mongo_db_name!r}."
        )
    new_password = getpass.getpass("New admin password: ")
    if getpass.getpass("Repeat new password: ") != new_password:
        sys.exit("Refusing: the two passwords do not match.")
    print(f"Database: {settings.mongo_db_name}  mode: {'APPLY' if args.apply else 'dry-run'}")
    await connect_to_mongo()
    try:
        email = await reset_admin_password(get_database(), args.email, new_password, args.apply)
    except Refused as exc:
        sys.exit(f"Refused: {exc}")
    finally:
        await close_mongo_connection()
    if args.apply:
        print(f"Password reset for admin {email}. All their existing sessions are logged out.")
    else:
        print(f"Dry-run OK for admin {email} - nothing written. Re-run with --apply to write.")


if __name__ == "__main__":
    asyncio.run(main())
