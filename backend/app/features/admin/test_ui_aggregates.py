"""Read-only aggregates for the admin UI: telemetry series/processed/maintenance, users list
q/role/statusCounts/documentCount, user detail, /admin/system. *_test database only."""

import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from bson import ObjectId

import app.features.excel.service as excel_service


async def _tele(client: Any, admin: Any) -> dict:
    r = await client.get("/api/admin/telemetry", headers=admin.headers)
    assert r.status_code == 200
    return r.json()


def _doc(owner_id: Any, **extra: Any) -> dict:
    return {
        "userId": owner_id,
        "uploadStatus": "processed",
        "documentType": "Tax Invoice",
        "isDeleted": False,
        "createdAt": datetime.now(UTC),
        **extra,
    }


async def test_series_has_30_days_ending_today_with_correct_counts(
    client: Any, make_user: Any, db: Any
) -> None:
    admin = await make_user(role="admin")  # created today
    u = await make_user()  # created today
    now = datetime.now(UTC)
    # Noon of the target day keeps this independent of the time the test runs.
    noon = now.replace(hour=12, minute=0, second=0, microsecond=0)
    await db.documents.insert_many(
        [_doc(u.id, createdAt=noon - timedelta(days=3)) for _ in range(2)]
        + [_doc(u.id, createdAt=noon - timedelta(days=29))]
        + [_doc(u.id, createdAt=noon - timedelta(days=30))]  # outside the window
        + [_doc(u.id, createdAt=noon - timedelta(days=3), isDeleted=True)]  # deleted: ignored
    )
    await db.exportedrows.insert_many(
        [{"userId": u.id, "exportedAt": noon - timedelta(days=1)} for _ in range(4)]
    )
    s = (await _tele(client, admin))["series"]
    today = now.date()
    assert len(s["days"]) == 30 and s["days"][-1] == today.isoformat()
    assert s["days"][0] == (today - timedelta(days=29)).isoformat()
    assert s["days"] == sorted(s["days"])
    assert all(len(s[k]) == 30 for k in ("users", "documents", "exports"))
    assert s["users"][-1] == 2 and sum(s["users"]) == 2
    assert s["documents"][-4] == 2 and s["documents"][0] == 1 and sum(s["documents"]) == 3
    assert s["exports"][-2] == 4 and sum(s["exports"]) == 4


async def test_processed_documents_totals_and_windows(client: Any, make_user: Any, db: Any) -> None:
    admin, u = await make_user(role="admin"), await make_user()
    now = datetime.now(UTC)
    await db.documents.insert_many(
        [_doc(u.id, processedAt=now - timedelta(days=1)) for _ in range(3)]
        + [_doc(u.id, processedAt=now - timedelta(days=9)) for _ in range(2)]
        + [_doc(u.id, processedAt=now - timedelta(days=40))]
        + [_doc(u.id, uploadStatus="failed", processedAt=now - timedelta(days=1))]
        + [_doc(u.id, processedAt=now - timedelta(days=1), isDeleted=True)]
    )
    assert (await _tele(client, admin))["processedDocuments"] == {
        "total": 6,
        "current": 3,
        "previous": 2,
    }


async def test_recent_maintenance_whitelist_max_five_names_no_context(
    client: Any, make_user: Any, db: Any
) -> None:
    admin = await make_user(role="admin")
    bob = await make_user(username="bobby")
    now = datetime.now(UTC)
    events = [
        {
            "userId": admin.id if i % 2 else bob.id,
            "action": "admin_nuke_user_range_data",
            "context": {"secret": "SHHH", "targetEmail": "x@y.co"},
            "createdAt": now - timedelta(minutes=i),
        }
        for i in range(1, 8)
    ]
    events.append(  # newest of all, whitelisted, user no longer exists
        {
            "userId": ObjectId(),
            "action": "user_deleted",
            "context": {"secret": "SHHH"},
            "createdAt": now,
        }
    )
    events += [  # not whitelisted, even though newer
        {"userId": bob.id, "action": a, "context": {}, "createdAt": now + timedelta(minutes=1)}
        for a in ("login", "document_exported", "admin_nuke_user_range_attempted")
    ]
    await db.auditlogs.insert_many(events)
    r = await client.get("/api/admin/telemetry", headers=admin.headers)
    items = r.json()["recentMaintenance"]
    assert len(items) == 5
    assert items[0]["action"] == "user_deleted" and items[0]["user"] is None
    assert {i["action"] for i in items[1:]} == {"admin_nuke_user_range_data"}
    assert items[1]["user"] == {"id": str(admin.id), "username": admin.username}  # i == 1
    assert items[2]["user"] == {"id": str(bob.id), "username": "bobby"}  # i == 2
    for it in items:
        assert set(it) == {"id", "action", "createdAt", "user"}
    # (activityFeed legitimately shows targetEmail; only recentMaintenance must be clean)
    assert "SHHH" not in str(items) and "x@y.co" not in str(items)


