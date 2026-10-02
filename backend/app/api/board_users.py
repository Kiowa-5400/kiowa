"""Board logins: invite, roles, titles, deactivate, unlock, reset. Plus the audit log."""

from __future__ import annotations

import html
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.auth import _link, send_password_link
from app.api.deps import BoardAuth, get_db, request_context, require_board, require_permission
from app.core.permissions import PROTECTED_ROLES, ROLE_LABELS, Permission, can_manage_role
from app.core.timeutil import now_utc
from app.models import AuditLog, BoardUser, Person, PositionOption
from app.schemas.common import APIModel, Email, Message, Name, Page, Phone
from app.services import audit
from app.services import auth as auth_service
from app.services import email as email_service

router = APIRouter(prefix="/api/board", tags=["board: users"])

can_manage = require_permission(Permission.BOARD_MANAGE)
can_audit = require_permission(Permission.AUDIT_VIEW)

Role = Literal["tech_admin", "president", "vice_president", "treasurer", "board_member"]


class BoardUserOut(BaseModel):
    id: int
    person_id: int
    name: str
    email: str
    phone: str | None
    role: str
    role_label: str
    position: str | None
    is_active: bool
    has_password: bool
    locked_until: datetime | None
    failed_login_count: int
    last_login_at: datetime | None
    created_at: datetime
    can_manage: bool


def _out(board_user: BoardUser, actor_role: str) -> BoardUserOut:
    person = board_user.person
    return BoardUserOut(
        id=board_user.id, person_id=person.id, name=person.full_name, email=person.email, phone=person.phone,
        role=board_user.role, role_label=ROLE_LABELS[board_user.role], position=board_user.position,
        is_active=board_user.is_active, has_password=person.password_hash is not None,
        locked_until=person.locked_until if person.locked_until and person.locked_until > now_utc() else None,
        failed_login_count=person.failed_login_count, last_login_at=person.last_login_at,
        created_at=board_user.created_at, can_manage=can_manage_role(actor_role, board_user.role),
    )


@router.get("/roles")
def roles(auth: BoardAuth = Depends(require_board)) -> list[dict[str, object]]:
    return [{"value": r, "label": label, "assignable": can_manage_role(auth.role, r)} for r, label in ROLE_LABELS.items()]


@router.get("/users", response_model=list[BoardUserOut])
def list_board_users(auth: BoardAuth = Depends(can_manage), db: Session = Depends(get_db)) -> list[BoardUserOut]:
    rows = db.scalars(select(BoardUser).join(Person, Person.id == BoardUser.person_id).order_by(BoardUser.is_active.desc(), Person.last_name)).all()
    return [_out(b, auth.role) for b in rows]


class InviteRequest(APIModel):
    first_name: Name
    last_name: Name
    email: Email
    phone: Phone = None
    role: Role = "board_member"
    position: str | None = Field(default=None, max_length=120)


def _count_active(db: Session, role: str, exclude_id: int) -> int:
    return db.scalar(
        select(func.count()).select_from(BoardUser).where(BoardUser.role == role, BoardUser.is_active.is_(True), BoardUser.id != exclude_id)
    ) or 0


@router.post("/users", response_model=BoardUserOut, status_code=status.HTTP_201_CREATED)
def invite_board_user(payload: InviteRequest, request: Request, auth: BoardAuth = Depends(can_manage),
                      db: Session = Depends(get_db)) -> BoardUserOut:
    if not can_manage_role(auth.role, payload.role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Only a technology administrator can grant that role.")
    person = auth_service.find_person_by_email(db, payload.email)
    if person is None:
        # Board members are club members too.
        person = Person(first_name=payload.first_name, last_name=payload.last_name, email=payload.email,
                        phone=payload.phone, membership_status="member", on_board=True)
        db.add(person)
        db.flush()
    elif person.board_user is not None and person.board_user.is_active:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="That person already has board access.")
    person.on_board = True
    board_user = person.board_user
    if board_user is None:
        board_user = BoardUser(person_id=person.id, role=payload.role, position=(payload.position or "").strip() or None,
                               invited_by_id=auth.person.id)
        db.add(board_user)
    else:
        board_user.role, board_user.is_active, board_user.deactivated_at = payload.role, True, None
        board_user.position = (payload.position or "").strip() or board_user.position
    db.flush()
    audit.record(db, actor=auth.person, action="board_user.invited", entity_type="board_user", entity_id=board_user.id,
                 summary=f"Gave {person.full_name} {ROLE_LABELS[payload.role]} access", context=request_context(request))
    if person.password_hash is None:
        token = auth_service.issue_token(db, person, "board_invite")
        db.commit()
        email_service.send_transactional(
            person.email, "You've been added to the Kiowa Gun Club board site",
            f"<p>Hi {html.escape(person.first_name)},</p><p>{html.escape(auth.person.full_name)} added you to the Kiowa Gun Club "
            f"board site as <strong>{ROLE_LABELS[payload.role]}</strong>. Set your password to finish setting up your account.</p>"
            + email_service.button(_link("board", "/accept-invite", token), "Set my password")
            + "<p>This link expires in 7 days.</p>",
        )
    else:
        db.commit()
        email_service.send_transactional(
            person.email, "You now have access to the Kiowa Gun Club board site",
            f"<p>Hi {html.escape(person.first_name)},</p><p>{html.escape(auth.person.full_name)} gave you "
            f"<strong>{ROLE_LABELS[payload.role]}</strong> access to the board site. Sign in with your existing club password.</p>",
        )
    db.refresh(board_user)
    return _out(board_user, auth.role)


