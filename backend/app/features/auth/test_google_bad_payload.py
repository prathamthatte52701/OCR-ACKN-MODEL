"""A Google token that passes verification but has a missing / empty / non-text email or sub must
be a clean 401 with the same generic message as every other bad Google token - never a 500, never a
created or changed user. Runs on the fake Mongo (conftest fixtures); the token check is mocked."""

from typing import Any

import pytest
from google.oauth2 import id_token as google_id_token
from httpx import AsyncClient

GENERIC = {"detail": "Could not verify Google sign-in."}
GOOD = {"email": "someone@bad-payload.local", "email_verified": True, "sub": "google-sub-1"}


def _mock(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> None:
    monkeypatch.setattr(google_id_token, "verify_oauth2_token", lambda *_a, **_k: payload)


def _without(key: str) -> dict[str, Any]:
    return {k: v for k, v in GOOD.items() if k != key}


BAD_PAYLOADS = {
    "no email": _without("email"),
    "email None": {**GOOD, "email": None},
    "empty email": {**GOOD, "email": ""},
    "blank email": {**GOOD, "email": "   "},
    "int email": {**GOOD, "email": 12345},
    "list email": {**GOOD, "email": ["a@b.c"]},
    "dict email": {**GOOD, "email": {"x": 1}},
    "no sub": _without("sub"),
    "sub None": {**GOOD, "sub": None},
    "empty sub": {**GOOD, "sub": ""},
    "blank sub": {**GOOD, "sub": "  "},
    "int sub": {**GOOD, "sub": 42},
    "list sub": {**GOOD, "sub": ["x"]},
    "email_verified false": {**GOOD, "email_verified": False},
    "email_verified missing": _without("email_verified"),
    "empty payload": {},
}


@pytest.mark.parametrize("name", sorted(BAD_PAYLOADS))
async def test_bad_google_payload_is_a_clean_401_and_creates_nothing(
    name: str, client: AsyncClient, db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock(monkeypatch, BAD_PAYLOADS[name])
    resp = await client.post("/api/auth/google", json={"idToken": "fake-token"})
    assert resp.status_code == 401, (name, resp.status_code, resp.text[:200])
    assert resp.json() == GENERIC
    assert "Traceback" not in resp.text and "KeyError" not in resp.text
    assert await db.users.count_documents({}) == 0


async def test_bad_payload_does_not_touch_an_existing_account(
    client: AsyncClient, db: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await make_user()
    before = await db.users.find_one({"_id": user.id})
    _mock(monkeypatch, {"email": user.email, "email_verified": True})  # no sub
    resp = await client.post("/api/auth/google", json={"idToken": "fake-token"})
    assert resp.status_code == 401 and resp.json() == GENERIC
    assert await db.users.find_one({"_id": user.id}) == before  # not linked, not changed


async def test_a_good_payload_still_works(
    client: AsyncClient, db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock(monkeypatch, GOOD)
    resp = await client.post("/api/auth/google", json={"idToken": "fake-token"})
    assert resp.status_code == 403  # new Google user waits for admin approval (unchanged)
    user = await db.users.find_one({"email": GOOD["email"]})
    assert user is not None and user["googleId"] == "google-sub-1"
