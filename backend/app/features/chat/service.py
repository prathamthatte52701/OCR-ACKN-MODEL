"""One-to-one support chat between a user and the admins. Logic only (no HTTP): router.py maps
ChatError to HTTPException. Message text is never logged or audited anywhere."""

from datetime import UTC, datetime, timedelta
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId

from app.features.auth.dependencies import iso_utc

CHAT_COLORS = ("blue", "violet", "teal", "green", "amber", "orange", "rose", "slate")
DEFAULT_COLOR = "blue"
MAX_TEXT = 1000
EDIT_WINDOW = timedelta(minutes=15)
# `nextSince` stays this far behind "now": a message stamped just before a poll can commit just
# after it, so the next poll must look back a little (clients dedupe by id).
SINCE_MARGIN = timedelta(seconds=2)
CLEAR_RANGES = {
    "24h": timedelta(hours=24),
    "3d": timedelta(days=3),
    "1w": timedelta(weeks=1),
    "1m": timedelta(days=30),
    "3m": timedelta(days=90),
    "6m": timedelta(days=180),
    "1y": timedelta(days=365),
}
MAX_LIMIT = 200
_APPROVED = {"$or": [{"status": "approved"}, {"status": {"$exists": False}}]}


class ChatError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def utcnow() -> datetime:
    return datetime.now(UTC)


def aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def clean_text(value: Any) -> str:
    if not isinstance(value, str):
        raise ChatError(422, "Message must be text.")
    if "\x00" in value:
        raise ChatError(422, "Message contains a character that is not allowed.")
    text = value.strip()
    if not text:
        raise ChatError(422, "Message cannot be empty.")
    if len(text) > MAX_TEXT:
        raise ChatError(422, f"Message is too long (maximum {MAX_TEXT} characters).")
    return text


def parse_object_id(value: Any, field: str) -> ObjectId:
    if isinstance(value, str):
        try:
            return ObjectId(value)
        except InvalidId:
            pass
    raise ChatError(422, f"Invalid {field}.")


def parse_datetime(value: str, field: str) -> datetime:
    try:
        return aware(datetime.fromisoformat(value)).astimezone(UTC)
    except (ValueError, OverflowError):
        raise ChatError(422, f"Invalid {field}.") from None


def _name(user: dict | None, removed: str) -> str:
    return user["username"] if user else removed


async def serialize(
    db: Any, docs: list[dict], viewer_id: ObjectId, now: datetime | None = None
) -> list[dict]:
    now = now or utcnow()
    ids = {d["fromId"] for d in docs} | {d["toAdminId"] for d in docs if d.get("toAdminId")}
    users = {}
    if ids:
        async for u in db.users.find({"_id": {"$in": list(ids)}}, {"username": 1}):
            users[u["_id"]] = u
    out = []
    for d in docs:
        removed = "Removed admin" if d["fromRole"] == "admin" else "Removed user"
        to_id = d.get("toAdminId")
        out.append(
            {
                "id": str(d["_id"]),
                "fromId": str(d["fromId"]),
                "fromRole": d["fromRole"],
                "fromName": _name(users.get(d["fromId"]), removed),
                "toAdminId": str(to_id) if to_id else None,
                "toAdminName": _name(users.get(to_id), "Removed admin") if to_id else None,
                "text": d["text"],
                "createdAt": iso_utc(d["createdAt"]),
                "editedAt": iso_utc(d.get("editedAt")),
                "readAt": iso_utc(d.get("readAt")),
                "mine": d["fromId"] == viewer_id,
                "canEdit": d["fromId"] == viewer_id and now - aware(d["createdAt"]) <= EDIT_WINDOW,
                # when the edit window closes (None for other people's messages): clients should
                # use this instead of adding 15 minutes to createdAt on a possibly skewed clock
                "editableUntil": (
                    iso_utc(aware(d["createdAt"]) + EDIT_WINDOW)
                    if d["fromId"] == viewer_id
                    else None
                ),
            }
        )
    return out


async def list_admins(db: Any) -> list[dict]:
    rows = db.users.find({"role": "admin", **_APPROVED}, {"username": 1}).sort("username", 1)
    return [{"id": str(u["_id"]), "name": u["username"]} async for u in rows]


async def _thread_user(db: Any, user_id: ObjectId) -> dict:
    user = await db.users.find_one({"_id": user_id, "role": {"$ne": "admin"}, **_APPROVED})
    if user is None:
        raise ChatError(404, "User not found.")
    return user


