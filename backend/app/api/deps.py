"""Request dependencies: database session, authentication, CSRF and authorization."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.permissions import Permission, has_permission, permissions_for
from app.core.ratelimit import client_ip
from app.core.security import constant_time_equals
from app.db.session import get_db
from app.models import AuthSession, BoardUser, Person
from app.services import auth as auth_service
from app.services.audit import RequestContext

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}



def request_context(request: Request) -> RequestContext:
    return RequestContext(ip_address=client_ip(request), user_agent=request.headers.get("user-agent"))


def set_session_cookie(response: Response, realm: str, token: str, *, persistent: bool, max_age: int) -> None:
    settings = get_settings()
    response.set_cookie(
        auth_service.SESSION_COOKIES[realm],
        token,
        httponly=True,
        secure=settings.secure_cookies,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain or None,
        path="/",
        # A non-"remember me" login is a browser-session cookie (cleared on close);
        # the server-side session still expires on its own schedule.
        max_age=max_age if persistent else None,
    )


def clear_session_cookie(response: Response, realm: str) -> None:
    settings = get_settings()
    response.delete_cookie(
        auth_service.SESSION_COOKIES[realm],
        path="/",
        domain=settings.cookie_domain or None,
        secure=settings.secure_cookies,
        httponly=True,
        samesite=settings.cookie_samesite,
    )


@dataclass
class MemberAuth:
    person: Person
    session: AuthSession
    token: str


@dataclass
class BoardAuth:
    person: Person
    board_user: BoardUser
    session: AuthSession
    token: str

    @property
    def role(self) -> str:
        return self.board_user.role

    def can(self, permission: Permission) -> bool:
        return has_permission(self.board_user.role, permission)

    @property
    def permissions(self) -> list[str]:
        return sorted(p.value for p in permissions_for(self.board_user.role))


def _check_csrf(request: Request, session: AuthSession) -> None:
    if request.method in UNSAFE_METHODS:
        header = request.headers.get("x-csrf-token", "")
        if not header or not constant_time_equals(header, session.csrf_token):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your session token is missing or stale. Refresh the page and try again.")


def _load(request: Request, db: Session, realm: str) -> tuple[AuthSession, str]:
    token = request.cookies.get(auth_service.SESSION_COOKIES[realm])
    session = auth_service.load_session(db, token, realm)
    if session is None or token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Please sign in.")
    _check_csrf(request, session)
    return session, token


def require_member(request: Request, db: Session = Depends(get_db)) -> MemberAuth:
    session, token = _load(request, db, "member")
    return MemberAuth(person=session.person, session=session, token=token)


def require_verified_member(auth: MemberAuth = Depends(require_member)) -> MemberAuth:
    if auth.person.email_verified_at is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Please verify your email address first.")
    return auth


def require_board(request: Request, db: Session = Depends(get_db)) -> BoardAuth:
    session, token = _load(request, db, "board")
    board_user = auth_service.active_board_user(session.person)
    if board_user is None:
        # Access was revoked after sign-in.
        db.delete(session)
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Board access has been revoked.")
    return BoardAuth(person=session.person, board_user=board_user, session=session, token=token)


def require_permission(permission: Permission):
    def dependency(auth: BoardAuth = Depends(require_board)) -> BoardAuth:
        if not auth.can(permission):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your board role doesn't allow this action.")
        return auth

    return dependency
