"""Per-account chat rate limits (limiter ON; reset before and after every test)."""

from typing import Any

import pytest

from app.features.chat.chat_testkit import (  # noqa: F401  (limiter_on is a fixture)
    BASE,
    admin_send,
    assert_created,
    limiter_on,
    user_send,
)

pytestmark = pytest.mark.usefixtures("limiter_on")


async def test_user_61st_send_in_an_hour_is_429(client: Any, make_user: Any) -> None:
    u, adm = await make_user(), await make_user(role="admin")
    for i in range(60):
        r = await user_send(client, u, adm, f"m{i}")
        assert r.status_code in (200, 201), f"send {i + 1}: {r.status_code} {r.text}"
    assert (await user_send(client, u, adm, "one too many")).status_code == 429


async def test_user_limit_is_per_account(client: Any, make_user: Any) -> None:
    u, v, adm = await make_user(), await make_user(), await make_user(role="admin")
    for i in range(60):
        await user_send(client, u, adm, f"m{i}")
    assert (await user_send(client, u, adm, "x")).status_code == 429
    assert_created(await user_send(client, v, adm, "other account unaffected"))


async def test_admin_201st_send_is_429(client: Any, make_user: Any) -> None:
    u, adm = await make_user(), await make_user(role="admin")
    for i in range(200):
        r = await admin_send(client, adm, u, f"m{i}")
        assert r.status_code in (200, 201), f"send {i + 1}: {r.status_code} {r.text}"
    assert (await admin_send(client, adm, u, "one too many")).status_code == 429


async def test_edit_limit_60_per_hour(client: Any, make_user: Any) -> None:
    u, adm = await make_user(), await make_user(role="admin")
    mid = assert_created(await user_send(client, u, adm, "v0"))["id"]
    for i in range(60):
        r = await client.patch(f"{BASE}/messages/{mid}", headers=u.headers, json={"text": f"v{i}"})
        assert r.status_code == 200, f"edit {i + 1}: {r.status_code} {r.text}"
    r = await client.patch(f"{BASE}/messages/{mid}", headers=u.headers, json={"text": "late"})
    assert r.status_code == 429


async def test_edit_and_send_budgets_are_separate(client: Any, make_user: Any) -> None:
    u, adm = await make_user(), await make_user(role="admin")
    mid = assert_created(await user_send(client, u, adm, "v0"))["id"]
    for i in range(60):
        await client.patch(f"{BASE}/messages/{mid}", headers=u.headers, json={"text": f"v{i}"})
    assert_created(await user_send(client, u, adm, "send still fine"))


async def test_one_hour_of_polling_is_never_429(client: Any, make_user: Any) -> None:
    u = await make_user()
    statuses: list[int] = []
    for _ in range(720):
        statuses.append((await client.get(f"{BASE}/messages", headers=u.headers)).status_code)
    for _ in range(120):
        statuses.append((await client.get(f"{BASE}/unread", headers=u.headers)).status_code)
    assert len(statuses) == 840
    assert 429 not in statuses
    assert set(statuses) == {200}


async def test_polling_does_not_eat_the_send_budget(client: Any, make_user: Any) -> None:
    u, adm = await make_user(), await make_user(role="admin")
    for _ in range(100):
        await client.get(f"{BASE}/unread", headers=u.headers)
    assert_created(await user_send(client, u, adm, "ok"))


async def test_limiter_state_does_not_leak_between_tests_first(client: Any, make_user: Any) -> None:
    """Exhausts a budget; the sibling test below must still start from a clean counter."""
    u, adm = await make_user(), await make_user(role="admin")
    for i in range(60):
        await user_send(client, u, adm, f"m{i}")
    assert (await user_send(client, u, adm, "x")).status_code == 429


async def test_limiter_state_does_not_leak_between_tests_second(
    client: Any, make_user: Any
) -> None:
    u, adm = await make_user(), await make_user(role="admin")
    for i in range(60):
        r = await user_send(client, u, adm, f"m{i}")
        assert r.status_code in (200, 201), r.text