async def list_threads(db: Any, admin_id: ObjectId) -> list[dict]:
    users = await db.users.find({"role": {"$ne": "admin"}, **_APPROVED}, {"username": 1}).to_list(
        None
    )
    unread = {
        r["_id"]: r["n"]
        async for r in db.chatmessages.aggregate(
            [
                {"$match": {"toAdminId": admin_id, "readAt": None}},
                {"$group": {"_id": "$threadUserId", "n": {"$sum": 1}}},
            ]
        )
    }
    last = {
        r["_id"]: r["t"]
        async for r in db.chatmessages.aggregate(
            [{"$group": {"_id": "$threadUserId", "t": {"$max": "$createdAt"}}}]
        )
    }
    rows = [
        {
            "userId": str(u["_id"]),
            "name": u["username"],
            "unreadCount": unread.get(u["_id"], 0),
            "lastMessageAt": iso_utc(last.get(u["_id"])),
            "_t": aware(last[u["_id"]]).timestamp() if u["_id"] in last else None,
        }
        for u in users
    ]
    # unread-first, then newest activity (threads with no messages last), then name
    rows.sort(
        key=lambda r: (
            r["unreadCount"] == 0,
            r["_t"] is None,
            -(r["_t"] or 0),
            r["name"].lower(),
        )
    )
    for r in rows:
        del r["_t"]
    return rows


async def fetch_page(
    db: Any,
    viewer_id: ObjectId,
    viewer_role: str,
    thread_user_id: ObjectId,
    since: datetime | None = None,
    before: ObjectId | None = None,
    limit: int = 100,
) -> dict:
    """One page of a thread plus what a polling client needs: `hasMore` (more matches exist
    beyond `limit`), `nextSince` (a safe value for the next `since`: dedupe by id) and
    `threadCount` (messages now in the thread, so a client can notice cleared messages)."""
    started = utcnow()
    if viewer_role == "admin":
        await _thread_user(db, thread_user_id)
    elif thread_user_id != viewer_id:
        raise ChatError(403, "You can only open your own chat.")
    limit = max(1, min(limit, MAX_LIMIT))
    query: dict[str, Any] = {"threadUserId": thread_user_id}
    if since is not None:
        query["updatedAt"] = {"$gte": since}
    if before is not None:
        cursor = await db.chatmessages.find_one({"_id": before, "threadUserId": thread_user_id})
        if cursor is None:
            raise ChatError(404, "Message not found.")
        query["$or"] = [
            {"createdAt": {"$lt": cursor["createdAt"]}},
            {"createdAt": cursor["createdAt"], "_id": {"$lt": before}},
        ]
    if since is not None:
        # oldest change first, so a client that falls behind catches up page by page instead of
        # silently skipping the older changes (e.g. 300 read receipts after one /read)
        cur = db.chatmessages.find(query).sort([("updatedAt", 1), ("_id", 1)]).limit(limit + 1)
        docs = await cur.to_list(limit + 1)
        has_more = len(docs) > limit
        docs = docs[:limit]
        next_since = aware(docs[-1]["updatedAt"]) if has_more else started - SINCE_MARGIN
    else:
        # newest `limit` matches, then flipped to ascending (createdAt, _id)
        cur = db.chatmessages.find(query).sort([("createdAt", -1), ("_id", -1)]).limit(limit + 1)
        docs = await cur.to_list(limit + 1)
        has_more = len(docs) > limit
        docs = docs[:limit]
        docs.reverse()
        next_since = started - SINCE_MARGIN
    return {
        "messages": await serialize(db, docs, viewer_id),
        "hasMore": has_more,
        "nextSince": iso_utc(next_since),
        "threadCount": await db.chatmessages.count_documents({"threadUserId": thread_user_id}),
    }


async def fetch_messages(
    db: Any,
    viewer_id: ObjectId,
    viewer_role: str,
    thread_user_id: ObjectId,
    since: datetime | None = None,
    before: ObjectId | None = None,
    limit: int = 100,
) -> list[dict]:
    page = await fetch_page(db, viewer_id, viewer_role, thread_user_id, since, before, limit)
    return page["messages"]


async def _insert(
    db: Any, thread_user_id: ObjectId, sender: ObjectId, role: str, to: ObjectId | None, text: str
) -> dict:
    now = utcnow()
    doc = {
        "threadUserId": thread_user_id,
        "fromId": sender,
        "fromRole": role,
        "toAdminId": to,
        "text": text,
        "createdAt": now,
        "updatedAt": now,
        "editedAt": None,
        "readAt": None,
    }
    doc["_id"] = (await db.chatmessages.insert_one(doc)).inserted_id
    return (await serialize(db, [doc], sender, now))[0]


async def send_user_message(db: Any, user_id: ObjectId, to_admin_id: Any, text: Any) -> dict:
    clean = clean_text(text)
    try:
        admin_id = parse_object_id(to_admin_id, "admin")
    except ChatError:
        raise ChatError(422, "Choose an admin to write to.") from None
    admin = await db.users.find_one({"_id": admin_id, "role": "admin", **_APPROVED}, {"_id": 1})
    if admin is None:
        raise ChatError(422, "Choose an admin to write to.")
    return await _insert(db, user_id, user_id, "user", admin_id, clean)


async def send_admin_message(db: Any, admin_id: ObjectId, user_id: Any, text: Any) -> dict:
    clean = clean_text(text)
    target = parse_object_id(user_id, "user")
    await _thread_user(db, target)
    return await _insert(db, target, admin_id, "admin", None, clean)


