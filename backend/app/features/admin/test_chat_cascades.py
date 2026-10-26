"""Chat cascades: delete_user removes only that user's chat thread; the wipe script clears it."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.scripts import wipe_all_except_admins as wipe


def _msg(thread: Any, from_id: Any, role: str) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "threadUserId": thread,
        "fromId": from_id,
        "fromRole": role,
        "text": "hi",
        "createdAt": now,
        "updatedAt": now,
    }


async def _delete(client: Any, admin: Any, user: Any) -> None:
    r = await client.delete(f"/api/admin/users/{user.id}", headers=admin.headers)
    assert r.status_code == 200, r.text


async def test_delete_user_removes_only_their_thread(client: Any, db: Any, make_user: Any) -> None:
    admin, a, b = await make_user(role="admin"), await make_user(), await make_user()
    await db.chatmessages.insert_many(
        [
            _msg(a.id, a.id, "user"),
            _msg(a.id, admin.id, "admin"),
            _msg(b.id, b.id, "user"),
            _msg(b.id, admin.id, "admin"),  # admin-authored, in B's thread: must stay
        ]
    )
    await _delete(client, admin, a)
    assert await db.chatmessages.count_documents({"threadUserId": a.id}) == 0
    assert await db.chatmessages.count_documents({"threadUserId": b.id}) == 2
    assert await db.chatmessages.count_documents({"fromId": admin.id}) == 1


async def test_delete_user_without_messages(client: Any, db: Any, make_user: Any) -> None:
    admin, a, b = await make_user(role="admin"), await make_user(), await make_user()
    await db.chatmessages.insert_one(_msg(b.id, b.id, "user"))
    await _delete(client, admin, a)
    assert await db.users.find_one({"_id": a.id}) is None
    assert await db.chatmessages.count_documents({}) == 1


async def test_wipe_dry_run_counts_and_apply_clears_chat(
    db: Any, make_user: Any, tmp_path: Path, capsys: Any
) -> None:
    assert db.name.endswith("_test")
    admin, u = await make_user(role="admin"), await make_user()
    await db.chatmessages.insert_many([_msg(u.id, u.id, "user"), _msg(u.id, admin.id, "admin")])
    exports = tmp_path / "exp"
    capsys.readouterr()
    assert await wipe.run(["--db", db.name], exports_dir=exports) == 0
    line = next(x for x in capsys.readouterr().out.splitlines() if "chatmessages" in x)
    assert "2" in line.split()
    assert await db.chatmessages.count_documents({}) == 2
    args = ["--db", db.name, "--apply", "--i-have-a-backup"]
    assert await wipe.run(args, exports_dir=exports) == 0
    assert await db.chatmessages.count_documents({}) == 0
    assert await db.users.count_documents({"role": "admin"}) == 1
