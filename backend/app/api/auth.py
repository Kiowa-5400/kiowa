"""Sign-in, registration, password and email-verification flows.

Member realm: /api/auth/*  (member portal and application apps)
Board realm:  /api/board/auth/*  (board app)
Both realms share one credential per person and one set of reset links.
"""

from __future__ import annotations

import html

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import (
    BoardAuth,
    MemberAuth,
    clear_session_cookie,
    get_db,
    request_context,
    require_board,
    require_member,
    set_session_cookie,
)
from app.api.serializers import member_profile
from app.core.config import get_settings
from app.core.permissions import ROLE_LABELS, permissions_for
from app.core.ratelimit import client_ip, rate_limit
from app.core.security import validate_new_password, verify_password
from app.core.timeutil import now_utc
from app.models import Person
from app.schemas.common import APIModel, Email, Message, Name, Phone
from app.schemas.people import MemberProfile
from app.services import audit
from app.services import auth as auth_service
from app.services import email as email_service

router = APIRouter(prefix="/api/auth", tags=["auth"])
board_router = APIRouter(prefix="/api/board/auth", tags=["board auth"])

GENERIC_RESET = "If that email has an account, we've sent a link to set a new password. It expires in 1 hour."
GENERIC_REGISTER = "Check your email for a link to verify your address and finish setting up your account."


class LoginRequest(APIModel):
    email: Email
    password: str = Field(max_length=256)
    remember: bool = False


class RegisterRequest(APIModel):
    first_name: Name
    last_name: Name
    email: Email
    password: str = Field(max_length=256)
    phone: Phone = None


class EmailOnly(APIModel):
    email: Email


class ResetRequest(APIModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(max_length=256)


class ChangePasswordRequest(APIModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class TokenOnly(APIModel):
    token: str = Field(min_length=10, max_length=200)


class SessionOut(BaseModel):
    csrf_token: str
    profile: MemberProfile


class BoardSessionOut(BaseModel):
    csrf_token: str
    person: dict[str, object]
    role: str
    role_label: str
    position: str | None
    permissions: list[str]


def _link(app: str, path: str, token: str) -> str:
    settings = get_settings()
    base = settings.board_app_url if app == "board" else settings.portal_app_url
    return f"{base.rstrip('/')}{path}?token={token}"


def send_verification_email(db: Session, person: Person) -> None:
    token = auth_service.issue_token(db, person, "email_verification")
    db.commit()
    email_service.send_transactional(
        person.email,
        "Verify your email for the Kiowa Gun Club member portal",
        f"<p>Hi {html.escape(person.first_name)},</p><p>Please confirm this is your email address to finish setting up "
        f"your Kiowa Gun Club account.</p>"
        + email_service.button(_link("portal", "/verify-email", token), "Verify my email")
        + "<p>This link expires in 24 hours. If you didn't create an account, you can ignore this message.</p>",
    )


def send_password_link(db: Session, person: Person, app: str, *, intro: str) -> None:
    token = auth_service.issue_token(db, person, "password_reset")
    db.commit()
    email_service.send_transactional(
        person.email,
        "Set your Kiowa Gun Club password",
        f"<p>Hi {html.escape(person.first_name)},</p><p>{intro}</p>"
        + email_service.button(_link(app, "/reset-password", token), "Set my password")
        + "<p>This link expires in 1 hour. If you didn't ask for this, you can ignore it — nothing changes until the link is used.</p>",
    )


def _issue_session(db: Session, response: Response, request: Request, person: Person, realm: str, remember: bool) -> str:
    settings = get_settings()
    issued = auth_service.create_session(
        db, person, realm, remember=remember, ip=client_ip(request), user_agent=request.headers.get("user-agent")
    )
    max_age = settings.remember_session_days * 86400 if remember else settings.session_ttl_hours * 3600
    set_session_cookie(response, realm, issued.token, persistent=remember, max_age=max_age)
    return issued.session.csrf_token


def board_session_payload(person: Person, csrf_token: str) -> BoardSessionOut:
    board_user = person.board_user
    assert board_user is not None

    return BoardSessionOut(
        csrf_token=csrf_token,
        person={"id": person.id, "first_name": person.first_name, "last_name": person.last_name, "email": person.email},
        role=board_user.role,
        role_label=ROLE_LABELS[board_user.role],
        position=board_user.position,
        permissions=sorted(p.value for p in permissions_for(board_user.role)),
    )


# ---------------------------------------------------------------------------
# Member realm
# ---------------------------------------------------------------------------


@router.post("/register", status_code=status.HTTP_202_ACCEPTED, response_model=Message,
             dependencies=[Depends(rate_limit("register", 5, 600))])
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> Message:
    """Always answers the same way, so registration can't be used to discover
    which emails have accounts. Existing contacts claim their record by
    email link instead of setting a password here."""
    if problem := validate_new_password(payload.password):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"message": problem, "errors": {"password": problem}})
    existing = auth_service.find_person_by_email(db, payload.email)
    if existing is None:
        person = Person(
            first_name=payload.first_name,
            last_name=payload.last_name,
            email=payload.email,
            phone=payload.phone,
            membership_status="non_member",
        )
        auth_service.set_password(db, person, payload.password)
        db.add(person)
        db.flush()
        audit.record(db, actor=person, action="account.registered", entity_type="person", entity_id=person.id)
        send_verification_email(db, person)
    elif not auth_service.recently_issued(db, existing, "password_reset"):
        intro = (
            "Someone (hopefully you) tried to create a Kiowa Gun Club account with this email, but you already have one. "
            "Use the link below if you need to set a new password."
            if existing.password_hash
            else "The club already has your contact information on file. Use the link below to set a password and access the member portal."
        )
        send_password_link(db, existing, "portal", intro=intro)
    return Message(message=GENERIC_REGISTER)


