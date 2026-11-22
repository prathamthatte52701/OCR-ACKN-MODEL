"""Every paged list accepts the four page sizes the UI offers (30, 50, 75, 100).

One test per route, 230+ rows each: page 1 holds exactly `limit` rows, totalPages is
ceil(total / limit), the last page holds the remainder, limit=0 falls back to the default of 30,
and a huge limit behaves as it does today (user routes cap at 100; the admin routes have no cap).
"""

import math
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from bson import ObjectId

SIZES = (30, 50, 75, 100)
ROWS = 230


def _now(i: int = 0) -> datetime:
    return datetime.now(UTC) - timedelta(seconds=i)


async def _check_sizes(
    client: Any,
    headers: dict,
    url: str,
    rows_key: str,
    total_key: str,
    *,
    params: dict | None = None,
    min_total: int = ROWS,
    capped_at: int | None = 100,
) -> None:
    base = dict(params or {})

    async def get(**extra: Any) -> dict:
        res = await client.get(url, headers=headers, params={**base, **extra})
        assert res.status_code == 200, res.text
        body: dict = res.json()
        return body

    total = None
    for lim in SIZES:
        first = await get(page=1, limit=lim)
        total = first[total_key]
        assert total >= min_total
        pages = math.ceil(total / lim)
        assert len(first[rows_key]) == lim
        assert first["totalPages"] == pages
        assert first["currentPage"] == 1
        last = await get(page=pages, limit=lim)
        assert len(last[rows_key]) == total - (pages - 1) * lim
        assert last["currentPage"] == pages
    assert total is not None
    # 230 rows / 75 per page = 4 pages (the spec's example), when exactly 230 rows exist
    if total == ROWS:
        assert math.ceil(total / 75) == 4
    # limit=0 and no limit both mean the default of 30
    assert len((await get(page=1, limit=0))[rows_key]) == 30
    assert len((await get(page=1))[rows_key]) == 30
    # a huge limit: user routes cap at 100, the admin routes have no cap today (kept as is)
    huge = await get(page=1, limit=1000)
    assert len(huge[rows_key]) == (capped_at if capped_at else total)
    # a page past the end never errors
    past = await client.get(url, headers=headers, params={**base, "page": 999, "limit": 100})
    assert past.status_code == 200, past.text
    assert len(past.json()[rows_key]) == 0 or past.json()["currentPage"] <= 999


async def test_user_documents_list_accepts_all_sizes(client: Any, db: Any, make_user: Any) -> None:
    a = await make_user()
    await db.documents.insert_many(
        [
            {
                "userId": a.id,
                "documentType": "Delivery Challan",
                "originalFilename": f"f{i}.pdf",
                "mimeType": "application/pdf",
                "uploadStatus": "processed",
                "number": f"8203{i:05d}",
                "date": "01/01/2026",
                "createdAt": _now(i),
                "updatedAt": _now(i),
            }
            for i in range(ROWS)
        ]
    )
    await _check_sizes(
        client, a.headers, "/api/documents", "documents", "totalDocuments", min_total=ROWS
    )


async def test_my_activity_accepts_all_sizes(client: Any, db: Any, make_user: Any) -> None:
    a = await make_user()
    await db.auditlogs.insert_many(
        [
            {"userId": a.id, "action": "document_uploaded", "context": {}, "createdAt": _now(i)}
            for i in range(ROWS)
        ]
    )
    await _check_sizes(client, a.headers, "/api/documents/my-activity", "activity", "totalActivity")


async def test_export_history_accepts_all_sizes(client: Any, db: Any, make_user: Any) -> None:
    a = await make_user()
    await db.exportedrows.insert_many(
        [
            {
                "userId": a.id,
                "documentId": ObjectId(),
                "workbookId": None,
                "documentType": "Delivery Challan",
                "number": f"8203{i:05d}",
                "date": "01/01/2026",
                "exportedAt": _now(i),
                "createdAt": _now(i),
                "updatedAt": _now(i),
            }
            for i in range(ROWS)
        ]
    )
    await _check_sizes(
        client, a.headers, "/api/documents/export-history", "exports", "totalExports"
    )


