"""Chat input validation: text rules, id shapes, NoSQL-shaped values."""

from typing import Any

import pytest

from app.features.chat.chat_testkit import BASE, assert_created, user_send


async def _setup(make_user: Any) -> tuple[Any, Any, Any]:
    return await make_user(), await make_user(role="admin"), await make_user(role="admin")


async def _post(client: Any, user: Any, body: Any) -> Any:
    return await client.post(f"{BASE}/messages", headers=user.headers, json=body)


async def test_exactly_1000_chars_accepted(client: Any, make_user: Any) -> None:
    u, adm, _ = await _setup(make_user)
    m = assert_created(await user_send(client, u, adm, "a" * 1000))
    assert len(m["text"]) == 1000


async def test_1001_chars_rejected(client: Any, make_user: Any, db: Any) -> None:
    u, adm, _ = await _setup(make_user)
    assert (await user_send(client, u, adm, "a" * 1001)).status_code == 422
    assert await db.chatmessages.count_documents({}) == 0


async def test_500_emoji_accepted_as_500_chars(client: Any, make_user: Any) -> None:
    u, adm, _ = await _setup(make_user)
    m = assert_created(await user_send(client, u, adm, "\U0001f600" * 500))
    assert m["text"] == "\U0001f600" * 500


async def test_1000_emoji_accepted_and_1001_rejected(client: Any, make_user: Any) -> None:
    u, adm, _ = await _setup(make_user)
    assert_created(await user_send(client, u, adm, "\U0001f600" * 1000))
    assert (await user_send(client, u, adm, "\U0001f600" * 1001)).status_code == 422


async def test_text_is_trimmed(client: Any, make_user: Any) -> None:
    u, adm, _ = await _setup(make_user)
    assert assert_created(await user_send(client, u, adm, "  hi there \n"))["text"] == "hi there"


async def test_trimmed_length_is_what_counts(client: Any, make_user: Any) -> None:
    u, adm, _ = await _setup(make_user)
    assert_created(await user_send(client, u, adm, "  " + "a" * 1000 + "  "))


@pytest.mark.parametrize("text", ["", " ", "   ", "\t", "\n\n", " \t\n "])
async def test_empty_or_whitespace_only_rejected(client: Any, make_user: Any, text: str) -> None:
    u, adm, _ = await _setup(make_user)
    assert (await user_send(client, u, adm, text)).status_code == 422


async def test_nul_character_rejected(client: Any, make_user: Any) -> None:
    u, adm, _ = await _setup(make_user)
    assert (await user_send(client, u, adm, "he\x00llo")).status_code == 422


@pytest.mark.parametrize("bad", [123, 1.5, True, ["a"], {"a": 1}, {"$ne": ""}, None])
async def test_non_string_text_rejected(client: Any, make_user: Any, bad: Any) -> None:
    u, adm, _ = await _setup(make_user)
    r = await _post(client, u, {"toAdminId": str(adm.id), "text": bad})
    assert r.status_code == 422


async def test_missing_text_or_target_rejected(client: Any, make_user: Any) -> None:
    u, adm, _ = await _setup(make_user)
    assert (await _post(client, u, {"toAdminId": str(adm.id)})).status_code == 422
    assert (await _post(client, u, {"text": "hi"})).status_code == 422
    assert (await _post(client, u, {})).status_code == 422


@pytest.mark.parametrize(
    "bad",
    ["", "abc", "123", "z" * 24, "0" * 23, "0" * 25, "../etc", "null", 5, None, ["x"]],
)
async def test_invalid_object_id_strings_rejected_for_user_send(
    client: Any, make_user: Any, db: Any, bad: Any
) -> None:
    u, _, _ = await _setup(make_user)
    r = await _post(client, u, {"toAdminId": bad, "text": "hi"})
    assert r.status_code in (400, 404, 422)
    assert await db.chatmessages.count_documents({}) == 0


