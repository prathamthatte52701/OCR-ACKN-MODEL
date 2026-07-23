from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.database import get_database
from app.core.security import decode_token

_bearer_scheme = HTTPBearer(auto_error=False)


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
    user = await db.users.find_one({"_id": user_id}, {"tokenVersion": 1, "role": 1})
    if user is None or user.get("tokenVersion") != payload.get("tokenVersion"):
        raise unauthorized

    return CurrentUser(id=user_id, role=user["role"])


async def require_admin(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """FastAPI equivalent of the old isAdmin middleware: always re-reads role
    from the DB (never trusts the JWT's role claim, which is client-tamperable) -
    get_current_user above already did that DB read, so this just checks it."""
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")
    return current_user
