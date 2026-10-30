import asyncio
from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from limits import RateLimitItemPerHour
from starlette.datastructures import UploadFile

from app.core.audit_log import safe_log_action
from app.core.database import get_database
from app.core.rate_limit import limiter, user_or_ip_key
from app.core.security import verify_password
from app.features.auth.dependencies import CurrentUser, get_current_user, iso_utc, require_admin
from app.features.chat import files, service
from app.features.chat.errors import ChatError
from app.features.chat.schemas import (
    ClearAllRequest,
    ClearRequest,
    ColorRequest,
    EditMessageRequest,
    ReadRequest,
    SendMessageRequest,
)

router = APIRouter()

POLL_LIMIT = "2000/hour"  # polling must never trip a limit (5s polling is 720/hour)
SEND_LIMITS = {"user": 60, "admin": 200}  # messages per hour, per account
CLEAR_ALL_PER_HOUR = 5


async def _run(coro: Awaitable[Any]) -> Any:
    try:
        return await coro
    except ChatError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from None


def _require_user(current_user: CurrentUser) -> None:
    if current_user.role == "admin":
        raise HTTPException(status_code=403, detail="This is only for users.")


def _hit(request: Request, scope: str, per_hour: int) -> None:
    """Per-account hourly limit with a count chosen at request time (the send route serves
    both roles). Uses slowapi's own storage, so limiter.enabled / limiter.reset() apply."""
    if limiter.enabled and not limiter.limiter.hit(
        RateLimitItemPerHour(per_hour), scope, user_or_ip_key(request)
    ):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")