@pytest.mark.parametrize("bad", ["", "abc", "z" * 24, "0" * 23, 5, None, ["x"]])
async def test_invalid_object_id_strings_rejected_for_admin_send(
    client: Any, make_user: Any, db: Any, bad: Any
) -> None:
    _, adm, _ = await _setup(make_user)
    r = await client.post(
        f"{BASE}/messages", headers=adm.headers, json={"userId": bad, "text": "hi"}
    )
    assert r.status_code in (400, 404, 422)
    assert await db.chatmessages.count_documents({}) == 0


async def test_to_admin_id_pointing_to_normal_user_rejected(
    client: Any, make_user: Any, db: Any
) -> None:
    u, _, _ = await _setup(make_user)
    other = await make_user()
    assert (await user_send(client, u, other, "hi")).status_code in (400, 404, 422)
    assert await db.chatmessages.count_documents({}) == 0


async def test_to_admin_id_missing_account_rejected(client: Any, make_user: Any, db: Any) -> None:
    u, _, _ = await _setup(make_user)
    r = await _post(client, u, {"toAdminId": "5" * 24, "text": "hi"})
    assert r.status_code in (400, 404, 422)
    assert await db.chatmessages.count_documents({}) == 0


@pytest.mark.parametrize(
    "bad", [{"$ne": ""}, {"$gt": ""}, {"$exists": True}, {"$regex": ".*"}, {"$in": []}]
)
async def test_nosql_shaped_target_ids_rejected(
    client: Any, make_user: Any, db: Any, bad: Any
) -> None:
    u, adm, _ = await _setup(make_user)
    await make_user()
    assert (await _post(client, u, {"toAdminId": bad, "text": "hi"})).status_code == 422
    r = await client.post(
        f"{BASE}/messages", headers=adm.headers, json={"userId": bad, "text": "hi"}
    )
    assert r.status_code == 422
    assert await db.chatmessages.count_documents({}) == 0


async def test_nosql_shaped_query_params_rejected_or_harmless(
    client: Any, make_user: Any, db: Any
) -> None:
    from app.features.chat.chat_testkit import seed

    u, adm, _ = await _setup(make_user)
    await seed(db, u, "secret", to_admin=adm)
    for qs in ("userId[$ne]=x", "userId[$gt]=", "before[$ne]=x", "since[$ne]=x"):
        r = await client.get(f"{BASE}/messages?{qs}", headers=adm.headers)
        assert r.status_code in (200, 422)
        if r.status_code == 200:
            assert "secret" not in r.text


async def test_script_tag_stored_and_returned_verbatim(
    client: Any, make_user: Any, db: Any
) -> None:
    u, adm, _ = await _setup(make_user)
    txt = "<script>alert('x')</script>&amp;"
    assert assert_created(await user_send(client, u, adm, txt))["text"] == txt
    assert (await db.chatmessages.find_one({}))["text"] == txt
    r = await client.get(f"{BASE}/messages", headers=u.headers)
    assert [m["text"] for m in r.json()["messages"]] == [txt]


async def test_unknown_extra_field_rejected(client: Any, make_user: Any) -> None:
    u, adm, _ = await _setup(make_user)
    r = await _post(client, u, {"toAdminId": str(adm.id), "text": "hi", "fromRole": "admin"})
    assert r.status_code == 422


@pytest.mark.parametrize("limit", [0, -1, "x"])
async def test_bad_limit_rejected(client: Any, make_user: Any, limit: Any) -> None:
    u, _, _ = await _setup(make_user)
    r = await client.get(f"{BASE}/messages", headers=u.headers, params={"limit": limit})
    assert r.status_code == 422


@pytest.mark.parametrize("bad", ["abc", "not-a-date", "2024-13-45"])
async def test_bad_since_rejected(client: Any, make_user: Any, bad: str) -> None:
    u, _, _ = await _setup(make_user)
    r = await client.get(f"{BASE}/messages", headers=u.headers, params={"since": bad})
    assert r.status_code == 422


@pytest.mark.parametrize("bad", ["abc", "z" * 24, "0" * 23])
async def test_bad_before_cursor_rejected(client: Any, make_user: Any, bad: str) -> None:
    u, _, _ = await _setup(make_user)
    r = await client.get(f"{BASE}/messages", headers=u.headers, params={"before": bad})
    assert r.status_code in (400, 422)
