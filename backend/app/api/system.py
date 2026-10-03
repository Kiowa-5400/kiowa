"""Health checks and the HTTP trigger for scheduled jobs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import get_settings
from app.core.security import constant_time_equals
from app.jobs import DAILY, JOBS, run_job

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness: the process is up. Used as Render's health check."""
    return {"status": "ok"}


@router.get("/health/ready")
def ready(db: Session = Depends(get_db)) -> dict[str, object]:
    """Readiness: the database answers and migrations have been applied."""
    try:
        version = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable or not migrated.") from exc
    settings = get_settings()
    return {
        "status": "ok",
        "migration": version,
        "integrations": {
            "storage": settings.storage_backend,
            "stripe": settings.stripe_configured,
            "email": settings.email_provider,
            "sms": settings.sms_provider,
        },
    }


@router.post("/api/jobs/{name}")
def trigger_job(name: str, request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    secret = get_settings().cron_secret
    header = request.headers.get("authorization", "")
    if not secret or not constant_time_equals(header, f"Bearer {secret}"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Unauthorized.")
    if name == "daily":
        return {job: run_job(db, job) for job in DAILY}
    if name not in JOBS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown job.")
    return {name: run_job(db, name)}
