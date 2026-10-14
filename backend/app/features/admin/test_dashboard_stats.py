"""Admin dashboard numbers (GET /admin/telemetry): counts, pending list, activity feed, empty DB,
no sensitive fields, admin-only. Runs on the *_test database only (conftest.py)."""

import time
from datetime import UTC, datetime, timedelta
from typing import Any

from bson import ObjectId


async def _get(client: Any, admin: Any) -> Any:
    return await client.get("/api/admin/telemetry", headers=admin.headers)


def _doc(owner: Any, status: str = "processed", kind: str = "Tax Invoice", **extra: Any) -> dict:
    now = datetime.now(UTC)
    return {
        "userId": owner.id,
        "uploadStatus": status,
        "documentType": kind,
        "isDeleted": False,
        "createdAt": now,
        **extra,
    }


async def test_empty_database_returns_zeros_and_empty_lists(client: Any, make_user: Any) -> None:
    admin = await make_user(role="admin")
    r = await _get(client, admin)
    assert r.status_code == 200
    body = r.json()
    assert body["totalDocuments"] == 0 and body["totalExports"] == 0
    assert body["documentsByStatus"] == {"uploaded": 0, "processed": 0, "failed": 0}
    assert body["ocrFailureRate"] == 0 and body["failedDocuments"] == 0
    assert body["orphanedFiles"] == 0
    assert body["pendingUsers"] == {"count": 0, "oldest": []}
    assert body["trends"]["documents"] == {"current": 0, "previous": 0}
    assert isinstance(body["activityFeed"], list)


async def test_non_admin_and_anonymous_are_refused(client: Any, make_user: Any) -> None:
    user = await make_user()
    assert (await _get(client, user)).status_code == 403
    assert (await client.get("/api/admin/telemetry")).status_code == 401


async def test_counts_failed_orphaned_and_deleted_documents(
    client: Any, make_user: Any, db: Any
) -> None:
    admin, u = await make_user(role="admin"), await make_user()
    await db.documents.insert_many(
        [_doc(u), _doc(u), _doc(u, "failed", "Delivery Challan"), _doc(u, "uploaded")]
        + [_doc(u, "failed", isDeleted=True)]  # soft-deleted: never counted
    )
    await db.orphanedfiles.insert_many(
        [{"userId": u.id, "gridFsFileId": ObjectId()}, {"userId": u.id, "gridFsFileId": ObjectId()}]
    )
    await db.exportedrows.insert_one({"userId": u.id, "exportedAt": datetime.now(UTC)})
    body = (await _get(client, admin)).json()
    assert body["totalDocuments"] == 4
    assert body["documentsByStatus"] == {"uploaded": 1, "processed": 2, "failed": 1}
    assert body["documentsByType"] == {"Tax Invoice": 3, "Delivery Challan": 1}
    assert body["failedDocuments"] == 1 and body["orphanedFiles"] == 2
    assert body["totalExports"] == 1
    assert body["ocrFailureRate"] == 33.3  # 1 failed of 3 finished


async def test_pending_list_has_only_pending_users_oldest_first_max_five(
    client: Any, make_user: Any, db: Any
) -> None:
    admin = await make_user(role="admin")
    await make_user(status="approved")
    await make_user(status="rejected")
    pending = [await make_user(status="pending") for _ in range(7)]
    now = datetime.now(UTC)
    for i, p in enumerate(pending):  # pending[0] is the OLDEST
        await db.users.update_one(
            {"_id": p.id}, {"$set": {"createdAt": now - timedelta(days=10 - i)}}
        )
    body = (await _get(client, admin)).json()["pendingUsers"]
    assert body["count"] == 7 and len(body["oldest"]) == 5
    assert [x["id"] for x in body["oldest"]] == [str(p.id) for p in pending[:5]]
    assert all(set(x) == {"id", "username", "email", "createdAt"} for x in body["oldest"])


async def test_feed_has_at_most_ten_items_with_correct_usernames_and_groups(
    client: Any, make_user: Any, db: Any
) -> None:
    admin = await make_user(role="admin")
    a, b = await make_user(username="alice"), await make_user(username="bobby")
    now = datetime.now(UTC)
    events = []
    for i in range(3):  # three saves by alice within minutes -> ONE grouped item with count 3
        events.append(
            {
                "userId": a.id,
                "action": "document_exported",
                "context": {},
                "createdAt": now - timedelta(seconds=i),
            }
        )
    events.append(
        {"userId": b.id, "action": "login", "context": {}, "createdAt": now - timedelta(minutes=1)}
    )
    for i in range(30):  # plenty more, to prove the cap
        events.append(
            {
                "userId": b.id if i % 2 else a.id,
                "action": f"act_{i}",
                "context": {},
                "createdAt": now - timedelta(hours=1, seconds=i),
            }
        )
    await db.auditlogs.insert_many(events)
    feed = (await _get(client, admin)).json()["activityFeed"]
    assert len(feed) == 10
    assert feed[0]["action"] == "document_exported" and feed[0]["count"] == 3
    assert feed[0]["user"]["username"] == "alice" and feed[1]["user"]["username"] == "bobby"
    assert feed[1]["action"] == "login"