async def test_users_q_role_and_literal_regex(client: Any, make_user: Any) -> None:
    admin = await make_user(role="admin", username="root", email="root@corp.test")
    await make_user(username="Alice", email="alice@looptest.local")
    await make_user(username="bobby", email="Zed.Person@Example.com")
    await make_user(username="a.b", email="dotted@looptest.local")
    await make_user(username="axb", email="other@looptest.local")

    async def names(**params: Any) -> list[str]:
        r = await client.get("/api/admin/users", params=params, headers=admin.headers)
        assert r.status_code == 200
        return sorted(u["username"] for u in r.json()["users"])

    assert await names(q="ALICE") == ["Alice"]  # username, case-insensitive
    assert await names(q="zed.person@EXAMPLE") == ["bobby"]  # email, case-insensitive
    assert await names(q="a.b") == ["a.b"]  # "." is literal, not "any char" (would match axb)
    assert await names(q=".*") == []  # literal, not match-everything
    assert await names(role="admin") == ["root"]
    assert await names(role="user", q="looptest") == ["Alice", "a.b", "axb"]
    r = await client.get("/api/admin/users", params={"q": "x" * 100}, headers=admin.headers)
    assert r.status_code == 200
    r = await client.get("/api/admin/users", params={"q": "x" * 101}, headers=admin.headers)
    assert r.status_code == 422
    r = await client.get("/api/admin/users", params={"role": "boss"}, headers=admin.headers)
    assert r.status_code == 422


async def test_status_counts_cover_all_users_incl_legacy_and_ignore_filters(
    client: Any, make_user: Any, db: Any
) -> None:
    admin = await make_user(role="admin")  # approved
    await make_user(status="approved")
    await make_user(status="pending")
    await make_user(status="pending")
    await make_user(status="rejected")
    await make_user(status=None)  # legacy: no status field -> approved
    expected = {"total": 6, "approved": 3, "pending": 2, "rejected": 1}
    for params in ({}, {"status": "pending"}, {"role": "admin"}, {"q": "nomatchatall"}):
        body = (await client.get("/api/admin/users", params=params, headers=admin.headers)).json()
        assert body["statusCounts"] == expected, params
        assert body["pendingCount"] == 2
    legacy = (await client.get("/api/admin/users", headers=admin.headers)).json()["users"]
    assert all("documentCount" in u for u in legacy)


async def test_document_count_per_user_excludes_deleted_and_other_users(
    client: Any, make_user: Any, db: Any
) -> None:
    admin, a, b, c = [await make_user(role="admin")] + [await make_user() for _ in range(3)]
    await db.documents.insert_many(
        [_doc(a.id) for _ in range(3)]
        + [_doc(a.id, isDeleted=True)]
        + [_doc(a.id, isDeleted=None)]  # not literally True -> counts
        + [_doc(b.id)]
    )
    users = {
        u["id"]: u
        for u in (await client.get("/api/admin/users", headers=admin.headers)).json()["users"]
    }
    assert users[str(a.id)]["documentCount"] == 4
    assert users[str(b.id)]["documentCount"] == 1
    assert users[str(c.id)]["documentCount"] == 0
    assert users[str(admin.id)]["documentCount"] == 0
    assert "status" in users[str(a.id)] and "createdAt" in users[str(a.id)]  # existing fields kept


async def test_get_user_has_document_count_and_last_active(
    client: Any, make_user: Any, db: Any
) -> None:
    admin, u = await make_user(role="admin"), await make_user()
    r = await client.get(f"/api/admin/users/{u.id}", headers=admin.headers)
    user = r.json()["user"]
    assert user["documentCount"] == 0 and user["lastActiveAt"] is None
    now = datetime.now(UTC)
    await db.documents.insert_many([_doc(u.id), _doc(u.id), _doc(u.id, isDeleted=True)])
    await db.auditlogs.insert_many(
        [
            {"userId": u.id, "action": "login", "createdAt": now - timedelta(days=2)},
            {"userId": u.id, "action": "login", "createdAt": now - timedelta(hours=1)},
            {"userId": admin.id, "action": "login", "createdAt": now},  # someone else's event
        ]
    )
    user = (await client.get(f"/api/admin/users/{u.id}", headers=admin.headers)).json()["user"]
    assert user["documentCount"] == 2 and user["username"] == u.username
    last = datetime.fromisoformat(user["lastActiveAt"])
    assert abs((last.replace(tzinfo=UTC) - (now - timedelta(hours=1))).total_seconds()) < 2


