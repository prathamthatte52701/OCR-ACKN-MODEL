from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.database import get_database
from app.core.security import decode_token

_bearer_scheme = HTTPBearer(auto_error=False)

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
PENDING_MESSAGE = "Waiting for admin approval."
REJECTED_MESSAGE = "Your request was not approved. Contact the admin."


def raise_if_not_approved(user_status: str) -> None:
    if user_status == STATUS_PENDING:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=PENDING_MESSAGE)
    if user_status != STATUS_APPROVED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=REJECTED_MESSAGE)


class CurrentUser:
    def __init__(self, id: ObjectId, role: str):
        self.id = id
        self.role = role


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> CurrentUser:
    """FastAPI equivalent of the old requireAuth middleware: verifies the JWT,
    then re-reads tokenVersion from the DB and rejects if it no longer
    matches - this is the session-revocation check (password change /
    soft-delete invalidate every previously-issued token even before natural
    expiry)."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired session. Please log in again.",
    )
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Please log in to continue."
        )

    payload = decode_token(credentials.credentials)
    if payload is None:
        raise unauthorized

    try:
        user_id = ObjectId(payload.get("userId"))
    except (InvalidId, TypeError):
        raise unauthorized from None

    db = get_database()
    user = await db.users.find_one({"_id": user_id}, {"tokenVersion": 1, "role": 1, "status": 1})
    if user is None or user.get("tokenVersion") != payload.get("tokenVersion"):
        raise unauthorized

    # Single enforcement point for the admin-approval gate: every protected
    # route depends on this function, so a pending/rejected account is locked
    # out everywhere, including with an old token. A missing status field
    # means a pre-approval-era account, which stays approved.
    raise_if_not_approved(user.get("status", STATUS_APPROVED))

    return CurrentUser(id=user_id, role=user["role"])


async def require_admin(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """FastAPI equivalent of the old isAdmin middleware: always re-reads role
    from the DB (never trusts the JWT's role claim, which is client-tamperable) -
    get_current_user above already did that DB read, so this just checks it."""
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")
    return current_user
