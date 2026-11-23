"""An invalid ObjectId in a request is a 4xx with a plain message, never a 500 and never a stack
trace. pymongo 4.20 made ObjectId() stricter (a whitespace string raises InvalidId), so every place
that builds an ObjectId from user input is checked here, with the status each route family already
answered before this file existed (path/query ids 400, body ids and chat 422, chat file 404)."""

from typing import Any

import pytest

from app.core.security import sign_token

INVALID = {
    "24_spaces": " " * 24,
    "24_non_hex": "z" * 24,
    "23_chars": "a" * 23,
    "25_chars": "a" * 25,
    "unicode": "रसीद" * 6,
    "10000_chars": "a" * 10000,
}
LEAKS = ("Traceback", "InvalidId", "bson", "pymongo", 'File "', "site-packages")

# (label, method, url template, who, extra kwargs template, expected status for an invalid id)
# "{v}" in the url/params/json is replaced by the invalid value.
CASES: list[tuple[str, str, str, str, dict, int]] = [
    ("admin user path", "GET", "/api/admin/users/{v}", "admin", {}, 400),
    ("admin approve path", "POST", "/api/admin/users/{v}/approve", "admin", {}, 400),
    ("admin document delete path", "DELETE", "/api/admin/documents/{v}", "admin", {}, 400),
    ("admin workbook download path", "GET", "/api/admin/workbooks/{v}/download", "admin", {}, 400),
    (
        "admin documents ?userId",
        "GET",
        "/api/admin/documents",
        "admin",
        {"params": {"userId": "{v}"}},
        400,
    ),
    (
        "admin exports ?userId",
        "GET",
        "/api/admin/exports",
        "admin",
        {"params": {"userId": "{v}"}},
        400,
    ),
    ("admin logs ?userId", "GET", "/api/admin/logs", "admin", {"params": {"userId": "{v}"}}, 400),
    ("document path", "GET", "/api/documents/{v}", "user", {}, 400),
    (
        "document correct path",
        "PATCH",
        "/api/documents/{v}/correct",
        "user",
        {"json": {"field": "number", "value": "1"}},
        400,
    ),
    ("document save path", "POST", "/api/documents/{v}/save", "user", {}, 400),
    (
        "export history workbook path",
        "GET",
        "/api/documents/export-history/workbook/{v}/download",
        "user",
        {},
        400,
    ),
    (
        "workbook download ?workbookId",
        "GET",
        "/api/documents/workbook/download",
        "user",
        {"params": {"workbookId": "{v}"}},
        400,
    ),
    (
        "download-all body ids",
        "POST",
        "/api/documents/download-all",
        "user",
        {"json": {"documentIds": ["{v}"]}},
        422,
    ),
    (
        "bulk-save body ids",
        "POST",
        "/api/documents/bulk-save",
        "user",
        {"json": {"documentIds": ["{v}"]}},
        422,
    ),
    ("chat file path", "GET", "/api/chat/files/{v}", "user", {}, 404),
    (
        "chat edit message path",
        "PATCH",
        "/api/chat/messages/{v}",
        "user",
        {"json": {"text": "x"}},
        422,
    ),
    (
        "chat messages ?userId (admin)",
        "GET",
        "/api/chat/messages",
        "admin",
        {"params": {"userId": "{v}"}},
        422,
    ),
    (
        "chat messages ?before",
        "GET",
        "/api/chat/messages",
        "user",
        {"params": {"before": "{v}"}},
        422,
    ),
    (
        "chat send toAdminId",
        "POST",
        "/api/chat/messages",
        "user",
        {"json": {"toAdminId": "{v}", "text": "x"}},
        422,
    ),
    (
        "chat send userId (admin)",
        "POST",
        "/api/chat/messages",
        "admin",
        {"json": {"userId": "{v}", "text": "x"}},
        422,
    ),
    (
        "chat send file toAdminId",
        "POST",
        "/api/chat/messages/file",
        "user",
        {"data": {"toAdminId": "{v}"}, "files": {"file": ("a.txt", b"hi", "text/plain")}},
        422,
    ),
    ("chat read upToId", "POST", "/api/chat/read", "user", {"json": {"upToId": "{v}"}}, 422),
    (
        "chat clear userId",
        "POST",
        "/api/chat/clear",
        "admin",
        {"json": {"userId": "{v}", "dryRun": True}},
        422,
    ),
]


def _fill(obj: Any, v: str) -> Any:
    if isinstance(obj, str):
        return obj.replace("{v}", v)
    if isinstance(obj, list):
        return [_fill(x, v) for x in obj]
    if isinstance(obj, dict):
        return {k: _fill(x, v) for k, x in obj.items()}
    return obj


@pytest.mark.parametrize("value", list(INVALID.values()), ids=list(INVALID))
@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
async def test_invalid_id_is_a_clean_4xx(
    client: Any, make_user: Any, case: tuple, value: str
) -> None:
    _, method, url, who, extra, expected = case
    account = await make_user(role="admin" if who == "admin" else "user")
    kwargs = _fill(extra, value)
    res = await client.request(method, _fill(url, value), headers=account.headers, **kwargs)
    assert res.status_code == expected, res.text[:300]
    assert not any(w in res.text for w in LEAKS), res.text[:300]


@pytest.mark.parametrize("bad", ["", " " * 24, "nope", "z" * 24])
async def test_token_with_an_invalid_user_id_is_a_401_not_a_500(client: Any, bad: str) -> None:
    token = sign_token(bad, 0, "user")
    res = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401
    assert not any(w in res.text for w in LEAKS)


async def test_well_formed_but_unknown_ids_keep_their_404(client: Any, make_user: Any) -> None:
    admin, user = await make_user(role="admin"), await make_user()
    unknown = "a" * 24
    for url, who in (
        (f"/api/admin/users/{unknown}", admin),
        (f"/api/documents/{unknown}", user),
        (f"/api/admin/workbooks/{unknown}/download", admin),
    ):
        assert (await client.get(url, headers=who.headers)).status_code == 404, url
