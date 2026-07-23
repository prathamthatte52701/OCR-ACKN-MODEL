import sys

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# A short/guessable JWT secret is brute-forceable offline (HS256 signatures
# can be forged once the secret is recovered) - 32 chars is a conservative
# floor, well under what any reasonable random generator produces (the real
# deployed secret is a 96-char hex string), but enough to reject "secret" /
# "changeme" / "test123"-style values outright instead of trusting deploy-time
# discipline alone.
MIN_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    mongo_uri: str = Field(alias="MONGO_URI")
    mongo_db_name: str = Field(default="docintel_transport", alias="MONGO_DB_NAME")
    jwt_secret: str = Field(alias="JWT_SECRET")
    groq_api_keys: str = Field(default="", alias="GROQ_API_KEYS")
    port: int = Field(default=5002, alias="PORT")
    environment: str = Field(default="development", alias="NODE_ENV")
    model_type: str = Field(default="consignor_consignee", alias="MODEL_TYPE")
    frontend_origin: str = Field(default="http://localhost:5174", alias="FRONTEND_ORIGIN")
    admin_origin: str = Field(default="http://localhost:5175", alias="ADMIN_ORIGIN")
    admin_1_password: str = Field(default="", alias="ADMIN_1_PASSWORD")
    admin_2_password: str = Field(default="", alias="ADMIN_2_PASSWORD")

    @field_validator("jwt_secret")
    @classmethod
    def _validate_jwt_secret_strength(cls, value: str) -> str:
        if len(value) < MIN_JWT_SECRET_LENGTH:
            raise ValueError(
                f"JWT_SECRET must be at least {MIN_JWT_SECRET_LENGTH} characters - "
                'generate one with `python -c "import secrets; print(secrets.token_hex(48))"`.'
            )
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cors_origins(self) -> list[str]:
        # Explicit allow-list, never "*" - both the main app and the separate
        # admin app need their own origin here (previously only frontend_origin
        # existed, so the admin app was never actually covered by CORS at all).
        # Driven entirely by env vars, so deploying to real domains is just
        # setting FRONTEND_ORIGIN/ADMIN_ORIGIN - never hardcode a domain here.
        return [self.frontend_origin, self.admin_origin]


def _load_settings() -> Settings:
    # Fail fast with a clear, operator-readable message on a missing required
    # var (MONGO_URI, JWT_SECRET) instead of either a raw Pydantic traceback
    # or - worse - silently starting with a broken config that only surfaces
    # as a confusing downstream error on the first request.
    try:
        return Settings()  # type: ignore[call-arg]
    except ValidationError as exc:
        missing = [str(err["loc"][0]) for err in exc.errors() if err["type"] == "missing"]
        if missing:
            sys.exit(
                f"ERROR: missing required environment variable(s): {', '.join(missing)}. "
                "Set them in .env before starting - refusing to start with an incomplete config."
            )
        value_errors = [str(err["msg"]) for err in exc.errors() if err["type"] == "value_error"]
        if value_errors:
            sys.exit("ERROR: " + " ".join(value_errors))
        raise


settings = _load_settings()
