"""Board payment reporting/actions and the Stripe webhook."""

from __future__ import annotations

import logging
from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal

import stripe
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import BoardAuth, get_db, request_context, require_permission
from app.core.config import get_settings
from app.core.permissions import Permission
from app.core.timeutil import club_local_to_utc, club_today
from app.models import Application, Document, Payment, Person
from app.schemas.common import APIModel, Page
from app.services import payments as payment_service

logger = logging.getLogger("kiowa.payments")

router = APIRouter(prefix="/api/board/payments", tags=["board: payments"])
webhook_router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

can_view = require_permission(Permission.PAYMENTS_VIEW)
can_manage = require_permission(Permission.PAYMENTS_MANAGE)


class PaymentRow(BaseModel):
    id: int
    person_id: int
    person_name: str
    person_email: str
    application_id: int | None
    application_type: str | None
    amount: Decimal
    refunded_amount: Decimal
    status: str
    method: str
    paid_at: datetime | None
    created_at: datetime
    covers_through: date | None
    stripe_checkout_session_id: str | None
    stripe_payment_intent_id: str | None
    failure_reason: str | None
    notes: str | None
    claims_discount: bool
    has_discount_document: bool


def _row(payment: Payment, discount_people: set[int]) -> PaymentRow:
    application = payment.application
    return PaymentRow(
        id=payment.id,
        person_id=payment.person_id,
        person_name=payment.person.full_name,
        person_email=payment.person.email,
        application_id=payment.application_id,
        application_type=application.application_type if application else None,
        amount=payment.amount,
        refunded_amount=payment.refunded_amount,
        status=payment.status,
        method=payment.method,
        paid_at=payment.paid_at,
        created_at=payment.created_at,
        covers_through=payment.covers_through,
        stripe_checkout_session_id=payment.stripe_checkout_session_id,
        stripe_payment_intent_id=payment.stripe_payment_intent_id,
        failure_reason=payment.failure_reason,
        notes=payment.notes,
        claims_discount=bool(application and application.claims_cleanup_discount),
        has_discount_document=payment.person_id in discount_people,
    )