@router.post("/login", dependencies=[Depends(rate_limit("login", 10, 60))])
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> SessionOut:
    try:
        person = auth_service.authenticate(db, payload.email, payload.password, "member")
    except auth_service.LoginError as exc:
        raise HTTPException(exc.status_code, detail=exc.message) from exc
    csrf = _issue_session(db, response, request, person, "member", payload.remember)
    db.commit()
    return SessionOut(csrf_token=csrf, profile=member_profile(db, person))


@router.post("/logout", response_model=Message)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> Message:
    auth_service.destroy_session(db, request.cookies.get(auth_service.SESSION_COOKIES["member"]))
    db.commit()
    clear_session_cookie(response, "member")
    return Message(message="Signed out.")


@router.get("/session")
def session(auth: MemberAuth = Depends(require_member), db: Session = Depends(get_db)) -> SessionOut:
    return SessionOut(csrf_token=auth.session.csrf_token, profile=member_profile(db, auth.person))


@router.post("/password/forgot", response_model=Message, dependencies=[Depends(rate_limit("forgot", 5, 600))])
def forgot_password(payload: EmailOnly, db: Session = Depends(get_db)) -> Message:
    person = auth_service.find_person_by_email(db, payload.email)
    if person is not None and not auth_service.recently_issued(db, person, "password_reset"):
        send_password_link(db, person, "portal", intro="We received a request to reset the password on your Kiowa Gun Club account.")
    return Message(message=GENERIC_RESET)


def _complete_reset(db: Session, payload: ResetRequest, request: Request) -> Person:
    if problem := validate_new_password(payload.password):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"message": problem, "errors": {"password": problem}})
    row = auth_service.consume_token(db, payload.token, ("password_reset", "board_invite"))
    if row is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="This link is invalid or has expired. Request a new one.")
    person = db.get(Person, row.person_id)
    assert person is not None
    auth_service.set_password(db, person, payload.password)
    # Using an emailed link proves control of the inbox.
    if person.email_verified_at is None:
        person.email_verified_at = now_utc()
    auth_service.destroy_all_sessions(db, person.id)
    audit.record(db, actor=person, action="account.password_reset", entity_type="person", entity_id=person.id,
                 context=request_context(request))
    db.commit()
    return person


@router.post("/password/reset", response_model=Message, dependencies=[Depends(rate_limit("reset", 10, 600))])
def reset_password(payload: ResetRequest, request: Request, db: Session = Depends(get_db)) -> Message:
    _complete_reset(db, payload, request)
    return Message(message="Your password has been set. You can sign in now.")


