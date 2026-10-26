"""Shared helpers for the chat HTTP tests (not a test module; imports no chat code)."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from bson import ObjectId

from app.core.rate_limit import limiter

BASE = "/api/chat"


@pytest.fixture
def limiter_on() -> Iterator[None]:
    """Turn the limiter ON for one test; reset before and after so nothing leaks."""
    old = limiter.enabled
    limiter.enabled = True
    limiter.reset()
    try:
        yield
    finally:
        limiter.reset()
        limiter.enabled = old


def ms_now() -> datetime:
    """tz-aware now truncated to milliseconds (Mongo's datetime precision)."""
    n = datetime.now(UTC)
    return n.replace(microsecond=(n.microsecond // 1000) * 1000)


def msg_of(res: Any) -> dict[str, Any]:
    """The message object from a POST/PATCH reply (bare or wrapped in {"message": ...})."""
    body = res.json()
    return body["message"] if isinstance(body.get("message"), dict) else body


def assert_created(res: Any) -> dict[str, Any]:
    assert res.status_code in (200, 201), res.text
    return msg_of(res)


async def seed(
    db: Any,
    thread_user: Any,
    text: str = "hello",
    *,
    sender: Any = None,
    role: str = "user",
    to_admin: Any = None,
    created: datetime | None = None,
    read: datetime | None = None,
    edited: datetime | None = None,
) -> ObjectId:
    """Raw insert into db.chatmessages. sender defaults to the thread user."""
    created = created or ms_now()
    doc = {
        "threadUserId": thread_user.id,
        "fromId": (sender or thread_user).id,
        "fromRole": role,
        "toAdminId": to_admin.id if to_admin is not None else None,
        "text": text,
        "createdAt": created,
        "updatedAt": created,
        "editedAt": edited,
        "readAt": read,
    }
    res = await db.chatmessages.insert_one(doc)
    return res.inserted_id


def minutes_ago(n: float) -> datetime:
    return ms_now() - timedelta(minutes=n)


async def user_send(client: Any, user: Any, admin: Any, text: str) -> Any:
    return await client.post(
        f"{BASE}/messages", headers=user.headers, json={"toAdminId": str(admin.id), "text": text}
    )


async def admin_send(client: Any, admin: Any, user: Any, text: str) -> Any:
    return await client.post(
        f"{BASE}/messages", headers=admin.headers, json={"userId": str(user.id), "text": text}
    )


async def thread(client: Any, who: Any, user: Any | None = None, **params: Any) -> Any:
    if user is not None:
        params["userId"] = str(user.id)
    return await client.get(f"{BASE}/messages", headers=who.headers, params=params)
