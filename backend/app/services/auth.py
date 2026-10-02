"""Authentication: password login with lockout, DB-backed sessions, one-time tokens.

There is one credential per person. The same login opens the member portal
(realm "member") and, for people with an active BoardUser row, the board app
(realm "board"). Each realm has its own session cookie.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password, hash_token, new_token, password_needs_rehash, verify_password
from app.core.timeutil import now_utc
from app.models import AuthSession, AuthToken, BoardUser, Person

logger = logging.getLogger("kiowa.auth")

MAX_FAILED_LOGIN_ATTEMPTS = 8
LOCKOUT_DURATION = timedelta(minutes=15)
TOKEN_TTL = {
    "password_reset": timedelta(hours=1),
    "email_verification": timedelta(hours=24),
    "board_invite": timedelta(days=7),
}
# Don't email the same inbox another reset link more often than this.
RESEND_COOLDOWN = timedelta(minutes=2)

SESSION_COOKIES = {"member": "kgc_member_session", "board": "kgc_board_session"}


class LoginError(Exception):
    def __init__(self, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


INVALID_CREDENTIALS = "Invalid email or password."


def normalize_email(email: str) -> str:
    return email.strip().lower()


def find_person_by_email(db: Session, email: str) -> Person | None:
    return db.scalar(select(Person).where(func.lower(Person.email) == normalize_email(email)))


def active_board_user(person: Person | None) -> BoardUser | None:
    if person and person.board_user and person.board_user.is_active:
        return person.board_user
    return None


def authenticate(db: Session, email: str, password: str, realm: str) -> Person:
    """Verifies credentials with lockout. Always pays the full hash cost, so
    response timing doesn't reveal which emails have accounts."""
    person = find_person_by_email(db, email)
    password_ok = verify_password(password, person.password_hash if person else None)

    if person is None or person.password_hash is None:
        raise LoginError(INVALID_CREDENTIALS)

    now = now_utc()
    if person.locked_until and person.locked_until > now:
        raise LoginError("Too many failed sign-in attempts. Try again in a few minutes.", 429)

    if not password_ok:
        person.failed_login_count += 1
        if person.failed_login_count >= MAX_FAILED_LOGIN_ATTEMPTS:
            person.failed_login_count = 0
            person.locked_until = now + LOCKOUT_DURATION
            logger.warning("account_locked", extra={"person_id": person.id})
        db.commit()
        raise LoginError(INVALID_CREDENTIALS)

    if realm == "board" and active_board_user(person) is None:
        raise LoginError(INVALID_CREDENTIALS)
    if realm == "member" and person.email_verified_at is None:
        raise LoginError("Please verify your email address before signing in. Check your inbox for the link.", 403)

    person.failed_login_count = 0
    person.locked_until = None
    person.last_login_at = now
    if password_needs_rehash(person.password_hash):
        person.password_hash = hash_password(password)
    return person


@dataclass
class IssuedSession:
    token: str
    session: AuthSession


def create_session(
    db: Session, person: Person, realm: str, *, remember: bool = False, ip: str | None = None, user_agent: str | None = None
) -> IssuedSession:
    settings = get_settings()
    token = new_token()
    ttl = timedelta(days=settings.remember_session_days) if remember else timedelta(hours=settings.session_ttl_hours)
    session = AuthSession(
        id=hash_token(token),
        person_id=person.id,
        realm=realm,
        csrf_token=new_token(),
        expires_at=now_utc() + ttl,
        ip_address=ip,
        user_agent=(user_agent or "")[:300] or None,
    )
    db.add(session)
    return IssuedSession(token=token, session=session)


def load_session(db: Session, token: str | None, realm: str) -> AuthSession | None:
    if not token:
        return None
    session = db.get(AuthSession, hash_token(token))
    if session is None or session.realm != realm:
        return None
    now = now_utc()
    if session.expires_at <= now:
        db.delete(session)
        db.commit()
        return None
    if now - session.last_seen_at > timedelta(minutes=5):
        session.last_seen_at = now
        db.commit()
    return session


def destroy_session(db: Session, token: str | None) -> None:
    if token:
        db.execute(delete(AuthSession).where(AuthSession.id == hash_token(token)))


def destroy_all_sessions(db: Session, person_id: int, *, except_session_id: str | None = None, realm: str | None = None) -> None:
    statement = delete(AuthSession).where(AuthSession.person_id == person_id)
    if except_session_id:
        statement = statement.where(AuthSession.id != except_session_id)
    if realm:
        statement = statement.where(AuthSession.realm == realm)
    db.execute(statement)


def purge_expired_sessions(db: Session) -> int:
    result = db.execute(delete(AuthSession).where(AuthSession.expires_at <= now_utc()))
    return result.rowcount or 0


# ---------------------------------------------------------------------------
# One-time tokens
# ---------------------------------------------------------------------------


def issue_token(db: Session, person: Person, purpose: str) -> str:
    """Invalidates earlier unused tokens of the same purpose and issues a new one."""
    db.execute(
        update(AuthToken)
        .where(AuthToken.person_id == person.id, AuthToken.purpose == purpose, AuthToken.used_at.is_(None))
        .values(used_at=now_utc())
    )
    token = new_token()
    db.add(
        AuthToken(
            person_id=person.id,
            purpose=purpose,
            token_hash=hash_token(token),
            expires_at=now_utc() + TOKEN_TTL[purpose],
        )
    )
    return token


def recently_issued(db: Session, person: Person, purpose: str) -> bool:
    latest: datetime | None = db.scalar(
        select(func.max(AuthToken.created_at)).where(AuthToken.person_id == person.id, AuthToken.purpose == purpose)
    )
    return latest is not None and now_utc() - latest < RESEND_COOLDOWN


def consume_token(db: Session, token: str, purposes: tuple[str, ...]) -> AuthToken | None:
    row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_token(token)).with_for_update())
    if row is None or row.purpose not in purposes or row.used_at is not None or row.expires_at <= now_utc():
        return None
    row.used_at = now_utc()
    return row


def set_password(db: Session, person: Person, password: str) -> None:
    person.password_hash = hash_password(password)
    person.failed_login_count = 0
    person.locked_until = None
