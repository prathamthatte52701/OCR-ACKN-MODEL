from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.audit_log import log_action
from app.core.config import settings
from app.core.database import get_database
from app.core.rate_limit import (
    allow_password_reset_for_email,
    enforce_login_email_limit,
    limiter,
)
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    hash_password,
    sign_token,
    verify_password,
)
from app.core.validators import (
    normalize_email,
    normalize_username,
    validate_email,
    validate_password,
    validate_username,
)
from app.features.auth.dependencies import (
    STATUS_APPROVED,
    STATUS_PENDING,
    CurrentUser,
    get_current_user,
    get_current_user_allow_password_change,
    iso_utc,
    raise_if_not_approved,
)
from app.features.auth.password_requests import (
    GENERIC_RESET_MESSAGE,
    can_request_reset,
    handle_reset_request,
    sanitize_note,
)
from app.features.auth.schemas import (
    ChangePasswordRequest,
    GoogleLoginRequest,
    LoginRequest,
    MessageResponse,
    PasswordResetRequestBody,
    SignupRequest,
    TokenResponse,
    UpdateProfileRequest,
    UserOut,
)

router = APIRouter()

# Shared text for every non-field-specific signup failure (duplicate email,
# race-condition duplicate) - must stay byte-identical so none of them stands
# out as the "email already exists" case in particular (account-enumeration fix).
GENERIC_SIGNUP_ERROR = "Could not create your account. Please check your details and try again."


def _user_out(user: dict) -> UserOut:
    return UserOut(
        id=str(user["_id"]),
        username=user["username"],
        email=user["email"],
        role=user["role"],
        must_change_password=user.get("mustChangePassword") is True,
    )


@router.post("/signup", status_code=status.HTTP_201_CREATED, response_model=MessageResponse)
@limiter.limit("15/hour")
async def signup(request: Request, body: SignupRequest) -> MessageResponse:
    db = get_database()

    email = normalize_email(body.email)
    username = normalize_username(body.username)

    if err := validate_username(username):
        raise HTTPException(status_code=400, detail=err)
    if err := validate_email(email):
        raise HTTPException(status_code=400, detail=err)
    if err := validate_password(body.password, username, email):
        raise HTTPException(status_code=400, detail=err)

    # Hash before the uniqueness check so a taken-email response costs
    # roughly the same as a successful signup - a response-time gap would
    # otherwise let an attacker use signup as an email-existence oracle.
    password_hash = hash_password(body.password)

    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=400, detail=GENERIC_SIGNUP_ERROR)

    now = datetime.now(UTC)
    try:
        await db.users.insert_one(
            {
                "username": username,
                "email": email,
                "passwordHash": password_hash,
                "role": "user",
                "status": STATUS_PENDING,
                "tokenVersion": 0,
                "createdAt": now,
                "updatedAt": now,
            }
        )
    except Exception as exc:
        if "E11000" in str(exc):
            raise HTTPException(status_code=400, detail=GENERIC_SIGNUP_ERROR) from exc
        raise

    created = await db.users.find_one({"email": email})
    assert created is not None
    await log_action(created["_id"], "signup", {"email": email})
    return MessageResponse(message="Account created. Waiting for admin approval.")


@router.post("/password-reset-request", response_model=MessageResponse)
@limiter.limit("10/hour")
async def password_reset_request(
    request: Request, body: PasswordResetRequestBody
) -> MessageResponse:
    """Public. Always the same generic 200 (only the per-IP limit can answer 429); a request
    row is created only for an approved, non-admin account with a password."""
    db = get_database()
    email = normalize_email(body.email)
    user = await db.users.find_one({"email": email})
    could_create = can_request_reset(user)
    within_limit = allow_password_reset_for_email(email) if could_create else True
    eligible = could_create and within_limit
    await handle_reset_request(db, user, sanitize_note(body.note), eligible)
    return MessageResponse(message=GENERIC_RESET_MESSAGE)


async def _consume_approval_notice(db: AsyncIOMotorDatabase, user: dict) -> bool:
    """One-time "you're approved" notice, shared by password and Google login. Call only after
    the approval gate. find_one_and_update is atomic: of two concurrent logins only one matches."""
    consumed = await db.users.find_one_and_update(
        {"_id": user["_id"], "approvalNoticePending": True},
        {"$set": {"approvalNoticePending": False}},
    )
    return consumed is not None


