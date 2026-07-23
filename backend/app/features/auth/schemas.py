from app.core.base_model import CamelModel


class SignupRequest(CamelModel):
    username: str
    email: str
    password: str


class LoginRequest(CamelModel):
    email: str
    password: str


class UpdateProfileRequest(CamelModel):
    username: str | None = None
    email: str | None = None


class ChangePasswordRequest(CamelModel):
    current_password: str
    new_password: str
    confirm_new_password: str | None = None


class ForgotPasswordVerifyRequest(CamelModel):
    username: str
    email: str


class ForgotPasswordResetRequest(CamelModel):
    username: str
    email: str
    new_password: str
    confirm_new_password: str | None = None


class UserOut(CamelModel):
    id: str
    username: str
    email: str
    role: str


class TokenResponse(CamelModel):
    token: str
    user: UserOut


class MessageResponse(CamelModel):
    message: str