@router.post("/password/change", response_model=Message)
def change_password(payload: ChangePasswordRequest, request: Request, auth: MemberAuth = Depends(require_member),
                    db: Session = Depends(get_db)) -> Message:
    return _change_password(db, auth.person, auth.session.id, payload, request)


def _change_password(db: Session, person: Person, session_id: str, payload: ChangePasswordRequest, request: Request) -> Message:
    if not verify_password(payload.current_password, person.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Your current password is incorrect.")
    if problem := validate_new_password(payload.new_password):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"message": problem, "errors": {"new_password": problem}})
    auth_service.set_password(db, person, payload.new_password)
    auth_service.destroy_all_sessions(db, person.id, except_session_id=session_id)
    audit.record(db, actor=person, action="account.password_changed", entity_type="person", entity_id=person.id,
                 context=request_context(request))
    db.commit()
    return Message(message="Password updated. Other signed-in devices were signed out.")


@router.post("/email/verify", response_model=Message, dependencies=[Depends(rate_limit("verify", 20, 600))])
def verify_email(payload: TokenOnly, db: Session = Depends(get_db)) -> Message:
    row = auth_service.consume_token(db, payload.token, ("email_verification",))
    if row is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="This verification link is invalid or has expired.")
    person = db.get(Person, row.person_id)
    assert person is not None
    person.email_verified_at = person.email_verified_at or now_utc()
    db.commit()
    return Message(message="Your email is verified. You can sign in now.")


@router.post("/email/resend", response_model=Message, dependencies=[Depends(rate_limit("resend", 5, 600))])
def resend_verification(payload: EmailOnly, db: Session = Depends(get_db)) -> Message:
    person = auth_service.find_person_by_email(db, payload.email)
    if (
        person is not None
        and person.email_verified_at is None
        and person.password_hash is not None
        and not auth_service.recently_issued(db, person, "email_verification")
    ):
        send_verification_email(db, person)
    return Message(message="If that account still needs verification, we've sent a new link.")


# ---------------------------------------------------------------------------
# Board realm
# ---------------------------------------------------------------------------


@board_router.post("/login", dependencies=[Depends(rate_limit("board-login", 10, 60))])
def board_login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> BoardSessionOut:
    try:
        person = auth_service.authenticate(db, payload.email, payload.password, "board")
    except auth_service.LoginError as exc:
        db.commit()
        raise HTTPException(exc.status_code, detail=exc.message) from exc
    csrf = _issue_session(db, response, request, person, "board", payload.remember)
    audit.record(db, actor=person, action="board.signed_in", entity_type="person", entity_id=person.id,
                 context=request_context(request))
    db.commit()
    return board_session_payload(person, csrf)


@board_router.post("/logout", response_model=Message)
def board_logout(request: Request, response: Response, db: Session = Depends(get_db)) -> Message:
    auth_service.destroy_session(db, request.cookies.get(auth_service.SESSION_COOKIES["board"]))
    db.commit()
    clear_session_cookie(response, "board")
    return Message(message="Signed out.")


@board_router.get("/session")
def board_session(auth: BoardAuth = Depends(require_board)) -> BoardSessionOut:
    return board_session_payload(auth.person, auth.session.csrf_token)


@board_router.post("/password/forgot", response_model=Message, dependencies=[Depends(rate_limit("board-forgot", 5, 600))])
def board_forgot_password(payload: EmailOnly, db: Session = Depends(get_db)) -> Message:
    person = auth_service.find_person_by_email(db, payload.email)
    if (
        person is not None
        and auth_service.active_board_user(person) is not None
        and not auth_service.recently_issued(db, person, "password_reset")
    ):
        send_password_link(db, person, "board", intro="We received a request to reset your Kiowa Gun Club board password.")
    return Message(message=GENERIC_RESET)


@board_router.post("/password/reset", response_model=Message, dependencies=[Depends(rate_limit("board-reset", 10, 600))])
def board_reset_password(payload: ResetRequest, request: Request, db: Session = Depends(get_db)) -> Message:
    _complete_reset(db, payload, request)
    return Message(message="Your password has been set. You can sign in now.")


@board_router.post("/password/change", response_model=Message)
def board_change_password(payload: ChangePasswordRequest, request: Request, auth: BoardAuth = Depends(require_board),
                          db: Session = Depends(get_db)) -> Message:
    return _change_password(db, auth.person, auth.session.id, payload, request)