async def test_system_shape_and_storage(
    client: Any, make_user: Any, db: Any, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = await make_user(role="admin")
    await db["fs.files"].insert_many(
        [{"filename": "a", "length": 1000}, {"filename": "b", "length": 234}]
    )
    (tmp_path / "a.xlsx").write_bytes(b"x" * 100)
    (tmp_path / "c.xlsx").write_bytes(b"x" * 50)
    (tmp_path / "a.xlsx.lock").write_bytes(b"x" * 999)
    (tmp_path / "b.tmp123.xlsx").write_bytes(b"x" * 999)
    monkeypatch.setattr(excel_service, "EXPORT_DIR", tmp_path)
    r = await client.get("/api/admin/system", headers=admin.headers)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {
        "db",
        "ocrLockWedged",
        "serverStartedAt",
        "uptimeSeconds",
        "storage",
        "checkedAt",
    }
    assert body["db"]["ok"] is True and isinstance(body["db"]["pingMs"], int)
    assert body["ocrLockWedged"] is False
    assert body["uptimeSeconds"] >= 0
    datetime.fromisoformat(body["serverStartedAt"])
    datetime.fromisoformat(body["checkedAt"])
    assert body["storage"] == {
        "documentFiles": {"bytes": 1234, "count": 2},
        "workbookFiles": {"bytes": 150, "count": 2},
    }


async def test_system_zero_storage_and_missing_dir_and_failed_ping(
    client: Any, make_user: Any, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = await make_user(role="admin")
    monkeypatch.setattr(excel_service, "EXPORT_DIR", tmp_path / "does-not-exist")
    body = (await client.get("/api/admin/system", headers=admin.headers)).json()
    assert body["storage"] == {
        "documentFiles": {"bytes": 0, "count": 0},
        "workbookFiles": {"bytes": 0, "count": 0},
    }

    class _Boom:
        async def command(self, *_a: Any, **_k: Any) -> None:
            raise RuntimeError("down")

        def __getitem__(self, _name: str) -> Any:
            raise RuntimeError("down")

    import app.features.admin.router as admin_router

    monkeypatch.setattr(admin_router, "get_database", lambda: _Boom())
    r = await client.get("/api/admin/system", headers=admin.headers)
    assert r.status_code == 200
    assert r.json()["db"]["ok"] is False
    assert r.json()["storage"]["documentFiles"] == {"bytes": 0, "count": 0}


async def test_admin_only_endpoints(client: Any, make_user: Any) -> None:
    user = await make_user()
    for path in ("/api/admin/system", "/api/admin/telemetry"):
        assert (await client.get(path, headers=user.headers)).status_code == 403
        assert (await client.get(path)).status_code == 401


async def test_empty_database_new_fields_are_zeros(client: Any, make_user: Any) -> None:
    admin = await make_user(role="admin")
    t = await _tele(client, admin)
    assert t["series"]["users"][-1] == 1  # the admin created just now
    assert sum(t["series"]["documents"]) == 0 and sum(t["series"]["exports"]) == 0
    assert t["processedDocuments"] == {"total": 0, "current": 0, "previous": 0}
    assert t["recentMaintenance"] == []
    users = (await client.get("/api/admin/users", headers=admin.headers)).json()
    assert users["statusCounts"] == {"total": 1, "approved": 1, "pending": 0, "rejected": 0}
    sysbody = (await client.get("/api/admin/system", headers=admin.headers)).json()
    assert sysbody["storage"]["documentFiles"] == {"bytes": 0, "count": 0}


async def test_telemetry_and_users_fast_with_5000_documents_and_500_users(
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
            _doc(owner.id, createdAt=now - timedelta(hours=i), processedAt=now - timedelta(hours=i))
            for i in range(5000)
        ]
    )
    for path in ("/api/admin/telemetry", "/api/admin/users?limit=30"):
        t0 = time.perf_counter()
        r = await client.get(path, headers=admin.headers)
        assert r.status_code == 200
        assert time.perf_counter() - t0 < 5, path