async def test_feed_exposes_no_sensitive_fields(client: Any, make_user: Any, db: Any) -> None:
    admin, u = await make_user(role="admin"), await make_user()
    await db.auditlogs.insert_one(
        {
            "userId": u.id,
            "action": "user_approved",
            "context": {
                "targetEmail": "x@y.co",
                "passwordHash": "SECRET",
                "token": "TOK",
                "targetUserId": "1",
            },
            "createdAt": datetime.now(UTC),
        }
    )
    r = await _get(client, admin)
    text = r.text
    assert "SECRET" not in text and "TOK" not in text and "passwordHash" not in text
    item = r.json()["activityFeed"][0]
    assert set(item) == {"id", "action", "createdAt", "user", "targetEmail", "count"}
    assert set(item["user"]) == {"id", "username"} and item["targetEmail"] == "x@y.co"


async def test_feed_survives_deleted_user_and_odd_context(
    client: Any, make_user: Any, db: Any
) -> None:
    admin = await make_user(role="admin")
    await db.auditlogs.insert_many(
        [
            {
                "userId": ObjectId(),
                "action": "login",
                "context": "not-a-dict",
                "createdAt": datetime.now(UTC),
            },
            {
                "userId": ObjectId(),
                "action": "x",
                "context": {"targetEmail": 123},
                "createdAt": datetime.now(UTC),
            },
        ]
    )
    feed = (await _get(client, admin)).json()["activityFeed"]
    assert len(feed) == 2 and all(i["user"] is None and i["targetEmail"] is None for i in feed)


async def test_trends_compare_this_week_with_the_week_before(
    client: Any, make_user: Any, db: Any
) -> None:
    admin, u = await make_user(role="admin"), await make_user()
    now = datetime.now(UTC)
    await db.documents.insert_many(
        [_doc(u, createdAt=now - timedelta(days=1)) for _ in range(3)]
        + [_doc(u, createdAt=now - timedelta(days=9)) for _ in range(2)]
        + [_doc(u, createdAt=now - timedelta(days=30))]
    )
    t = (await _get(client, admin)).json()["trends"]["documents"]
    assert t == {"current": 3, "previous": 2}


async def test_dashboard_is_fast_with_5000_documents_and_500_users(
    client: Any, make_user: Any, db: Any
) -> None:
    admin, owner = await make_user(role="admin"), await make_user()
    now = datetime.now(UTC)
    await db.users.insert_many(
        [
            {
                "username": f"p{i}",
                "email": f"p{i}@looptest.local",
                "role": "user",
                "status": "pending" if i % 5 == 0 else "approved",
                "tokenVersion": 0,
                "createdAt": now - timedelta(minutes=i),
            }
            for i in range(500)
        ]
    )
    await db.documents.insert_many(
        [
            _doc(
                owner,
                ["processed", "failed", "uploaded"][i % 3],
                ["Tax Invoice", "Delivery Challan"][i % 2],
            )
            for i in range(5000)
        ]
    )
    await db.auditlogs.insert_many(
        [
            {
                "userId": owner.id,
                "action": "login",
                "context": {},
                "createdAt": now - timedelta(seconds=i),
            }
            for i in range(500)
        ]
    )
    t0 = time.perf_counter()
    r = await _get(client, admin)
    elapsed = time.perf_counter() - t0
    assert r.status_code == 200 and r.json()["totalDocuments"] == 5000
    assert r.json()["pendingUsers"]["count"] == 100
    print(f"\ndashboard with 5000 docs / 500 users: {elapsed * 1000:.0f} ms")
    assert elapsed < 5.0


async def test_feed_leaves_out_admin_access_noise(client: Any, make_user: Any, db: Any) -> None:
    admin = await make_user(role="admin")
    now = datetime.now(UTC)
    await db.auditlogs.insert_many(
        [
            {"userId": admin.id, "action": "admin_access", "context": {}, "createdAt": now},
            {
                "userId": admin.id,
                "action": "login",
                "context": {},
                "createdAt": now - timedelta(minutes=5),
            },
        ]
    )
    feed = (await _get(client, admin)).json()["activityFeed"]
    assert [i["action"] for i in feed] == ["login"]
