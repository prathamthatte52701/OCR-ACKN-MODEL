import sys

from pydantic import Field, ValidationError, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# A short/guessable JWT secret is brute-forceable offline (HS256 signatures
# can be forged once the secret is recovered) - 32 chars is a conservative
# floor, well under what any reasonable random generator produces (the real
# deployed secret is a 96-char hex string), but enough to reject "secret" /
# "changeme" / "test123"-style values outright instead of trusting deploy-time
# discipline alone.
MIN_JWT_SECRET_LENGTH = 32
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
DEFAULT_DB_NAME = "ackn_AI_model"
DEFAULT_FRONTEND_ORIGIN = "http://localhost:5174"
DEFAULT_ADMIN_ORIGIN = "http://localhost:5175"
DEFAULT_AUDIT_LOG_RETENTION_DAYS = 365


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    mongo_uri: str = Field(alias="MONGO_URI")
    mongo_db_name: str = Field(default=DEFAULT_DB_NAME, alias="MONGO_DB_NAME")
    jwt_secret: str = Field(alias="JWT_SECRET")
    groq_api_keys: str = Field(default="", alias="GROQ_API_KEYS")
    # Groq has already retired a model once; the model name must be changeable without a deploy.
    # Blank = the default. A bad name is NOT replaced by another model: the failure is reported.
    groq_model: str = Field(default=DEFAULT_GROQ_MODEL, alias="GROQ_MODEL")
    # Unset = "high". Set but blank = None = do not send the parameter
    # (models without a reasoning mode reject it with a 400).
    groq_reasoning_effort: str | None = Field(default="high", alias="GROQ_REASONING_EFFORT")
    groq_max_tokens: int = Field(default=2000, alias="GROQ_MAX_TOKENS")
    frontend_origin: str = Field(default=DEFAULT_FRONTEND_ORIGIN, alias="FRONTEND_ORIGIN")
    admin_origin: str = Field(default=DEFAULT_ADMIN_ORIGIN, alias="ADMIN_ORIGIN")
    admin_1_password: str = Field(default="", alias="ADMIN_1_PASSWORD")
    admin_2_password: str = Field(default="", alias="ADMIN_2_PASSWORD")
    # Seed-only identities (see app/scripts/seed_admin.py) - kept out of source so
    # no real person's name/email is committed to the repo.
    admin_1_name: str = Field(default="", alias="ADMIN_1_NAME")
    admin_1_email: str = Field(default="", alias="ADMIN_1_EMAIL")
    admin_2_name: str = Field(default="", alias="ADMIN_2_NAME")
    admin_2_email: str = Field(default="", alias="ADMIN_2_EMAIL")
    # Swagger/ReDoc/openapi.json hand over a full map of the API, so they are OFF
    # unless explicitly enabled (ENABLE_DOCS=true), in every environment.
    enable_docs: bool = Field(default=False, alias="ENABLE_DOCS")
    google_client_id: str = Field(default="", alias="GOOGLE_CLIENT_ID")
    # Audit entries older than this many days are deleted by MongoDB (TTL index). 0 = keep forever.
    audit_log_retention_days: int = Field(
        default=DEFAULT_AUDIT_LOG_RETENTION_DAYS, alias="AUDIT_LOG_RETENTION_DAYS"
    )

    @field_validator("mongo_uri", mode="before")
    @classmethod
    def _require_mongo_uri(cls, value: object) -> object:
        # Required: a blank MONGO_URI (e.g. a copied .env.example) must stop the start with a
        # clear message, not become an empty string that fails later inside the driver.
        if not isinstance(value, str) or not value.strip():
            raise ValueError("MONGO_URI is required and must not be blank.")
        return value.strip()

    @field_validator("mongo_db_name", "frontend_origin", "admin_origin", mode="before")
    @classmethod
    def _blank_means_default(cls, value: object, info: ValidationInfo) -> object:
        # .env.example ships these optional lines blank (or commented out); blank/whitespace
        # means "use the default", exactly like ENABLE_DOCS / GROQ_MODEL above. Real values are
        # only stripped of surrounding spaces.
        defaults = {
            "mongo_db_name": DEFAULT_DB_NAME,
            "frontend_origin": DEFAULT_FRONTEND_ORIGIN,
            "admin_origin": DEFAULT_ADMIN_ORIGIN,
        }
        if not isinstance(value, str) or not value.strip():
            return defaults[str(info.field_name)]
        return value.strip()

    @field_validator("enable_docs", mode="before")
    @classmethod
    def _blank_means_off(cls, value: object) -> object:
        # .env.example ships `ENABLE_DOCS=` blank; that must mean "off", not a
        # boot-time bool-parsing crash.
        return False if isinstance(value, str) and not value.strip() else value

    @field_validator("groq_model", mode="before")
    @classmethod
    def _clean_groq_model(cls, value: object) -> object:
        if not isinstance(value, str) or not value.strip():
            return DEFAULT_GROQ_MODEL
        value = value.strip()
        if len(value) > 100 or any(ch.isspace() for ch in value):
            raise ValueError(
                "GROQ_MODEL must be a model name without spaces (at most 100 characters)."
            )
        return value

    @field_validator("groq_reasoning_effort", mode="before")
    @classmethod
    def _clean_reasoning_effort(cls, value: object) -> object:
        if not isinstance(value, str) or not value.strip():
            return None
        value = value.strip().lower()
        if value not in ("low", "medium", "high"):
            raise ValueError(
                "GROQ_REASONING_EFFORT must be low, medium or high (or blank to not send it)."
            )
        return value

    @field_validator("groq_max_tokens", mode="before")
    @classmethod
    def _clean_max_tokens(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return 2000
        text = str(value).strip()
        if not text.isascii() or not text.isdigit() or not 50 <= int(text) <= 4000:
            raise ValueError("GROQ_MAX_TOKENS must be a whole number from 50 to 4000.")
        return int(text)

    @field_validator("audit_log_retention_days", mode="before")
    @classmethod
    def _clean_audit_retention(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return DEFAULT_AUDIT_LOG_RETENTION_DAYS
        text = str(value).strip()
        if not text.isascii() or not text.isdigit() or int(text) > 3650:
            raise ValueError("AUDIT_LOG_RETENTION_DAYS must be a whole number from 0 to 3650.")
        return int(text)

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
    def docs_enabled(self) -> bool:
        return self.enable_docs

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
