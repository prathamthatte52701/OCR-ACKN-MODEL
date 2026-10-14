"""One admin must never change, reject, delete or purge ANOTHER admin (403, nothing written, no file
touched). Self-service and regular-user management keep working. Runs on the *_test DB only."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from app.features.documents.gridfs_service import download_buffer, upload_buffer

MSG = "Admin accounts can only be changed by that admin."


async def _victim(db: Any, make_user: Any) -> tuple[Any, Any, Any]:
    """(acting admin, victim admin, victim's GridFS file id) - victim owns one old document."""
    a, b = await make_user(role="admin"), await make_user(role="admin")
    file_id = await upload_buffer(b"victim-bytes", "v.png", "image/png")
    await db.documents.insert_one(
        {
            "userId": b.id,
            "documentType": "Delivery Challan",
            "uploadStatus": "processed",
            "number": "820762791",
            "date": "10/01/2020",
            "gridFsFileId": file_id,
            "isDeleted": False,
            "createdAt": datetime.now(UTC) - timedelta(days=900),
        }
    )
    return a, b, file_id


async def _snapshot(db: Any, user_id: Any, file_id: Any) -> tuple[Any, int, bytes]:
    return (
        await db.users.find_one({"_id": user_id}),
        await db.documents.count_documents({"userId": user_id}),
        await download_buffer(file_id),
    )


def _purge_range(a: Any) -> dict[str, Any]:
    return {
        "olderThanMonths": 1,
        "password": a.password,
        "confirmPassword": a.password,
        "confirmationPhrase": "NUKE USER",
    }


def _purge_months(a: Any) -> dict[str, Any]:
    return {
        "year": 2020,
        "months": [1],
        "password": a.password,
        "confirmPassword": a.password,
        "confirmationPhrase": "NUKE USER MONTHS",
    }


def _calls(a: Any, b: Any) -> list[tuple[str, str, Any]]:
    uid = f"/api/admin/users/{b.id}"
    return [
        ("DELETE", uid, None),
        ("PATCH", uid, {"username": "hijacked"}),
        ("PATCH", uid, {"email": "hijack@looptest.local"}),
        ("PATCH", uid, {"role": "user"}),
        ("PATCH", uid, {"role": "user", "username": "harmless"}),  # mixed-field bypass attempt
        ("PUT", f"{uid}/email", {"email": "hijack2@looptest.local"}),
        ("POST", f"{uid}/reject", {"reason": "x"}),
        ("POST", f"{uid}/reject", None),
        ("POST", f"{uid}/approve", None),
        ("DELETE", f"{uid}/purge-range", _purge_range(a)),
        ("DELETE", f"{uid}/purge-months", _purge_months(a)),
    ]


async def _send(client: Any, a: Any, method: str, url: str, body: Any) -> Any:
    kwargs: dict[str, Any] = {"headers": a.headers}
    if body is not None:
        kwargs["json"] = body
    return await client.request(method, url, **kwargs)


async def test_admin_cannot_touch_another_admin_anywhere(
    client: Any, make_user: Any, db: Any
) -> None:
    a, b, file_id = await _victim(db, make_user)
    before = await _snapshot(db, b.id, file_id)
    for method, url, body in _calls(a, b):
        r = await _send(client, a, method, url, body)
        assert r.status_code == 403, (method, url, body, r.status_code, r.text)
        assert r.json()["detail"] == MSG
    assert await _snapshot(db, b.id, file_id) == before  # user doc, documents, GridFS intact
    assert (await client.get("/api/auth/me", headers=b.headers)).status_code == 200
    assert await db.auditlogs.count_documents({"action": "user_deleted"}) == 0


async def test_concurrent_requests_cannot_bypass_the_check(
    client: Any, make_user: Any, db: Any
) -> None:
    a, b, file_id = await _victim(db, make_user)
    before = await _snapshot(db, b.id, file_id)
    calls = _calls(a, b) * 3
    results = await asyncio.gather(*(_send(client, a, m, u, body) for m, u, body in calls))
    assert {r.status_code for r in results} == {403}
    assert await _snapshot(db, b.id, file_id) == before


async def test_admin_still_manages_regular_users(client: Any, make_user: Any, db: Any) -> None:
    a = await make_user(role="admin")
    u = await make_user(status="pending")
    uid = f"/api/admin/users/{u.id}"
    assert (await _send(client, a, "POST", f"{uid}/approve", None)).status_code == 200
    r = await _send(client, a, "PATCH", uid, {"username": "renamed1"})
    assert r.status_code == 200 and r.json()["user"]["username"] == "renamed1"
    r = await _send(client, a, "PUT", f"{uid}/email", {"email": "new1@looptest.local"})
    assert r.status_code == 200
    r = await _send(client, a, "POST", f"{uid}/reject", {"reason": "x"})
    assert r.status_code == 200
    r = await _send(client, a, "DELETE", f"{uid}/purge-range", _purge_range(a))
    assert r.status_code == 200
    assert (await _send(client, a, "DELETE", uid, None)).status_code == 200
    assert await db.users.find_one({"_id": u.id}) is None
    # promoting a regular user works; once they are an admin only they can change themselves
    v = await make_user()
    vid = f"/api/admin/users/{v.id}"
    assert (await _send(client, a, "PATCH", vid, {"role": "admin"})).status_code == 200
    assert (await _send(client, a, "PATCH", vid, {"role": "user"})).status_code == 403


async def test_admin_can_edit_self_but_not_demote_or_delete_self(
    client: Any, make_user: Any
) -> None:
    a = await make_user(role="admin")
    await make_user(role="admin")  # so the last-admin guard is not what answers
    url = f"/api/admin/users/{a.id}"
    r = await _send(client, a, "PATCH", url, {"username": "myself1"})
    assert r.status_code == 200 and r.json()["user"]["username"] == "myself1"
    assert (await _send(client, a, "PATCH", url, {"role": "user"})).status_code == 400
    assert (await _send(client, a, "DELETE", url, None)).status_code == 400


async def test_non_admin_and_bad_ids_keep_their_usual_errors(client: Any, make_user: Any) -> None:
    user, b = await make_user(), await make_user(role="admin")
    for method, url, body in _calls(user, b):
        assert (await _send(client, user, method, url, body)).status_code == 403
    a = await make_user(role="admin")
    assert (await _send(client, a, "DELETE", "/api/admin/users/not-an-id", None)).status_code == 400
    missing = "64b7f0f0f0f0f0f0f0f0f0f0"
    r = await _send(client, a, "DELETE", f"/api/admin/users/{missing}", None)
    assert r.status_code == 404
    r = await _send(client, a, "POST", f"/api/admin/users/{missing}/approve", None)
    assert r.status_code == 404
