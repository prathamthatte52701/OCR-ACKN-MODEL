"""T8: every admin route that opens/lists/downloads another user's data writes
an audit entry (adminId, targetUserId, resource, action, time)."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import openpyxl
import pytest
from bson import ObjectId

from app.features.excel import service as excel_service


@pytest.fixture
def exports_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(excel_service, "EXPORT_DIR", tmp_path)
    return tmp_path


async def _entries(db: Any) -> list[dict[str, Any]]:
    return [e async for e in db.auditlogs.find({"action": "admin_access"})]


async def test_admin_list_documents_is_audited(client: Any, db: Any, make_user: Any) -> None:
    admin = await make_user(role="admin")
    owner = await make_user()
    r = await client.get(f"/api/admin/documents?userId={owner.id}", headers=admin.headers)
    assert r.status_code == 200
    r = await client.get("/api/admin/documents", headers=admin.headers)
    assert r.status_code == 200
    entries = await _entries(db)
    assert len(entries) == 2
    targeted = [e for e in entries if e["context"]["targetUserId"] == str(owner.id)]
    assert len(targeted) == 1
    ctx = targeted[0]["context"]
    assert ctx["adminId"] == str(admin.id) and ctx["resource"] == "documents"
    assert ctx["action"] == "list" and targeted[0]["createdAt"]
    assert targeted[0]["userId"] == admin.id
    assert any(e["context"]["targetUserId"] is None for e in entries)  # all-users view


async def test_admin_export_rows_and_workbook_list_audited(
    client: Any, db: Any, make_user: Any
) -> None:
    admin = await make_user(role="admin")
    owner = await make_user()
    assert (
        await client.get(f"/api/admin/exports?userId={owner.id}", headers=admin.headers)
    ).status_code == 200
    assert (await client.get("/api/admin/workbooks", headers=admin.headers)).status_code == 200
    resources = sorted(e["context"]["resource"] for e in await _entries(db))
    assert resources == ["export_rows", "workbooks"]


async def test_admin_workbook_download_audited_with_resource_id(
    client: Any, db: Any, make_user: Any, exports_dir: Path
) -> None:
    admin = await make_user(role="admin")
    owner = await make_user()
    now = datetime.now(UTC)
    wb_id = (
        await db.workbooks.insert_one(
            {
                "userId": owner.id,
                "year": 2026,
                "filename": "Books",
                "isActive": True,
                "createdAt": now,
                "updatedAt": now,
            }
        )
    ).inserted_id
    wb = openpyxl.Workbook()
    wb.save(exports_dir / f"{excel_service.physical_workbook_filename(owner.id, 'Books')}.xlsx")

    r = await client.get(f"/api/admin/workbooks/{wb_id}/download", headers=admin.headers)
    assert r.status_code == 200
    (entry,) = await _entries(db)
    ctx = entry["context"]
    assert ctx["action"] == "download" and ctx["resource"] == "workbook"
    assert ctx["targetUserId"] == str(owner.id) and ctx["resourceId"] == str(wb_id)


async def test_admin_viewing_own_data_not_logged_and_missing_workbook_not_logged(
    client: Any, db: Any, make_user: Any
) -> None:
    admin = await make_user(role="admin")
    await client.get(f"/api/admin/documents?userId={admin.id}", headers=admin.headers)
    r = await client.get(f"/api/admin/workbooks/{ObjectId()}/download", headers=admin.headers)
    assert r.status_code == 404
    assert await _entries(db) == []


async def test_non_admin_cannot_trigger_admin_routes_or_audit(
    client: Any, db: Any, make_user: Any
) -> None:
    user = await make_user()
    for path in ("/api/admin/documents", "/api/admin/exports", "/api/admin/workbooks"):
        assert (await client.get(path, headers=user.headers)).status_code == 403
    assert await _entries(db) == []
