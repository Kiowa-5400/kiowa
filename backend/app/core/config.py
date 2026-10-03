"""Application configuration, loaded from environment variables.

Every credential comes from the environment (Render secrets in production,
``backend/.env`` locally). Nothing secret has a default value here.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    secret_key: str = ""
    database_url: str = ""

    # Browser origins allowed to call the API with credentials (www, apply, board).
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # Public URLs used to build links in emails and Stripe redirects.
    public_site_url: str = "http://localhost:4173"
    apply_app_url: str = "http://localhost:5173"
    board_app_url: str = "http://localhost:4174"
    api_public_url: str = "http://localhost:8000"

    club_timezone: str = "America/Chicago"

    # "board" puts the public site and the apply app behind a board sign-in
    # (pre-launch preview). Set to "public" at launch.
    site_access: Literal["public", "board"] = "public"

    # Session cookies. Secure defaults to on outside development/test.
    cookie_secure: bool | None = None
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cookie_domain: str | None = None
    session_ttl_hours: int = 8
    remember_session_days: int = 30
    trust_proxy_headers: bool = True

    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    # File storage. Render's paid persistent disk is mounted at this path in production.
    # Local development defaults to a project-local directory.
    storage_backend: Literal["local"] = "local"
    local_storage_dir: str = ".storage"

    max_upload_mb: int = 10

    # Email
    email_provider: Literal["resend", "console", "disabled"] = "console"
    resend_api_key: str = ""
    resend_webhook_secret: str = ""
    email_from_address: str = "no-reply@kiowagunclub.org"
    email_from_name: str = "Kiowa Gun Club"
    email_reply_to: str = ""

    # SMS
    # SMS: "gateway" = Veriphone carrier lookup + Resend to the carrier email-to-SMS gateway.
    sms_provider: Literal["telnyx", "gateway", "console", "disabled"] = "console"
    telnyx_api_key: str = ""
    telnyx_messaging_profile_id: str = ""
    telnyx_from_number: str = ""
    telnyx_webhook_public_key: str = ""
    veriphone_api_key: str = ""
    sms_from_name: str = "Kiowa Gun Club"
    sms_from_address: str = ""  # defaults to EMAIL_FROM_ADDRESS

    # Scheduled jobs triggered over HTTP must present this bearer token.
    cron_secret: str = ""

    # Optional external error monitoring.
    sentry_dsn: str = ""

    # First-deployment administrator (see `python -m app.cli bootstrap-admin`).
    bootstrap_admin_email: str = ""
    bootstrap_admin_name: str = ""
    bootstrap_admin_password: str = ""

    log_level: str = "INFO"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip().rstrip("/") for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        # Render hands out postgres:// URLs; SQLAlchemy needs the psycopg driver named.
        if value.startswith("postgres://"):
            value = "postgresql+psycopg://" + value[len("postgres://") :]
        elif value.startswith("postgresql://"):
            value = "postgresql+psycopg://" + value[len("postgresql://") :]
        return value

    @model_validator(mode="after")
    def _validate_production(self) -> Settings:
        if self.app_env != "production":
            return self
        problems: list[str] = []
        if len(self.secret_key) < 32:
            problems.append("SECRET_KEY must be set to at least 32 random characters")
        if not self.database_url.startswith("postgresql"):
            problems.append("DATABASE_URL must point at PostgreSQL")
        if self.storage_backend != "local":
            problems.append("STORAGE_BACKEND must be 'local' when using the Render persistent disk")
        if not self.local_storage_dir:
            problems.append("LOCAL_STORAGE_DIR must be set")
        if not self.cors_origins:
            problems.append("CORS_ORIGINS must list the deployed www, apply and board origins")
        elif any(not origin.startswith("https://") for origin in self.cors_origins):
            problems.append("CORS_ORIGINS must only contain https:// origins in production")
        if self.cookie_secure is False:
            problems.append("COOKIE_SECURE cannot be disabled in production")
        if self.email_provider == "console":
            problems.append("EMAIL_PROVIDER must be 'resend' (or 'disabled') in production")
        if self.sms_provider == "console":
            problems.append("SMS_PROVIDER must be 'telnyx', 'gateway' or 'disabled' in production")
        if self.sms_provider == "telnyx" and (not self.telnyx_api_key or not self.telnyx_from_number):
            problems.append("SMS_PROVIDER=telnyx needs TELNYX_API_KEY and TELNYX_FROM_NUMBER")
        if self.sms_provider == "gateway" and (not self.veriphone_api_key or self.email_provider != "resend"):
            problems.append("SMS_PROVIDER=gateway needs VERIPHONE_API_KEY and EMAIL_PROVIDER=resend")
        if problems:
            raise ValueError("Invalid production configuration: " + "; ".join(problems))
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def secure_cookies(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.app_env == "production"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def stripe_configured(self) -> bool:
        return bool(self.stripe_secret_key and self.stripe_webhook_secret)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
