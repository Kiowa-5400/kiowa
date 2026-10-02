from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel


def _default_database_url() -> str:
    db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "kiowa.db"))
    return f"sqlite:///{db_path}"


class Settings(BaseModel):
    app_env: str = os.getenv("APP_ENV", "development")
    app_secret: str = os.getenv("APP_SECRET")
    secret_key: str = os.getenv("SECRET_KEY", os.getenv("APP_SECRET"))
    database_url: str = os.getenv("DATABASE_URL", _default_database_url())
    stripe_webhook_secret: str = os.getenv("STRIPE_WEBHOOK_SECRET")
    stripe_secret_key: str = os.getenv("STRIPE_SECRET_KEY")
    cors_origins: list[str] = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "").split(",") if origin.strip()]
    upload_dir: str = os.getenv("UPLOAD_DIR", str(Path(__file__).resolve().parents[1] / ".private_uploads"))
    max_upload_size_mb: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "5"))

    veriphone_api_key: str | None = os.getenv("VERIPHONE_API_KEY")
    veriphone_api_url: str = os.getenv("VERIPHONE_API_URL", "https://api.veriphone.io/v2/verify")
    veriphone_default_country: str = os.getenv("VERIPHONE_DEFAULT_COUNTRY", "US")
    veriphone_timeout_seconds: float = float(os.getenv("VERIPHONE_TIMEOUT_SECONDS", "8"))

    smtp_host: str | None = os.getenv("SMTP_HOST")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_username: str | None = os.getenv("SMTP_USERNAME")
    smtp_password: str | None = os.getenv("SMTP_PASSWORD")
    smtp_starttls: bool = os.getenv("SMTP_STARTTLS", "true").lower() in {"1", "true", "yes"}
    smtp_timeout_seconds: float = float(os.getenv("SMTP_TIMEOUT_SECONDS", "10"))
    email_from: str | None = os.getenv("EMAIL_FROM")
    notification_subject: str = os.getenv("NOTIFICATION_SUBJECT", "Kiowa Gun Club application notification")

    # JSON object mapping Veriphone carrier-name fragments to email-to-SMS
    # gateway domains or address templates. Example:
    # {"t-mobile": "tmomail.net", "verizon": "vtext.com"}
    # Keep this configurable because carrier gateways can change.
    sms_gateway_map: str = os.getenv("SMS_GATEWAY_MAP", "{}")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
