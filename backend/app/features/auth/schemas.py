from pydantic import Field

from app.core.base_model import CamelModel

# Hard ceilings on every request field. The real rules live in validators.py
# (username 3-8, email RFC 254, password 8-64 / 72 bytes) and give friendly
# messages; these exist so an oversize body is rejected at parse time (422)
# instead of being hashed, regex-scanned or stored. Passwords get headroom
# (128) so over-long NEW passwords still reach validate_password's message.
MAX_USERNAME = 64
MAX_EMAIL = 254
MAX_PASSWORD = 128
MAX_ID_TOKEN = 4096

Username = Field(max_length=MAX_USERNAME)
Email = Field(max_length=MAX_EMAIL)
Password = Field(max_length=MAX_PASSWORD)


class SignupRequest(CamelModel):
    username: str = Username
    email: str = Email
    password: str = Password


class LoginRequest(CamelModel):
    email: str = Email
    password: str = Password


class GoogleLoginRequest(CamelModel):
    id_token: str = Field(max_length=MAX_ID_TOKEN)


class UpdateProfileRequest(CamelModel):
    username: str | None = Field(default=None, max_length=MAX_USERNAME)
    email: str | None = Field(default=None, max_length=MAX_EMAIL)


class ChangePasswordRequest(CamelModel):
    current_password: str = Password
    new_password: str = Password
    confirm_new_password: str | None = Field(default=None, max_length=MAX_PASSWORD)


class ForgotPasswordVerifyRequest(CamelModel):
    username: str = Username
    email: str = Email


class ForgotPasswordResetRequest(CamelModel):
    username: str = Username
    email: str = Email
    new_password: str = Password
    confirm_new_password: str | None = Field(default=None, max_length=MAX_PASSWORD)


class UserOut(CamelModel):
    id: str
    username: str
    email: str
    role: str


class TokenResponse(CamelModel):
    token: str
    user: UserOut
    # True exactly once: on the first password login after an admin approved the account.
    just_approved: bool = False


class MessageResponse(CamelModel):
    message: str