@router.post("/login", response_model=TokenResponse)
@limiter.limit("100/15minute")
async def login(request: Request, body: LoginRequest) -> TokenResponse:
    db = get_database()
    email = normalize_email(body.email)
    if not email or not body.password:
        raise HTTPException(status_code=400, detail="Email and password are required.")
    await enforce_login_email_limit(request, email)

    user = await db.users.find_one({"email": email})
    # Always run exactly one bcrypt check (against a dummy hash when there is no
    # usable password) so unknown email / Google-only account / wrong password
    # are indistinguishable in both response and timing.
    stored_hash = user.get("passwordHash") if user else None
    password_ok = verify_password(body.password, stored_hash or DUMMY_PASSWORD_HASH)
    if not user or not stored_hash or not password_ok:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    # Password is checked FIRST so the pending/rejected message is only ever
    # shown to someone who proved they own the account (no status oracle).
    raise_if_not_approved(user)

    # Consume the one-time "you're approved" notice. Reached only after the password check
    # AND the approval gate above, so a wrong password or a pending/rejected account can never
    # use it up. find_one_and_update is atomic: of two concurrent logins only one matches.
    consumed = await _consume_approval_notice(db, user)

    # Auto-close an open password-reset request: the user got in with their own password.
    # Skipped while a temporary password is in force (that request is already done). One
    # conditional update, so it is race-safe and a no-op when nothing is open.
    if user.get("mustChangePassword") is not True:
        now = datetime.now(UTC)
        await db.passwordresetrequests.update_one(
            {"userId": user["_id"], "status": "open"},
            {
                "$set": {
                    "status": "done",
                    "resolution": "user_logged_in",
                    "resolvedAt": now,
                    "resolvedBy": None,
                    "updatedAt": now,
                }
            },
        )

    token = sign_token(str(user["_id"]), user["tokenVersion"], user["role"])
    await log_action(user["_id"], "login", {"email": email})
    return TokenResponse(
        token=token,
        user=_user_out(user),
        just_approved=consumed,
        approved_at=iso_utc(user.get("decidedAt")) if user.get("decision") == "approved" else None,
    )


async def _derive_google_username(db: AsyncIOMotorDatabase, email: str) -> str:
    """New Google signups have no username to collect (GSI hands us email +
    name/sub, not a username) - derive one from the email local-part,
    deduped against existing usernames the same way a manual signup would
    collide on a duplicate, since `username` has no unique index of its own
    but validate_username caps it at 3-8 chars."""
    base = normalize_username(email.split("@")[0])[:8] or "user"
    if len(base) < 3:
        base = (base + "user")[:8]
    candidate = base
    suffix = 1
    while await db.users.find_one({"username": candidate}):
        suffix_str = str(suffix)
        candidate = f"{base[: 8 - len(suffix_str)]}{suffix_str}"
        suffix += 1
    return candidate


@router.post("/google", response_model=TokenResponse)
@limiter.limit("100/15minute")
async def google_login(request: Request, body: GoogleLoginRequest) -> TokenResponse:
    try:
        payload = google_id_token.verify_oauth2_token(
            body.id_token, google_requests.Request(), settings.google_client_id
        )
    except Exception:  # noqa: BLE001 - never leak verification internals to the client
        raise HTTPException(status_code=401, detail="Could not verify Google sign-in.") from None

    if not payload.get("email_verified"):
        raise HTTPException(status_code=401, detail="Could not verify Google sign-in.")

    email = normalize_email(payload["email"])
    google_id = payload["sub"]
    await enforce_login_email_limit(request, email)

    db = get_database()
    user = await db.users.find_one({"email": email})
    now = datetime.now(UTC)

    if user:
        raise_if_not_approved(user)  # same 403 as password login; before any link/log/token
    else:
        # New Google user: waits for admin approval like an email signup, no token.
        username = await _derive_google_username(db, email)
        try:
            inserted = await db.users.insert_one(
                {
                    "username": username,
                    "email": email,
                    "role": "user",
                    "status": STATUS_PENDING,
                    "tokenVersion": 0,
                    "authProvider": "google",
                    "googleId": google_id,
                    "createdAt": now,
                    "updatedAt": now,
                }
            )
        except Exception as exc:
            if "E11000" not in str(exc):
                raise
            # A concurrent first login created it; answer from that account's real state
            # (pending/rejected/revoked 403; if it was approved meanwhile, sign in normally).
            user = await db.users.find_one({"email": email})
            if not user:
                raise HTTPException(status_code=400, detail=GENERIC_SIGNUP_ERROR) from exc
            raise_if_not_approved(user)
        else:
            await log_action(inserted.inserted_id, "signup", {"email": email, "method": "google"})
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "ACCOUNT_PENDING",
                    "message": "Your request was sent. Sign in again after the admin approves.",
                    "requestedAt": iso_utc(now),
                    "decidedAt": None,
                    "reason": None,
                },
            )

    if "google" not in user.get("authProvider", "local"):
        # Existing password account signing in with Google for the first time. Whoever set that
        # password may not be the Google owner (a stranger can sign up with someone's email), so
        # the link REPLACES the password: drop it, end every old session, close any open reset
        # request. One conditional update, so of two concurrent logins only one links.
        linked = await db.users.update_one(
            {
                "_id": user["_id"],
                "authProvider": {"$not": {"$regex": "google"}},
                # still approved now (None = an old account without the field): the admin may
                # have rejected it since the read above
                "status": {"$in": [STATUS_APPROVED, None]},
            },
            {
                "$set": {
                    "authProvider": "google",
                    "googleId": google_id,
                    "mustChangePassword": False,
                    "updatedAt": now,
                },
                "$unset": {"passwordHash": ""},
                "$inc": {"tokenVersion": 1},
            },
        )
        user = await db.users.find_one({"_id": user["_id"]})
        assert user is not None
        if linked.matched_count:
            await db.passwordresetrequests.update_one(
                {"userId": user["_id"], "status": "open"},
                {
                    "$set": {
                        "status": "done",
                        "resolution": "google_linked",
                        "resolvedAt": now,
                        "resolvedBy": None,
                        "updatedAt": now,
                    }
                },
            )
            await log_action(user["_id"], "google_account_linked", {"email": email})
        else:  # lost the race, or the account was rejected since the read: check again
            raise_if_not_approved(user)
            await log_action(user["_id"], "login", {"email": email, "method": "google"})
    else:
        await log_action(user["_id"], "login", {"email": email, "method": "google"})

    consumed = await _consume_approval_notice(db, user)
    token = sign_token(str(user["_id"]), user["tokenVersion"], user["role"])
    return TokenResponse(
        token=token,
        user=_user_out(user),
        just_approved=consumed,
        approved_at=iso_utc(user.get("decidedAt")) if user.get("decision") == "approved" else None,
    )