class BoardUserUpdate(APIModel):
    role: Role | None = None
    position: str | None = Field(default=None, max_length=120)
    is_active: bool | None = None


def _get_manageable(db: Session, auth: BoardAuth, board_user_id: int) -> BoardUser:
    board_user = db.get(BoardUser, board_user_id)
    if board_user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Board user not found.")
    if not can_manage_role(auth.role, board_user.role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Only a technology administrator can change this login.")
    return board_user


@router.patch("/users/{board_user_id}", response_model=BoardUserOut)
def update_board_user(board_user_id: int, payload: BoardUserUpdate, request: Request, auth: BoardAuth = Depends(can_manage),
                      db: Session = Depends(get_db)) -> BoardUserOut:
    board_user = _get_manageable(db, auth, board_user_id)
    data = payload.model_dump(exclude_unset=True)
    context = request_context(request)
    losing_role = (
        ("role" in data and data["role"] != board_user.role) or ("is_active" in data and not data["is_active"])
    ) and board_user.is_active
    if losing_role and board_user.role in PROTECTED_ROLES and _count_active(db, board_user.role, board_user.id) == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Can't remove the last active {ROLE_LABELS[board_user.role]}. Appoint someone else first.")
    if "is_active" in data and not data["is_active"] and board_user.person_id == auth.person.id:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="You can't deactivate your own login.")
    if "role" in data and data["role"] != board_user.role:
        if not can_manage_role(auth.role, data["role"]):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Only a technology administrator can grant that role.")
        audit.record(db, actor=auth.person, action="board_user.role_changed", entity_type="board_user", entity_id=board_user.id,
                     details={"from": board_user.role, "to": data["role"]}, summary=board_user.person.full_name, context=context)
        board_user.role = data["role"]
    if "position" in data:
        board_user.position = (data["position"] or "").strip() or None
    if "is_active" in data and data["is_active"] != board_user.is_active:
        board_user.is_active = bool(data["is_active"])
        board_user.deactivated_at = None if board_user.is_active else now_utc()
        if not board_user.is_active:
            auth_service.destroy_all_sessions(db, board_user.person_id, realm="board")
        audit.record(db, actor=auth.person, action="board_user." + ("reactivated" if board_user.is_active else "deactivated"),
                     entity_type="board_user", entity_id=board_user.id, summary=board_user.person.full_name, context=context)
    db.commit()
    return _out(board_user, auth.role)


@router.post("/users/{board_user_id}/unlock", response_model=BoardUserOut)
def unlock(board_user_id: int, request: Request, auth: BoardAuth = Depends(can_manage), db: Session = Depends(get_db)) -> BoardUserOut:
    board_user = _get_manageable(db, auth, board_user_id)
    board_user.person.failed_login_count = 0
    board_user.person.locked_until = None
    audit.record(db, actor=auth.person, action="board_user.unlocked", entity_type="board_user", entity_id=board_user.id,
                 context=request_context(request))
    db.commit()
    return _out(board_user, auth.role)


@router.post("/users/{board_user_id}/send-reset", response_model=Message)
def send_reset(board_user_id: int, request: Request, auth: BoardAuth = Depends(can_manage), db: Session = Depends(get_db)) -> Message:
    """Emails a reset link; whoever triggers this never sees the new password."""
    board_user = _get_manageable(db, auth, board_user_id)
    audit.record(db, actor=auth.person, action="board_user.reset_sent", entity_type="board_user", entity_id=board_user.id,
                 context=request_context(request))
    send_password_link(db, board_user.person, "board",
                       intro=f"{html.escape(auth.person.full_name)} sent you a link to set a new board password. Your current password works until you use it.")
    return Message(message=f"Reset link sent to {board_user.person.email}.")


@router.get("/position-options")
def position_options(auth: BoardAuth = Depends(require_board), db: Session = Depends(get_db)) -> list[str]:
    return list(db.scalars(select(PositionOption.label).order_by(PositionOption.label)))


class PositionCreate(APIModel):
    label: str = Field(min_length=1, max_length=120)


@router.post("/position-options", response_model=list[str])
def add_position(payload: PositionCreate, auth: BoardAuth = Depends(can_manage), db: Session = Depends(get_db)) -> list[str]:
    label = payload.label.strip()
    if not db.scalar(select(PositionOption).where(func.lower(PositionOption.label) == label.lower())):
        db.add(PositionOption(label=label))
        db.commit()
    return position_options(auth, db)


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


class AuditOut(BaseModel):
    id: int
    created_at: datetime
    actor_label: str
    action: str
    entity_type: str | None
    entity_id: str | None
    summary: str | None
    details: dict[str, object] | None
    ip_address: str | None


@router.get("/audit", response_model=Page[AuditOut])
def audit_log(
    q: str | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    auth: BoardAuth = Depends(can_audit),
    db: Session = Depends(get_db),
) -> Page[AuditOut]:
    query = select(AuditLog)
    if action:
        query = query.where(AuditLog.action.like(f"{action}%"))
    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)
    if entity_id:
        query = query.where(AuditLog.entity_id == entity_id)
    if q:
        like = f"%{q.lower()}%"
        query = query.where(or_(func.lower(AuditLog.actor_label).like(like), func.lower(func.coalesce(AuditLog.summary, "")).like(like)))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size))
    return Page(
        items=[AuditOut(id=r.id, created_at=r.created_at, actor_label=r.actor_label, action=r.action, entity_type=r.entity_type,
                        entity_id=r.entity_id, summary=r.summary, details=r.details, ip_address=r.ip_address) for r in rows],
        total=total, page=page, page_size=page_size,
    )