async def edit_message(db: Any, editor_id: ObjectId, message_id: ObjectId, text: Any) -> dict:
    clean = clean_text(text)
    msg = await db.chatmessages.find_one({"_id": message_id})
    if msg is None:
        raise ChatError(404, "Message not found.")
    if msg["fromId"] != editor_id:
        raise ChatError(403, "You can only edit your own messages.")
    now = utcnow()
    # exact check first (Mongo keeps milliseconds only, so the filter below alone would let an
    # edit 1 microsecond past the window through)
    if now - aware(msg["createdAt"]) > EDIT_WINDOW:
        raise ChatError(403, "The 15-minute edit time is over.")
    # conditional filter: the window check and the write are one atomic step
    updated = await db.chatmessages.find_one_and_update(
        {"_id": message_id, "fromId": editor_id, "createdAt": {"$gte": now - EDIT_WINDOW}},
        {"$set": {"text": clean, "editedAt": now, "updatedAt": now}},
        return_document=True,
    )
    if updated is None:
        raise ChatError(403, "The 15-minute edit time is over.")
    return (await serialize(db, [updated], editor_id, now))[0]


async def _mark(db: Any, query: dict) -> int:
    now = utcnow()
    res = await db.chatmessages.update_many(
        {**query, "readAt": None}, {"$set": {"readAt": now, "updatedAt": now}}
    )
    return res.modified_count


async def _up_to(db: Any, thread_user_id: ObjectId, up_to_id: ObjectId) -> dict:
    """Query for messages at or before `up_to_id` in the thread, by the (createdAt, _id) order
    the `before` cursor uses."""
    ref = await db.chatmessages.find_one({"_id": up_to_id, "threadUserId": thread_user_id})
    if ref is None:
        raise ChatError(404, "Message not found.")
    return {
        "threadUserId": thread_user_id,
        "$or": [
            {"createdAt": {"$lt": ref["createdAt"]}},
            {"createdAt": ref["createdAt"], "_id": {"$lte": up_to_id}},
        ],
    }


async def mark_read_user(db: Any, user_id: ObjectId, up_to_id: ObjectId) -> int:
    return await _mark(db, {**await _up_to(db, user_id, up_to_id), "fromRole": "admin"})


async def mark_read_admin(
    db: Any, admin_id: ObjectId, thread_user_id: ObjectId, up_to_id: ObjectId
) -> int:
    await _thread_user(db, thread_user_id)
    return await _mark(db, {**await _up_to(db, thread_user_id, up_to_id), "toAdminId": admin_id})


async def unread_user(db: Any, user_id: ObjectId) -> dict:
    n = await db.chatmessages.count_documents(
        {"threadUserId": user_id, "fromRole": "admin", "readAt": None}
    )
    return {"count": n}


async def unread_admin(db: Any, admin_id: ObjectId) -> dict:
    # only threads this admin can actually open (approved, non-admin owners): a rejected user's
    # leftover message must not keep a badge that /read could never clear
    openable = [
        u["_id"] async for u in db.users.find({"role": {"$ne": "admin"}, **_APPROVED}, {"_id": 1})
    ]
    rows = [
        {"userId": str(r["_id"]), "count": r["n"]}
        async for r in db.chatmessages.aggregate(
            [
                {
                    "$match": {
                        "toAdminId": admin_id,
                        "readAt": None,
                        "threadUserId": {"$in": openable},
                    }
                },
                {"$group": {"_id": "$threadUserId", "n": {"$sum": 1}}},
            ]
        )
    ]
    return {"count": sum(r["count"] for r in rows), "byUser": rows}


async def get_color(db: Any, user_id: ObjectId) -> str:
    user = await db.users.find_one({"_id": user_id}, {"chatColor": 1})
    color = user.get("chatColor") if user else None
    return color if color in CHAT_COLORS else DEFAULT_COLOR


async def set_color(db: Any, user_id: ObjectId, color: Any) -> str:
    if not isinstance(color, str) or color not in CHAT_COLORS:
        raise ChatError(422, "Choose one of the listed colours.")
    await db.users.update_one({"_id": user_id}, {"$set": {"chatColor": color}})
    return color


async def clear_thread(
    db: Any, admin_id: ObjectId, thread_user_id: ObjectId, older_than: Any, dry_run: bool
) -> int:
    if older_than != "all" and (not isinstance(older_than, str) or older_than not in CLEAR_RANGES):
        raise ChatError(422, "Choose how old the messages should be.")
    await _thread_user(db, thread_user_id)
    query: dict[str, Any] = {"threadUserId": thread_user_id}
    if older_than != "all":
        query["createdAt"] = {"$lt": utcnow() - CLEAR_RANGES[older_than]}
    if dry_run:
        return await db.chatmessages.count_documents(query)
    return (await db.chatmessages.delete_many(query)).deleted_count


async def clear_all(db: Any, admin_id: ObjectId, dry_run: bool) -> int:
    if dry_run:
        return await db.chatmessages.count_documents({})
    return (await db.chatmessages.delete_many({})).deleted_count
