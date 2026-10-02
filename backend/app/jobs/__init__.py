"""Scheduled jobs.

Production runs ``python -m app.jobs daily`` from a Render Cron Job once a day
(see render.yaml). Every job is idempotent, so running it twice in a day, or
catching up after a missed day, is safe. The same jobs can be triggered over
HTTP with the CRON_SECRET bearer token (POST /api/jobs/{name}).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.services import auth as auth_service
from app.services import payments, renewal

logger = logging.getLogger("kiowa.jobs")


def _renewal_reminders(db: Session) -> dict[str, object]:
    return renewal.send_renewal_reminders(db).__dict__


def _termination_sweep(db: Session) -> dict[str, object]:
    return renewal.run_termination_sweep(db)


def _nra_check(db: Session) -> dict[str, object]:
    return {"suspended": renewal.run_nra_expiration_check(db)}


def _reconcile_payments(db: Session) -> dict[str, object]:
    try:
        return dict(payments.reconcile_pending_payments(db))
    except payments.PaymentsNotConfigured:
        return {"skipped": "Stripe not configured"}


def _purge_sessions(db: Session) -> dict[str, object]:
    removed = auth_service.purge_expired_sessions(db)
    db.commit()
    return {"removed": removed}


JOBS: dict[str, Callable[[Session], dict[str, object]]] = {
    "nra-check": _nra_check,
    "renewal-reminders": _renewal_reminders,
    "termination-sweep": _termination_sweep,
    "reconcile-payments": _reconcile_payments,
    "purge-sessions": _purge_sessions,
}
DAILY = ["nra-check", "renewal-reminders", "termination-sweep", "reconcile-payments", "purge-sessions"]


def run_job(db: Session, name: str) -> dict[str, object]:
    logger.info("job_started", extra={"job": name})
    try:
        result = JOBS[name](db)
    except Exception:
        db.rollback()
        logger.exception("job_failed", extra={"job": name})
        raise
    logger.info("job_finished", extra={"job": name, "result": result})
    return result
