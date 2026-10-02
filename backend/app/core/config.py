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
    cors_origins: list[str] = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS").split(",")
        if origin.strip()
    ]
    upload_dir: str = os.getenv("UPLOAD_DIR", str(Path(__file__).resolve().parents[1] / ".private_uploads"))
    max_upload_size_mb: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "5"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