@router.get("", response_model=Page[PaymentRow])
def list_payments(
    status_filter: str | None = Query(default=None, alias="status"),
    method: str | None = None,
    q: str | None = None,
    start: date | None = None,
    end: date | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    auth: BoardAuth = Depends(can_view),
    db: Session = Depends(get_db),
) -> Page[PaymentRow]:
    query = select(Payment).join(Person, Person.id == Payment.person_id)
    if status_filter:
        query = query.where(Payment.status == status_filter)
    if method:
        query = query.where(Payment.method == method)
    if q:
        like = f"%{q.strip().lower()}%"
        query = query.where(or_(func.lower(Person.first_name + " " + Person.last_name).like(like), func.lower(Person.email).like(like)))
    if start:
        query = query.where(Payment.created_at >= club_local_to_utc(start, time.min))
    if end:
        query = query.where(Payment.created_at <= club_local_to_utc(end, time.max))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(Payment.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    discount_people = set(
        db.scalars(select(Document.person_id).where(Document.document_type == "cleanup_discount", Document.review_status != "rejected"))
    )
    return Page(items=[_row(p, discount_people) for p in rows], total=total, page=page, page_size=page_size)


@router.get("/summary")
def payment_summary(year: int | None = None, auth: BoardAuth = Depends(can_view), db: Session = Depends(get_db)) -> dict[str, object]:
    year = year or club_today().year
    start = club_local_to_utc(date(year, 1, 1), time.min)
    end = club_local_to_utc(date(year, 12, 31), time.max)
    collected = db.scalar(
        select(func.coalesce(func.sum(Payment.amount - Payment.refunded_amount), 0)).where(
            Payment.status.in_(("paid", "partially_refunded")), Payment.paid_at.between(start, end)
        )
    )
    by_method = db.execute(
        select(Payment.method, func.count(), func.coalesce(func.sum(Payment.amount), 0))
        .where(Payment.status.in_(("paid", "partially_refunded", "refunded")), Payment.paid_at.between(start, end))
        .group_by(Payment.method)
    ).all()
    by_status = db.execute(select(Payment.status, func.count()).group_by(Payment.status)).all()
    by_month = db.execute(
        select(func.date_trunc("month", func.timezone(get_settings().club_timezone, Payment.paid_at)).label("m"), func.sum(Payment.amount))
        .where(Payment.status.in_(("paid", "partially_refunded")), Payment.paid_at.between(start, end))
        .group_by("m").order_by("m")
    ).all()
    refunded = db.scalar(select(func.coalesce(func.sum(Payment.refunded_amount), 0)).where(Payment.paid_at.between(start, end)))
    stale_pending = db.scalar(select(func.count()).select_from(Payment).where(Payment.status == "pending", Payment.method == "card"))
    awaiting = db.scalar(select(func.count()).select_from(Application).where(Application.status == "approved", Application.payment_status != "paid"))
    return {
        "year": year,
        "collected": str(Decimal(collected).quantize(Decimal("0.01"))),
        "refunded": str(Decimal(refunded).quantize(Decimal("0.01"))),
        "by_method": [{"method": m, "count": c, "amount": str(a)} for m, c, a in by_method],
        "by_status": [{"status": s, "count": c} for s, c in by_status],
        "by_month": [{"month": m.date().isoformat()[:7], "amount": str(a)} for m, a in by_month],
        "pending_checkouts": stale_pending,
        "approved_awaiting_payment": awaiting,
    }


class ManualPayment(APIModel):
    person_id: int
    application_id: int | None = None
    amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    method: Literal["cash", "check", "other"]
    notes: str | None = Field(default=None, max_length=1000)


@router.post("/manual", response_model=PaymentRow, status_code=status.HTTP_201_CREATED)
def record_manual(payload: ManualPayment, request: Request, auth: BoardAuth = Depends(can_manage), db: Session = Depends(get_db)) -> PaymentRow:
    person = db.get(Person, payload.person_id)
    if person is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Contact not found.")
    application = db.get(Application, payload.application_id) if payload.application_id else None
    if payload.application_id and application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Application not found.")
    payment = payment_service.record_manual_payment(
        db, person=person, application=application, amount=payload.amount, method=payload.method,
        notes=payload.notes, actor=auth.person, context=request_context(request),
    )
    return _row(payment, set())


class RefundRequest(APIModel):
    amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    reason: str = Field(min_length=1, max_length=500)


@router.post("/{payment_id}/refund", response_model=PaymentRow)
def refund(payment_id: int, payload: RefundRequest, request: Request, auth: BoardAuth = Depends(can_manage),
           db: Session = Depends(get_db)) -> PaymentRow:
    payment = db.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Payment not found.")
    try:
        payment_service.refund_payment(db, payment, payload.amount, payload.reason, auth.person, request_context(request))
    except payment_service.PaymentsNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Stripe isn't configured.") from exc
    except payment_service.PaymentProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=f"Stripe refused the refund: {exc}") from exc
    return _row(payment, set())


@router.post("/reconcile")
def reconcile(auth: BoardAuth = Depends(can_manage), db: Session = Depends(get_db)) -> dict[str, int]:
    try:
        return payment_service.reconcile_pending_payments(db, older_than_minutes=0)
    except payment_service.PaymentsNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Stripe isn't configured.") from exc


@webhook_router.post("/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    payload = await request.body()
    try:
        gateway = payment_service.get_gateway()
        event = gateway.verify_webhook(payload, request.headers.get("stripe-signature"))
    except payment_service.PaymentsNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Stripe isn't configured.") from exc
    except (stripe.SignatureVerificationError, ValueError) as exc:
        logger.warning("stripe_webhook_rejected", extra={"reason": str(exc)[:200]})
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid signature.") from exc
    result = payment_service.handle_stripe_event(db, event)
    logger.info("stripe_webhook", extra={"event_type": event.get("type"), "result": result})
    return {"status": result}
