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

    # Browser origins allowed to call the API with credentials (www, portal, apply, board).
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # Public URLs used to build links in emails and Stripe redirects.
    public_site_url: str = "http://localhost:4173"
    portal_app_url: str = "http://localhost:5174"  # member sign-in, account, application status, payment
    apply_app_url: str = "http://localhost:5173"  # the membership application form
    board_app_url: str = "http://localhost:4174"
    api_public_url: str = "http://localhost:8000"

    club_timezone: str = "America/Chicago"

    # Session cookies. Secure defaults to on outside development/test.
    cookie_secure: bool | None = None
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cookie_domain: str | None = None
    session_ttl_hours: int = 8
    remember_session_days: int = 30
    trust_proxy_headers: bool = True
    # How many proxies sit between the internet and the API and append to X-Forwarded-For.
    # Render's load balancer alone is 1; add 1 more if the API domain is also behind Cloudflare's proxy.
    trusted_proxy_count: int = Field(default=1, ge=1, le=5)

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
    # SMS: "httpsms" = the httpSMS Android app sends from the club's phone (httpsms.com);
    # "gateway" = Veriphone carrier lookup + Resend to the carrier email-to-SMS gateway.
    sms_provider: Literal["httpsms", "twilio", "gateway", "console", "disabled"] = "console"
    httpsms_api_key: str = ""
    httpsms_from_number: str = ""  # the club phone running the httpSMS app, e.g. +16205550100
    httpsms_webhook_signing_key: str = ""  # signs delivery-status webhooks (HS256 JWT)
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_messaging_service_sid: str = ""
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
            problems.append("CORS_ORIGINS must list the deployed www, portal, apply and board origins")
        elif any(not origin.startswith("https://") for origin in self.cors_origins):
            problems.append("CORS_ORIGINS must only contain https:// origins in production")
        link_urls = {
            "PUBLIC_SITE_URL": self.public_site_url,
            "PORTAL_APP_URL": self.portal_app_url,
            "APPLY_APP_URL": self.apply_app_url,
            "BOARD_APP_URL": self.board_app_url,
            "API_PUBLIC_URL": self.api_public_url,
        }
        if bad := [name for name, url in link_urls.items() if not url.startswith("https://")]:
            problems.append(f"{', '.join(bad)} must be https:// addresses in production (they build links in emails)")
        if self.cookie_secure is False:
            problems.append("COOKIE_SECURE cannot be disabled in production")
        if self.email_provider == "console":
            problems.append("EMAIL_PROVIDER must be 'resend' (or 'disabled') in production")
        if self.sms_provider == "console":
            problems.append("SMS_PROVIDER must be 'twilio', 'gateway' or 'disabled' in production")
        if self.sms_provider == "httpsms" and (not self.httpsms_api_key or not self.httpsms_from_number):
            problems.append("SMS_PROVIDER=httpsms needs HTTPSMS_API_KEY and HTTPSMS_FROM_NUMBER")
        if self.sms_provider == "twilio" and (not self.twilio_account_sid or not self.twilio_auth_token or not self.twilio_messaging_service_sid):
            problems.append("SMS_PROVIDER=twilio needs TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_MESSAGING_SERVICE_SID")
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

    @property
    def stripe_test_mode(self) -> bool:
        """Stripe keys carry their mode in the prefix (sk_test_/rk_test_ vs sk_live_/rk_live_)."""
        return self.stripe_secret_key.startswith(("sk_test_", "rk_test_"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
