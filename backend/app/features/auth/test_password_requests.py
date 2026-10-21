"""Admin-handled password reset: public request endpoint (generic reply, one open
request per user, rate limits). Written from the contract, before the implementation."""

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest

from app.core.rate_limit import limiter

URL = "/api/auth/password-reset-request"
GENERIC = {"message": "If this account exists, the admin has been told."}


def _rows(db: Any, **q: Any) -> Any:
    return db.passwordresetrequests.find(q).to_list(None)


@pytest.fixture
def limiter_on() -> Iterator[None]:
    old = limiter.enabled
    limiter.enabled = True
    limiter.reset()
    try:
        yield
    finally:
        limiter.reset()
        limiter.enabled = old


async def test_identical_response_for_every_case_and_no_rows_for_ineligible(
    client: Any, db: Any, make_user: Any
) -> None:
    pending = await make_user(status="pending")
    rejected = await make_user(status="rejected")
    admin = await make_user(role="admin")
    google = await make_user(password=None)
    valid = await make_user()
    cases = [
        "ghost-nobody@looptest.local",
        pending.email,
        rejected.email,
        admin.email,
        google.email,
        valid.email,
    ]
    resps = [await client.post(URL, json={"email": e, "note": "hi"}) for e in cases]
    for r in resps:
        assert r.status_code == 200
        assert r.json() == GENERIC
    assert len({len(r.content) for r in resps}) == 1
    assert len({r.text for r in resps}) == 1
    rows = await _rows(db)
    assert [r["userId"] for r in rows] == [valid.id]
    assert rows[0]["status"] == "open"
    assert rows[0]["email"] == valid.email
    assert rows[0]["username"] == valid.username


async def test_missing_status_user_is_eligible_and_email_is_normalized(
    client: Any, db: Any, make_user: Any
) -> None:
    legacy = await make_user(status=None)
    r = await client.post(URL, json={"email": f"  {legacy.email.upper()} "})
    assert r.status_code == 200 and r.json() == GENERIC
    assert len(await _rows(db, userId=legacy.id)) == 1


async def test_second_request_updates_same_row(client: Any, db: Any, make_user: Any) -> None:
    u = await make_user()
    await client.post(URL, json={"email": u.email, "note": "first"})
    first = (await _rows(db, userId=u.id))[0]
    await client.post(URL, json={"email": u.email, "note": "second"})
    rows = await _rows(db, userId=u.id)
    assert len(rows) == 1
    assert rows[0]["_id"] == first["_id"]
    assert rows[0]["note"] == "second"
    assert rows[0]["updatedAt"] >= first["updatedAt"]
    assert rows[0]["createdAt"] == first["createdAt"]


async def test_concurrent_requests_make_exactly_one_open_row(
    client: Any, db: Any, make_user: Any
) -> None:
    u = await make_user()
    rs = await asyncio.gather(
        *[client.post(URL, json={"email": u.email, "note": f"n{i}"}) for i in range(12)]
    )
    assert all(r.status_code == 200 and r.json() == GENERIC for r in rs)
    assert len(await _rows(db, userId=u.id, status="open")) == 1


async def test_new_open_row_after_previous_resolved(client: Any, db: Any, make_user: Any) -> None:
    u = await make_user()
    await client.post(URL, json={"email": u.email})
    await db.passwordresetrequests.update_many({}, {"$set": {"status": "dismissed"}})
    await client.post(URL, json={"email": u.email})
    assert len(await _rows(db, userId=u.id)) == 2
    assert len(await _rows(db, userId=u.id, status="open")) == 1


async def test_note_is_sanitized_and_limited(client: Any, db: Any, make_user: Any) -> None:
    u = await make_user()
    r = await client.post(
        URL, json={"email": u.email, "note": "  hello\x00\x07 wor\x1fld\x7f\n<b>x</b>  "}
    )
    assert r.status_code == 200
    note = (await _rows(db, userId=u.id))[0]["note"]
    assert note == note.strip()
    assert not any(ord(c) < 32 or ord(c) == 127 for c in note)
    assert "hello" in note and "wor" in note
    ok = await client.post(URL, json={"email": u.email, "note": "x" * 200})
    assert ok.status_code == 200
    assert len((await _rows(db, userId=u.id))[0]["note"]) == 200
    big = await client.post(URL, json={"email": u.email, "note": "x" * 201})
    assert big.status_code == 422
    assert len((await _rows(db, userId=u.id))[0]["note"]) == 200


async def test_missing_or_null_note_ok(client: Any, db: Any, make_user: Any) -> None:
    u = await make_user()
    assert (await client.post(URL, json={"email": u.email, "note": None})).status_code == 200
    assert len(await _rows(db, userId=u.id)) == 1


@pytest.mark.parametrize("bad", ["", "nope", "a@b", "x" * 260 + "@looptest.local", "a b@c.co"])
async def test_malformed_email_422(client: Any, bad: str) -> None:
    assert (await client.post(URL, json={"email": bad})).status_code == 422
    assert (await client.post(URL, json={})).status_code == 422


async def test_old_verify_and_reset_routes_gone(client: Any) -> None:
    for path in ("verify", "reset"):
        r = await client.post("/api/auth/" + "forgot" + f"-password/{path}", json={})
        assert r.status_code in (404, 405)


async def test_per_ip_limit_429_after_10(client: Any, limiter_on: None) -> None:
    codes = []
    for i in range(11):
        codes.append(
            (await client.post(URL, json={"email": f"ip{i}-nobody@looptest.local"})).status_code
        )
    assert codes[:10] == [200] * 10
    assert codes[10] == 429


async def test_per_email_limit_is_silent_and_independent_of_login(
    client: Any, db: Any, make_user: Any, limiter_on: None
) -> None:
    u = await make_user()
    last = None
    for i in range(6):  # under the 10/hour per-IP limit
        last = await client.post(URL, json={"email": u.email, "note": f"note{i}"})
        assert last.status_code == 200 and last.json() == GENERIC
    # the per-email limiter kicked in: later notes were ignored, still one row
    rows = await _rows(db, userId=u.id)
    assert len(rows) == 1
    assert rows[0]["note"] != "note5"
    # and it does not touch the login limiter for the same email
    login = await client.post("/api/auth/login", json={"email": u.email, "password": u.password})
    assert login.status_code == 200


async def test_per_email_limit_on_unknown_email_same_reply(client: Any, limiter_on: None) -> None:
    rs = [await client.post(URL, json={"email": "who-is-this@looptest.local"}) for _ in range(6)]
    assert {(r.status_code, r.text) for r in rs} == {(200, rs[0].text)}


async def test_audit_logged_without_note_and_no_row_for_ineligible_audit(
    client: Any, db: Any, make_user: Any
) -> None:
    u = await make_user()
    ghost = await make_user(status="pending")
    await client.post(URL, json={"email": u.email, "note": "SECRETNOTE-123"})
    await client.post(URL, json={"email": ghost.email, "note": "SECRETNOTE-456"})
    logs = await db.auditlogs.find({"action": "PASSWORD_RESET_REQUESTED"}).to_list(None)
    assert [x["userId"] for x in logs] == [u.id]
    assert "SECRETNOTE" not in str(await db.auditlogs.find({}).to_list(None))
