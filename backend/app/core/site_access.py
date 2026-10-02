"""Pre-launch preview gate (SITE_ACCESS=board).

While enabled, every API route except the board app's own routes, provider
webhooks, scheduled jobs and health checks requires a signed-in, active
board user. The www and apply apps receive 401 ``preview_locked`` and show a
"private preview" screen linking to the board sign-in. Set SITE_ACCESS=public
at launch to open the site.
"""

from __future__ import annotations

from fastapi import Request

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.services import auth as auth_service

ALWAYS_OPEN_PREFIXES = ("/api/board/", "/api/webhooks/", "/api/jobs/", "/api/site-access", "/health")


def gate_applies(path: str) -> bool:
    return get_settings().site_access == "board" and not path.startswith(ALWAYS_OPEN_PREFIXES)


def has_board_session(request: Request) -> bool:
    token = request.cookies.get(auth_service.SESSION_COOKIES["board"])
    if not token:
        return False
    with get_sessionmaker()() as db:
        session = auth_service.load_session(db, token, "board")
        return session is not None and auth_service.active_board_user(session.person) is not None
