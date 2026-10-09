from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.audit_log import log_action
from app.core.config import settings
from app.core.database import get_database
from app.core.rate_limit import enforce_login_email_limit, limiter
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
    raise_if_not_approved,
)
from app.features.auth.schemas import (
    ChangePasswordRequest,
    ForgotPasswordResetRequest,
    ForgotPasswordVerifyRequest,
    GoogleLoginRequest,
    LoginRequest,
    MessageResponse,
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
# Same reasoning, same wording pattern, for forgot-password.
GENERIC_FORGOT_PASSWORD_ERROR = "Username and email do not match our records."
GOOGLE_ONLY_FORGOT_PASSWORD_ERROR = (
    "This account uses Google Sign-In - there's no password to reset."
)


def _is_google_only(user: dict) -> bool:
    # Exactly "google" (not "local+google", which still has a real
    # passwordHash to reset) - matches the presence/absence-of-passwordHash
    # contract used everywhere else in this file.
    return user.get("authProvider") == "google"


def _user_out(user: dict) -> UserOut:
    return UserOut(
        id=str(user["_id"]), username=user["username"], email=user["email"], role=user["role"]
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
    raise_if_not_approved(user.get("status", STATUS_APPROVED))

    # Consume the one-time "you're approved" notice. Reached only after the password check
    # AND the approval gate above, so a wrong password or a pending/rejected account can never
    # use it up. find_one_and_update is atomic: of two concurrent logins only one matches.
    consumed = await db.users.find_one_and_update(
        {"_id": user["_id"], "approvalNoticePending": True},
        {"$set": {"approvalNoticePending": False}},
    )

    token = sign_token(str(user["_id"]), user["tokenVersion"], user["role"])
    await log_action(user["_id"], "login", {"email": email})
    return TokenResponse(token=token, user=_user_out(user), just_approved=consumed is not None)


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

    if not user:
        username = await _derive_google_username(db, email)
        await db.users.insert_one(
            {
                "username": username,
                "email": email,
                "role": "user",
                "status": STATUS_APPROVED,
                "tokenVersion": 0,
                "authProvider": "google",
                "googleId": google_id,
                "createdAt": now,
                "updatedAt": now,
            }
        )
        user = await db.users.find_one({"email": email})
        assert user is not None
        await log_action(user["_id"], "signup", {"email": email, "method": "google"})
    elif "google" not in user.get("authProvider", "local"):
        # Existing local-password account signing in with Google for the
        # first time - link the accounts, leave passwordHash untouched so
        # the original password keeps working.
        await db.users.update_one(
            {"_id": user["_id"]},
            {"$set": {"authProvider": "local+google", "googleId": google_id, "updatedAt": now}},
        )
        user = await db.users.find_one({"_id": user["_id"]})
        assert user is not None
        await log_action(user["_id"], "google_account_linked", {"email": email})
    else:
        await log_action(user["_id"], "login", {"email": email, "method": "google"})

    token = sign_token(str(user["_id"]), user["tokenVersion"], user["role"])
    return TokenResponse(token=token, user=_user_out(user))


@router.get("/me", response_model=dict)
async def get_me(current_user: CurrentUser = Depends(get_current_user)) -> dict:
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
    current_user: CurrentUser = Depends(get_current_user),
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

    if err := validate_password(body.new_password, user.get("username"), user.get("email")):
        raise HTTPException(status_code=400, detail=err)

    new_hash = hash_password(body.new_password)
    new_token_version = user["tokenVersion"] + 1
    await db.users.update_one(
        {"_id": current_user.id},
        {
            "$set": {
                "passwordHash": new_hash,
                "tokenVersion": new_token_version,
                "updatedAt": datetime.now(UTC),
            }
        },
    )
    user["passwordHash"] = new_hash
    user["tokenVersion"] = new_token_version

    # Re-issue a fresh token carrying the new tokenVersion so the tab that
    # just changed the password doesn't get logged out too - only every
    # OTHER previously-issued token is now invalid.
    token = sign_token(str(user["_id"]), new_token_version, user["role"])
    await log_action(user["_id"], "password_change", {"method": "change_password"})
    return TokenResponse(token=token, user=_user_out(user))


@router.post("/forgot-password/verify", response_model=dict)
@limiter.limit("20/15minute")
async def forgot_password_verify(request: Request, body: ForgotPasswordVerifyRequest) -> dict:
    db = get_database()
    user = await db.users.find_one(
        {"username": normalize_username(body.username), "email": normalize_email(body.email)}
    )
    if not user:
        raise HTTPException(status_code=400, detail=GENERIC_FORGOT_PASSWORD_ERROR)
    if _is_google_only(user):
        raise HTTPException(status_code=400, detail=GOOGLE_ONLY_FORGOT_PASSWORD_ERROR)
    return {"verified": True}


@router.post("/forgot-password/reset", response_model=MessageResponse)
@limiter.limit("20/15minute")
async def forgot_password_reset(
    request: Request, body: ForgotPasswordResetRequest
) -> MessageResponse:
    if body.new_password != body.confirm_new_password:
        raise HTTPException(status_code=400, detail="New password and confirmation do not match.")

    db = get_database()
    user = await db.users.find_one(
        {"username": normalize_username(body.username), "email": normalize_email(body.email)}
    )
    if not user:
        raise HTTPException(status_code=400, detail=GENERIC_FORGOT_PASSWORD_ERROR)
    if _is_google_only(user):
        raise HTTPException(status_code=400, detail=GOOGLE_ONLY_FORGOT_PASSWORD_ERROR)

    if err := validate_password(body.new_password, user.get("username"), user.get("email")):
        raise HTTPException(status_code=400, detail=err)

    new_hash = hash_password(body.new_password)
    await db.users.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "passwordHash": new_hash,
                "tokenVersion": user["tokenVersion"] + 1,
                "updatedAt": datetime.now(UTC),
            }
        },
    )
    await log_action(user["_id"], "password_change", {"method": "forgot_password"})
    return MessageResponse(message="Password updated successfully.")
