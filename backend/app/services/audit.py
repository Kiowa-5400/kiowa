"""Audit trail for privileged actions.

Callers pass only non-sensitive details: never passwords, tokens, payment
secrets, or document contents.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import request_id_var
from app.models import AuditLog, Person

logger = logging.getLogger("kiowa.audit")

_SENSITIVE_KEYS = {"password", "token", "secret", "card", "csrf", "password_hash"}


@dataclass(frozen=True)
class RequestContext:
    ip_address: str | None = None
    user_agent: str | None = None


def _scrub(details: dict[str, Any] | None) -> dict[str, Any] | None:
    if not details:
        return details
    return {k: v for k, v in details.items() if not any(s in k.lower() for s in _SENSITIVE_KEYS)}


def record(
    db: Session,
    *,
    actor: Person | None,
    action: str,
    entity_type: str | None = None,
    entity_id: object | None = None,
    summary: str | None = None,
    details: dict[str, Any] | None = None,
    context: RequestContext | None = None,
    actor_label: str | None = None,
) -> AuditLog:
    """Adds an audit row to the current transaction (committed with the change it describes)."""
    entry = AuditLog(
        actor_id=actor.id if actor else None,
        actor_label=actor_label or (f"{actor.full_name} <{actor.email}>" if actor else "system"),
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        summary=summary,
        details=_scrub(details),
        ip_address=context.ip_address if context else None,
        user_agent=(context.user_agent or "")[:300] if context else None,
        request_id=request_id_var.get(),
    )
    db.add(entry)
    logger.info("audit", extra={"action": action, "entity_type": entity_type, "entity_id": entry.entity_id})
    return entry