@router.get("/me", response_model=dict)
async def get_me(
    current_user: CurrentUser = Depends(get_current_user_allow_password_change),
) -> dict:
    db = get_database()
    user = await db.users.find_one({"_id": current_user.id})
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return {"user": _user_out(user)}


@router.patch("/me", response_model=dict)
async def update_me(
    body: UpdateProfileRequest, current_user: CurrentUser = Depends(get_current_user)
) -> dict:
    db = get_database()
    user = await db.users.find_one({"_id": current_user.id})
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated.")

    updates: dict = {}
    if body.username is not None:
        username = normalize_username(body.username)
        if err := validate_username(username):
            raise HTTPException(status_code=400, detail=err)
        updates["username"] = username

    # Email is an identity/approval anchor, so only an admin can change it. Sending
    # the unchanged address (the profile form does) is harmless and allowed.
    if body.email is not None and normalize_email(body.email) != user["email"]:
        raise HTTPException(
            status_code=403, detail="Only an admin can change your email. Contact the admin."
        )

    if updates:
        updates["updatedAt"] = datetime.now(UTC)
        await db.users.update_one({"_id": current_user.id}, {"$set": updates})
        refreshed = await db.users.find_one({"_id": current_user.id})
        assert refreshed is not None
        user = refreshed

    return {"user": _user_out(user)}


@router.post("/change-password", response_model=TokenResponse)
@limiter.limit("20/15minute")
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    current_user: CurrentUser = Depends(get_current_user_allow_password_change),
) -> TokenResponse:
    if body.new_password != body.confirm_new_password:
        raise HTTPException(status_code=400, detail="New password and confirmation do not match.")

    db = get_database()
    user = await db.users.find_one({"_id": current_user.id})
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    if "passwordHash" not in user:
        raise HTTPException(
            status_code=400,
            detail="This account uses Google Sign-In - there's no password to change.",
        )

    if not verify_password(body.current_password, user["passwordHash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")

    if body.new_password == body.current_password:
        raise HTTPException(
            status_code=400, detail="New password must be different from your current password."
        )
    if err := validate_password(body.new_password, user.get("username"), user.get("email")):
        raise HTTPException(status_code=400, detail=err)

    was_forced = user.get("mustChangePassword") is True
    new_hash = hash_password(body.new_password)
    new_token_version = user["tokenVersion"] + 1
    changes: dict = {
        "passwordHash": new_hash,
        "tokenVersion": new_token_version,
        "updatedAt": datetime.now(UTC),
    }
    if was_forced:
        changes["mustChangePassword"] = False
    # Conditional on the hash + tokenVersion we verified against: if an admin set a temp
    # password in between, that write wins and this one is refused instead of overwriting it.
    written = await db.users.update_one(
        {
            "_id": current_user.id,
            "passwordHash": user["passwordHash"],
            "tokenVersion": user["tokenVersion"],
        },
        {"$set": changes},
    )
    if written.matched_count == 0:
        raise HTTPException(
            status_code=409,
            detail="Your password was changed elsewhere. Please log in again.",
        )
    user["passwordHash"] = new_hash
    user["tokenVersion"] = new_token_version
    user["mustChangePassword"] = False

    # Re-issue a fresh token carrying the new tokenVersion so the tab that
    # just changed the password doesn't get logged out too - only every
    # OTHER previously-issued token is now invalid.
    token = sign_token(str(user["_id"]), new_token_version, user["role"])
    await log_action(user["_id"], "password_change", {"method": "change_password"})
    if was_forced:
        # A request filed between the temp password and this change would otherwise stay open.
        closed_at = datetime.now(UTC)
        await db.passwordresetrequests.update_one(
            {"userId": user["_id"], "status": "open"},
            {
                "$set": {
                    "status": "done",
                    "resolution": "user_logged_in",
                    "resolvedAt": closed_at,
                    "updatedAt": closed_at,
                    "resolvedBy": None,
                }
            },
        )
        await log_action(user["_id"], "PASSWORD_CHANGED_FORCED", {})
    return TokenResponse(token=token, user=_user_out(user))