@router.get("/admins")
async def get_admins(current_user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    _require_user(current_user)
    return await service.list_admins(get_database())


@router.get("/threads")
@limiter.limit(POLL_LIMIT, key_func=user_or_ip_key)
async def get_threads(
    request: Request, current_user: CurrentUser = Depends(require_admin)
) -> list[dict]:
    return await service.list_threads(get_database(), current_user.id)


@router.get("/messages")
@limiter.limit(POLL_LIMIT, key_func=user_or_ip_key)
async def get_messages(
    request: Request,
    user_id: str | None = Query(None, alias="userId"),
    since: str | None = None,
    before: str | None = None,
    limit: int = Query(100, ge=1),  # < 1 is a 422; above 200 is quietly capped to 200
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    db = get_database()
    if current_user.role == "admin":
        thread_id = service.parse_object_id(user_id, "user") if user_id else None
        if thread_id is None:
            raise HTTPException(status_code=422, detail="Choose a user.")
    else:
        if user_id is not None and user_id != str(current_user.id):
            raise HTTPException(status_code=403, detail="You can only open your own chat.")
        thread_id = current_user.id

    async def build() -> dict:
        page = await service.fetch_page(
            db,
            current_user.id,
            current_user.role,
            thread_id,
            service.parse_datetime(since, "since") if since else None,
            service.parse_object_id(before, "before") if before else None,
            limit,
        )
        return {**page, "serverTime": iso_utc(service.utcnow())}

    return await _run(build())


@router.post("/messages", status_code=201)
async def send_message(
    request: Request,
    body: SendMessageRequest,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    db = get_database()
    is_admin = current_user.role == "admin"
    _hit(request, "chat_send", SEND_LIMITS["admin" if is_admin else "user"])
    if is_admin:
        if body.to_admin_id is not None:
            raise HTTPException(status_code=422, detail="Admins write to a user, not an admin.")
        coro = service.send_admin_message(db, current_user.id, body.user_id, body.text)
    else:
        if body.user_id is not None:
            raise HTTPException(status_code=422, detail="Choose an admin to write to.")
        coro = service.send_user_message(db, current_user.id, body.to_admin_id, body.text)
    return await _run(coro)


_FORM_FIELDS = {"file", "text", "toAdminId", "userId"}


@router.post("/messages/file", status_code=201)
async def send_file_message(
    request: Request, current_user: CurrentUser = Depends(get_current_user)
) -> dict:
    """multipart: file (exactly one), text (optional), toAdminId (users) / userId (admins)."""
    is_admin = current_user.role == "admin"
    role = "admin" if is_admin else "user"
    _hit(request, "chat_send", SEND_LIMITS[role])
    _hit(request, "chat_file", files.FILE_SENDS_PER_HOUR[role])
    try:
        form = await request.form(max_files=3, max_fields=10)
    except Exception:  # noqa: BLE001 - malformed multipart or a client that went away
        raise HTTPException(status_code=422, detail=files.BAD_FILE) from None
    try:
        if set(form.keys()) - _FORM_FIELDS:
            raise HTTPException(status_code=422, detail="Unknown field.")
        uploads = form.getlist("file")
        if len(uploads) != 1 or not isinstance(uploads[0], UploadFile):
            raise HTTPException(status_code=422, detail="Attach exactly one file.")
        text = form.get("text")
        if text is not None and not isinstance(text, str):
            raise HTTPException(status_code=422, detail="Message must be text.")
        if is_admin:
            if "toAdminId" in form:
                raise HTTPException(status_code=422, detail="Admins write to a user, not an admin.")
            recipient = form.get("userId")
        else:
            if "userId" in form:
                raise HTTPException(status_code=422, detail="Choose an admin to write to.")
            recipient = form.get("toAdminId")
        return await _run(
            service.send_file_message(
                get_database(), current_user.id, role, recipient, text, uploads[0]
            )
        )
    finally:
        await form.close()


@router.get("/files/{attachment_id}")
@limiter.limit("600/hour", key_func=user_or_ip_key)
async def get_file(
    request: Request, attachment_id: str, current_user: CurrentUser = Depends(get_current_user)
) -> Response:
    try:
        aid = service.parse_object_id(attachment_id, "file id")
    except ChatError:
        raise HTTPException(status_code=404, detail="File not found.") from None
    rec, data = await _run(files.open_file(get_database(), aid, current_user.id, current_user.role))
    return Response(
        content=data,
        media_type=rec["contentType"],
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Content-Disposition": files.content_disposition(rec["kind"], rec["name"]),
        },
    )


@router.patch("/messages/{message_id}")
@limiter.limit("60/hour", key_func=user_or_ip_key)
async def edit_message(
    request: Request,
    message_id: str,
    body: EditMessageRequest,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    async def go() -> dict:
        mid = service.parse_object_id(message_id, "message id")
        return await service.edit_message(get_database(), current_user.id, mid, body.text)

    return await _run(go())


@router.post("/read")
async def mark_read(
    body: ReadRequest, current_user: CurrentUser = Depends(get_current_user)
) -> dict:
    db = get_database()
    if current_user.role != "admin":
        # a user only ever reads their own thread: naming someone else's is refused, not ignored
        if body.user_id not in (None, str(current_user.id)):
            raise HTTPException(status_code=403, detail="You can only read your own messages.")

        async def go_user() -> int:
            up_to = service.parse_object_id(body.up_to_id, "message id")
            return await service.mark_read_user(db, current_user.id, up_to)

        return {"marked": await _run(go_user())}

    async def go() -> int:
        if body.user_id is None:
            raise service.ChatError(422, "Choose a user.")
        uid = service.parse_object_id(body.user_id, "user")
        up_to = service.parse_object_id(body.up_to_id, "message id")
        return await service.mark_read_admin(db, current_user.id, uid, up_to)

    return {"marked": await _run(go())}


@router.get("/unread")
@limiter.limit(POLL_LIMIT, key_func=user_or_ip_key)
async def get_unread(
    request: Request, current_user: CurrentUser = Depends(get_current_user)
) -> dict:
    db = get_database()
    if current_user.role == "admin":
        return await service.unread_admin(db, current_user.id)
    return await service.unread_user(db, current_user.id)


@router.get("/settings")
async def get_settings(current_user: CurrentUser = Depends(get_current_user)) -> dict:
    return {"chatColor": await service.get_color(get_database(), current_user.id)}


@router.put("/settings/color")
async def put_color(
    body: ColorRequest, current_user: CurrentUser = Depends(get_current_user)
) -> dict:
    return {"chatColor": await _run(service.set_color(get_database(), current_user.id, body.color))}


def _with_files(out: dict, res: dict) -> dict:
    """files/bytes appear only when chat files were involved: text replies keep the old shape."""
    if res["files"]:
        out.update(files=res["files"], bytes=res["bytes"])
    return out


def _need_delete(dry_run: bool, confirm: Any) -> None:
    if not dry_run and confirm != "DELETE":
        raise HTTPException(status_code=422, detail='Type "DELETE" to confirm.')


@router.post("/clear")
async def clear(body: ClearRequest, current_user: CurrentUser = Depends(require_admin)) -> dict:
    _need_delete(body.dry_run, body.confirm)

    async def go() -> dict:
        uid = service.parse_object_id(body.user_id, "user")
        return await service.clear_thread_full(
            get_database(), current_user.id, uid, body.older_than, body.dry_run
        )

    res = await _run(go())
    if body.dry_run:
        return _with_files({"count": res["messages"]}, res)
    await safe_log_action(
        current_user.id,
        "chat_cleared",
        _with_files(
            {"scope": str(body.user_id), "range": body.older_than, "deleted": res["messages"]}, res
        ),
    )
    return _with_files({"deleted": res["messages"]}, res)


@router.post("/clear-all")
async def clear_all(
    request: Request, body: ClearAllRequest, current_user: CurrentUser = Depends(require_admin)
) -> dict:
    db = get_database()
    _need_delete(body.dry_run, body.confirm)
    # counted before the password is checked, so wrong guesses (dry run or real) use up the budget
    _hit(request, "chat_clear_all", CLEAR_ALL_PER_HOUR)
    user = await db.users.find_one({"_id": current_user.id}, {"passwordHash": 1})
    if not user or "passwordHash" not in user:
        await safe_log_action(current_user.id, "chat_clear_blocked", {"reason": "no_password"})
        raise HTTPException(
            status_code=400,
            detail="This account uses Google Sign-In - there's no password to confirm with.",
        )
    password = body.password
    ok = isinstance(password, str) and await asyncio.to_thread(
        verify_password, password, user["passwordHash"]
    )
    if not ok:
        await safe_log_action(current_user.id, "chat_clear_blocked", {"reason": "wrong_password"})
        raise HTTPException(status_code=400, detail="Incorrect password.")
    if body.dry_run:
        res = await service.clear_all_full(db, current_user.id, True)
        return _with_files({"count": res["messages"]}, res)
    res = await service.clear_all_full(db, current_user.id, False)
    await safe_log_action(
        current_user.id,
        "chat_cleared",
        _with_files({"scope": "all", "range": "all", "deleted": res["messages"]}, res),
    )
    return _with_files({"deleted": res["messages"]}, res)