async def test_admin_users_accepts_all_sizes(client: Any, db: Any, make_user: Any) -> None:
    admin = await make_user(role="admin")
    await db.users.insert_many(
        [
            {
                "username": f"x{i}",
                "email": f"bulk{i}-{ObjectId()}@looptest.local",
                "role": "user",
                "status": "approved",
                "tokenVersion": 0,
                "createdAt": _now(i),
                "updatedAt": _now(i),
            }
            for i in range(ROWS)
        ]
    )
    await _check_sizes(
        client, admin.headers, "/api/admin/users", "users", "totalUsers", capped_at=None
    )


async def test_admin_documents_accepts_all_sizes(client: Any, db: Any, make_user: Any) -> None:
    admin = await make_user(role="admin")
    owner = await make_user()
    await db.documents.insert_many(
        [
            {
                "userId": owner.id,
                "documentType": "Tax Invoice",
                "originalFilename": f"f{i}.pdf",
                "mimeType": "application/pdf",
                "uploadStatus": "processed",
                "taxInvoiceNo": f"G00277{i:05d}",
                "date": "01/01/2026",
                "createdAt": _now(i),
                "updatedAt": _now(i),
            }
            for i in range(ROWS)
        ]
    )
    await _check_sizes(
        client,
        admin.headers,
        "/api/admin/documents",
        "documents",
        "totalDocuments",
        capped_at=None,
    )
    # the same list scoped to one user (the user-detail "Documents" section)
    await _check_sizes(
        client,
        admin.headers,
        "/api/admin/documents",
        "documents",
        "totalDocuments",
        params={"userId": str(owner.id)},
        capped_at=None,
    )


async def test_admin_logs_accepts_all_sizes(client: Any, db: Any, make_user: Any) -> None:
    admin = await make_user(role="admin")
    owner = await make_user()
    await db.auditlogs.insert_many(
        [
            {"userId": owner.id, "action": "document_uploaded", "context": {}, "createdAt": _now(i)}
            for i in range(ROWS)
        ]
    )
    await _check_sizes(
        client, admin.headers, "/api/admin/logs", "logs", "totalLogs", capped_at=None
    )
    await _check_sizes(
        client,
        admin.headers,
        "/api/admin/logs",
        "logs",
        "totalLogs",
        params={"userId": str(owner.id)},
        capped_at=None,
    )


async def test_admin_exports_accepts_all_sizes(client: Any, db: Any, make_user: Any) -> None:
    admin = await make_user(role="admin")
    owner = await make_user()
    await db.exportedrows.insert_many(
        [
            {
                "userId": owner.id,
                "documentId": ObjectId(),
                "workbookId": None,
                "documentType": "Delivery Challan",
                "number": f"8203{i:05d}",
                "date": "01/01/2026",
                "exportedAt": _now(i),
                "createdAt": _now(i),
                "updatedAt": _now(i),
            }
            for i in range(ROWS)
        ]
    )
    await _check_sizes(
        client,
        admin.headers,
        "/api/admin/exports",
        "exports",
        "totalExports",
        params={"userId": str(owner.id)},
        capped_at=None,
    )


async def test_admin_orphaned_files_accepts_all_sizes(client: Any, db: Any, make_user: Any) -> None:
    admin = await make_user(role="admin")
    await db.orphanedfiles.insert_many(
        [
            {
                "gridFsFileId": ObjectId(),
                "userId": None,
                "context": "test",
                "errorType": "TestError",
                "errorMessage": "x",
                "attemptCount": 1,
                "createdAt": _now(i),
                "updatedAt": _now(i),
            }
            for i in range(ROWS)
        ]
    )
    await _check_sizes(
        client,
        admin.headers,
        "/api/admin/orphaned-files",
        "orphanedFiles",
        "totalOrphanedFiles",
        capped_at=None,
    )


@pytest.mark.parametrize("bad", ["abc", "1.5", ""])
async def test_non_numeric_limit_is_a_clean_422(client: Any, make_user: Any, bad: str) -> None:
    a = await make_user()
    res = await client.get(
        "/api/documents/my-activity", headers=a.headers, params={"page": 1, "limit": bad}
    )
    assert res.status_code == 422
