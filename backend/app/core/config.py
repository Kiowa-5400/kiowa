from __future__ import annotations

import os
from functools import lru_cache

from pydantic import BaseModel


class Settings(BaseModel):
    app_env: str = os.getenv("APP_ENV", "development")
    app_secret: str = os.getenv("APP_SECRET", "change-me")
    database_url: str = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/kiowa_gun_club")
    cors_origins: list[str] = [
        origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:4173,http://localhost:5173,http://localhost:4174").split(",") if origin.strip()
    ]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
