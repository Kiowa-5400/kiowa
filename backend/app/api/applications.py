"""Board review of applications and private membership documents."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import BoardAuth, get_db, request_context, require_permission
from app.api.member import stream_private_document
from app.api.serializers import (
    board_application_detail,
    board_application_summary,
    document_out,
)
from app.core.permissions import Permission
from app.models import Application, Document, Person
from app.schemas.common import Page
from app.schemas.membership import (
    ApproveRequest,
    BoardApplicationDetail,
    BoardApplicationSummary,
    DeclineRequest,
    DocumentOut,
    DocumentReview,
    InfoRequest,
    NoteCreate,
)
from app.services import audit, membership

router = APIRouter(prefix="/api/board", tags=["board: applications"])

can_review = require_permission(Permission.APPLICATIONS_REVIEW)
can_review_docs = require_permission(Permission.DOCUMENTS_REVIEW)


def _get(db: Session, application_id: int) -> Application:
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Application not found.")
    return application


@router.get("/applications", response_model=Page[BoardApplicationSummary])
def list_applications(
    status_filter: str | None = Query(default=None, alias="status"),
    application_type: Literal["renewal", "waiting_list"] | None = None,
    q: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    auth: BoardAuth = Depends(can_review),
    db: Session = Depends(get_db),
) -> Page[BoardApplicationSummary]:
    query = select(Application).join(Person, Person.id == Application.person_id).where(Application.status != "draft")
    if status_filter == "open":
        query = query.where(Application.status.in_(("submitted", "needs_info", "approved")))
    elif status_filter:
        query = query.where(Application.status == status_filter)
    if application_type:
        query = query.where(Application.application_type == application_type)
    if q:
        like = f"%{q.strip().lower()}%"
        query = query.where(or_(func.lower(Person.first_name + " " + Person.last_name).like(like), func.lower(Person.email).like(like)))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(Application.submitted_at.desc().nulls_last(), Application.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    pending = _pending_by_application(db, [a.id for a in rows])
    return Page(items=[board_application_summary(a, pending.get(a.id, 0)) for a in rows], total=total, page=page, page_size=page_size)


def _pending_by_application(db: Session, ids: list[int]) -> dict[int, int]:
    if not ids:
        return {}
    rows = db.execute(
        select(Document.application_id, func.count())
        .where(Document.application_id.in_(ids), Document.review_status == "pending")
        .group_by(Document.application_id)
    ).all()
    return {app_id: count for app_id, count in rows}


@router.get("/applications/{application_id}", response_model=BoardApplicationDetail)
def get_application(application_id: int, auth: BoardAuth = Depends(can_review), db: Session = Depends(get_db)) -> BoardApplicationDetail:
    return board_application_detail(db, _get(db, application_id))


@router.post("/applications/{application_id}/approve", response_model=BoardApplicationDetail)
def approve(application_id: int, payload: ApproveRequest, request: Request, auth: BoardAuth = Depends(can_review),
            db: Session = Depends(get_db)) -> BoardApplicationDetail:
    application = _get(db, application_id)
    membership.approve_application(
        db, application, auth.person,
        membership.ApprovalOptions(**payload.model_dump()),
        request_context(request),
    )
    db.refresh(application)
    return board_application_detail(db, application)


@router.post("/applications/{application_id}/decline", response_model=BoardApplicationDetail)
def decline(application_id: int, payload: DeclineRequest, request: Request, auth: BoardAuth = Depends(can_review),
            db: Session = Depends(get_db)) -> BoardApplicationDetail:
    application = _get(db, application_id)
    membership.decline_application(db, application, auth.person, payload.reason, payload.notify_applicant, request_context(request))
    return board_application_detail(db, application)


@router.post("/applications/{application_id}/request-info", response_model=BoardApplicationDetail)
def request_info(application_id: int, payload: InfoRequest, request: Request, auth: BoardAuth = Depends(can_review),
                 db: Session = Depends(get_db)) -> BoardApplicationDetail:
    application = _get(db, application_id)
    membership.request_more_information(db, application, auth.person, payload.message, request_context(request))
    return board_application_detail(db, application)


@router.post("/applications/{application_id}/payment-request", response_model=BoardApplicationDetail)
def payment_request(application_id: int, request: Request, auth: BoardAuth = Depends(can_review),
                    db: Session = Depends(get_db)) -> BoardApplicationDetail:
    application = _get(db, application_id)
    membership.send_payment_request(db, application, auth.person, request_context(request))
    return board_application_detail(db, application)


@router.post("/applications/{application_id}/verify-nra", response_model=BoardApplicationDetail)
def verify_nra(application_id: int, request: Request, auth: BoardAuth = Depends(can_review),
               db: Session = Depends(get_db)) -> BoardApplicationDetail:
    application = _get(db, application_id)
    membership.verify_nra(db, application, auth.person, request_context(request))
    membership.refresh_eligibility(db, application)
    db.commit()
    return board_application_detail(db, application)


@router.post("/applications/{application_id}/background-check", response_model=BoardApplicationDetail)
def set_background_check(application_id: int, cleared: bool, request: Request, auth: BoardAuth = Depends(can_review),
                         db: Session = Depends(get_db)) -> BoardApplicationDetail:
    application = _get(db, application_id)
    membership.set_background_check(db, application.person, cleared, auth.person, request_context(request))
    db.commit()
    return board_application_detail(db, application)


@router.post("/applications/{application_id}/discount", response_model=BoardApplicationDetail)
def set_discount(application_id: int, approved: bool, request: Request, auth: BoardAuth = Depends(can_review),
                 db: Session = Depends(get_db)) -> BoardApplicationDetail:
    application = _get(db, application_id)
    if not application.claims_cleanup_discount:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="This application doesn't claim the cleanup discount.")
    if application.payment_status == "paid":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Dues are already paid.")
    application.discount_approved = approved
    membership.refresh_eligibility(db, application)
    audit.record(db, actor=auth.person, action="application.discount_" + ("approved" if approved else "removed"),
                 entity_type="application", entity_id=application.id, context=request_context(request))
    db.commit()
    return board_application_detail(db, application)


@router.post("/applications/{application_id}/notes", response_model=BoardApplicationDetail, status_code=status.HTTP_201_CREATED)
def add_note(application_id: int, payload: NoteCreate, request: Request, auth: BoardAuth = Depends(can_review),
             db: Session = Depends(get_db)) -> BoardApplicationDetail:
    application = _get(db, application_id)
    membership.add_note(db, application, auth.person, payload.body, request_context(request))
    db.commit()
    db.refresh(application)
    return board_application_detail(db, application)


# ---------------------------------------------------------------------------
# Private document review
# ---------------------------------------------------------------------------


class ReviewQueueItem(DocumentOut):
    person_id: int
    person_name: str
    application_status: str | None


@router.get("/documents", response_model=Page[ReviewQueueItem])
def review_queue(
    review_status: Literal["pending", "approved", "rejected"] | None = "pending",
    person_id: int | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    auth: BoardAuth = Depends(can_review_docs),
    db: Session = Depends(get_db),
) -> Page[ReviewQueueItem]:
    query = select(Document).where(Document.purged_at.is_(None))
    if review_status:
        query = query.where(Document.review_status == review_status)
    if person_id:
        query = query.where(Document.person_id == person_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(Document.uploaded_at).offset((page - 1) * page_size).limit(page_size)).all()
    return Page(
        items=[
            ReviewQueueItem(
                **document_out(d).model_dump(),
                person_id=d.person_id,
                person_name=d.person.full_name,
                application_status=d.application.status if d.application else None,
            )
            for d in rows
        ],
        total=total, page=page, page_size=page_size,
    )


@router.post("/documents/{document_id}/review", response_model=DocumentOut)
def review_document(document_id: int, payload: DocumentReview, request: Request, auth: BoardAuth = Depends(can_review_docs),
                    db: Session = Depends(get_db)) -> DocumentOut:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found.")
    membership.review_document(db, document, auth.person, payload.review_status, payload.notes, request_context(request))
    return document_out(document)


@router.get("/documents/{document_id}/file")
def view_document(document_id: int, request: Request, auth: BoardAuth = Depends(can_review_docs),
                  db: Session = Depends(get_db)) -> Response:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found.")
    audit.record(db, actor=auth.person, action="document.viewed", entity_type="document", entity_id=document.id,
                 context=request_context(request))
    db.commit()
    return stream_private_document(document)


