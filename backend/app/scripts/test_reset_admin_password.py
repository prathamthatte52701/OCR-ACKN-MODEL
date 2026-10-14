from typing import Any

import pytest

from app.core.security import verify_password
from app.scripts import reset_admin_password as rap

NEW = "Nw8#kLp2!Tz9"


async def _user(db: Any, acct: Any) -> dict:
    u = await db.users.find_one({"_id": acct.id})
    assert u is not None
    return u


async def test_dry_run_changes_nothing(db: Any, make_user: Any) -> None:
    a = await make_user(role="admin")
    before = await _user(db, a)
    assert await rap.reset_admin_password(db, a.email, NEW) == a.email
    assert await _user(db, a) == before
    assert await db.auditlogs.count_documents({"action": rap.AUDIT_ACTION}) == 0


async def test_apply_sets_hash_bumps_token_version_and_audits(
    db: Any, client: Any, make_user: Any
) -> None:
    a = await make_user(role="admin")
    await rap.reset_admin_password(db, f"  {a.email.upper()} ", NEW, apply=True)
    u = await _user(db, a)
    assert verify_password(NEW, u["passwordHash"]) and u["tokenVersion"] == 1
    assert (
        await client.get("/api/auth/me", headers=a.headers)
    ).status_code == 401  # old token dead
    login = await client.post("/api/auth/login", json={"email": a.email, "password": NEW})
    assert login.status_code == 200
    log = await db.auditlogs.find_one({"action": rap.AUDIT_ACTION})
    assert log is not None and log["context"] == {"email": a.email}
    assert NEW not in str(log)


async def test_refusals(db: Any, make_user: Any) -> None:
    user = await make_user()
    google_admin = await make_user(role="admin", password=None)
    admin = await make_user(role="admin")
    for email, pw in [
        (user.email, NEW),  # non-admin
        (google_admin.email, NEW),  # Google-only
        ("nobody@looptest.local", NEW),  # unknown
        (admin.email, "weak"),  # weak password
        (admin.email, f"Zq9!{admin.username}!X"),  # contains username
    ]:
        with pytest.raises(rap.Refused):
            await rap.reset_admin_password(db, email, pw, apply=True)
    for a in (user, google_admin, admin):
        u = await _user(db, a)
        assert u["tokenVersion"] == 0
    assert "passwordHash" not in await _user(db, google_admin)
    assert verify_password(admin.password, (await _user(db, admin))["passwordHash"])


async def test_wrong_db_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["x", "--db", "some_other_db", "--email", "a@b.c", "--apply"])
    with pytest.raises(SystemExit) as exc:
        await rap.main()
    assert "Refusing" in str(exc.value)


async def test_main_password_mismatch_and_refusal_exit_nonzero(
    db: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings

    a = await make_user(role="admin")
    argv = ["x", "--db", settings.mongo_db_name, "--email", a.email, "--apply"]
    monkeypatch.setattr("sys.argv", argv)
    answers = iter([NEW, "different"])
    monkeypatch.setattr("getpass.getpass", lambda _p="": next(answers))
    with pytest.raises(SystemExit) as exc:
        await rap.main()
    assert "do not match" in str(exc.value)
    assert (await _user(db, a))["tokenVersion"] == 0
