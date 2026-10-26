"""Per-account chat colour setting."""

from typing import Any

import pytest

from app.features.chat.chat_testkit import BASE

COLORS = ["blue", "violet", "teal", "green", "amber", "orange", "rose", "slate"]


async def test_default_color_is_blue(client: Any, make_user: Any) -> None:
    for role in ("user", "admin"):
        who = await make_user(role=role)
        r = await client.get(f"{BASE}/settings", headers=who.headers)
        assert r.status_code == 200 and r.json() == {"chatColor": "blue"}


@pytest.mark.parametrize("color", COLORS)
async def test_valid_color_saved_and_returned(client: Any, make_user: Any, color: str) -> None:
    u = await make_user()
    r = await client.put(f"{BASE}/settings/color", headers=u.headers, json={"color": color})
    assert r.status_code == 200, r.text
    assert (await client.get(f"{BASE}/settings", headers=u.headers)).json() == {"chatColor": color}


@pytest.mark.parametrize(
    "bad", ["red", "", "BLUE", " blue", "blue ", "#fff", 5, None, ["blue"], {"$ne": ""}]
)
async def test_invalid_color_rejected_and_not_saved(client: Any, make_user: Any, bad: Any) -> None:
    u = await make_user()
    assert (
        await client.put(f"{BASE}/settings/color", headers=u.headers, json={"color": "rose"})
    ).status_code == 200
    r = await client.put(f"{BASE}/settings/color", headers=u.headers, json={"color": bad})
    assert r.status_code == 422
    assert (await client.get(f"{BASE}/settings", headers=u.headers)).json() == {"chatColor": "rose"}


async def test_missing_color_or_extra_field_rejected(client: Any, make_user: Any) -> None:
    u = await make_user()
    assert (
        await client.put(f"{BASE}/settings/color", headers=u.headers, json={})
    ).status_code == 422
    r = await client.put(
        f"{BASE}/settings/color", headers=u.headers, json={"color": "teal", "role": "admin"}
    )
    assert r.status_code == 422


async def test_color_is_per_account(client: Any, make_user: Any) -> None:
    a, b = await make_user(), await make_user()
    await client.put(f"{BASE}/settings/color", headers=a.headers, json={"color": "amber"})
    assert (await client.get(f"{BASE}/settings", headers=b.headers)).json() == {"chatColor": "blue"}
    assert (await client.get(f"{BASE}/settings", headers=a.headers)).json() == {
        "chatColor": "amber"
    }


async def test_color_does_not_grant_a_role_change(client: Any, make_user: Any, db: Any) -> None:
    u = await make_user()
    await client.put(f"{BASE}/settings/color", headers=u.headers, json={"color": "green"})
    assert (await db.users.find_one({"_id": u.id}))["role"] == "user"
