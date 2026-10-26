"""A failing audit write must not turn a successful delete (or a refusal) into an error."""

from typing import Any

import pytest

from app.core import audit_log
from app.features.chat.chat_testkit import BASE, seed


@pytest.fixture
def audit_down(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("audit store down")

    monkeypatch.setattr(audit_log, "log_action", boom)
    # the router must not hold its own reference to the raw writer
    import app.features.chat.router as router

    if hasattr(router, "log_action"):
        monkeypatch.setattr(router, "log_action", boom)


async def test_clear_survives_audit_failure(
    client: Any, make_user: Any, db: Any, audit_down: None
) -> None:
    u, a = await make_user(), await make_user(role="admin")
    await seed(db, u, "m1")
    await seed(db, u, "m2", sender=a, role="admin")
    r = await client.post(
        f"{BASE}/clear",
        headers=a.headers,
        json={"userId": str(u.id), "olderThan": "all", "confirm": "DELETE"},
    )
    assert r.status_code == 200 and r.json() == {"deleted": 2}
    assert await db.chatmessages.count_documents({}) == 0


async def test_clear_all_survives_audit_failure(
    client: Any, make_user: Any, db: Any, audit_down: None
) -> None:
    u, a = await make_user(), await make_user(role="admin")
    await seed(db, u, "m1")
    r = await client.post(
        f"{BASE}/clear-all", headers=a.headers, json={"password": a.password, "confirm": "DELETE"}
    )
    assert r.status_code == 200 and r.json() == {"deleted": 1}
    assert await db.chatmessages.count_documents({}) == 0


async def test_wrong_password_still_400_when_audit_fails(
    client: Any, make_user: Any, db: Any, audit_down: None
) -> None:
    u, a = await make_user(), await make_user(role="admin")
    await seed(db, u, "keep")
    r = await client.post(
        f"{BASE}/clear-all", headers=a.headers, json={"password": "nope", "confirm": "DELETE"}
    )
    assert r.status_code == 400 and r.json()["detail"] == "Incorrect password."
    assert await db.chatmessages.count_documents({}) == 1
