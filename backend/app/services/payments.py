"""Dues payments: Stripe Checkout, webhook fulfillment, refunds, manual payments.\n\nCheckout uses Stripe automatic payment methods so eligible popular payment methods and wallets can be offered without storing payment credentials.

Board decision carried over from kiowa-gun (2026-08): dues are never
auto-billed and cards are never stored. Every charge is a one-time hosted
Checkout Session the member deliberately completes. Do not add Stripe
subscriptions or saved payment methods.

The Stripe webhook (or a server-to-server retrieval during reconciliation) is
the only thing that marks a payment paid. A browser returning from Checkout
changes nothing.
"""

from __future__ import annotations

import html
import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from typing import Any, Protocol

import stripe
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.timeutil import club_today, format_long_date, now_utc
from app.models import Application, Payment, Person, StripeEvent
from app.services import audit
from app.services import email as email_service
from app.services.audit import RequestContext
from app.services.membership import WorkflowError, evaluate_payment_eligibility, refresh_eligibility, site_settings
from app.services.renewal import next_cutoff_after_payment

logger = logging.getLogger("kiowa.payments")


class PaymentsNotConfigured(Exception):
    pass


class PaymentProviderError(Exception):
    pass


def to_cents(amount: Decimal) -> int:
    return int((Decimal(amount) * 100).quantize(Decimal("1")))


def from_cents(cents: int) -> Decimal:
    return (Decimal(cents) / 100).quantize(Decimal("0.01"))


class PaymentGateway(Protocol):
    def create_checkout_session(self, params: dict[str, Any], idempotency_key: str) -> dict[str, Any]: ...

    def retrieve_checkout_session(self, session_id: str) -> dict[str, Any]: ...

    def create_refund(self, payment_intent_id: str, amount_cents: int, idempotency_key: str) -> dict[str, Any]: ...

    def verify_webhook(self, payload: bytes, signature: str | None) -> dict[str, Any]: ...


class StripeGateway:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.stripe_configured:
            raise PaymentsNotConfigured()
        self._client = stripe.StripeClient(settings.stripe_secret_key, max_network_retries=2)
        self._webhook_secret = settings.stripe_webhook_secret

    def create_checkout_session(self, params: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        try:
            session = self._client.v1.checkout.sessions.create(params=params, options={"idempotency_key": idempotency_key})
        except stripe.StripeError as exc:
            raise PaymentProviderError(exc.user_message or "The payment processor rejected the request.") from exc
        return session.to_dict()

    def retrieve_checkout_session(self, session_id: str) -> dict[str, Any]:
        try:
            return self._client.v1.checkout.sessions.retrieve(session_id).to_dict()
        except stripe.StripeError as exc:
            raise PaymentProviderError(str(exc)) from exc

    def create_refund(self, payment_intent_id: str, amount_cents: int, idempotency_key: str) -> dict[str, Any]:
        try:
            refund = self._client.v1.refunds.create(
                params={"payment_intent": payment_intent_id, "amount": amount_cents},
                options={"idempotency_key": idempotency_key},
            )
        except stripe.StripeError as exc:
            raise PaymentProviderError(exc.user_message or str(exc)) from exc
        return refund.to_dict()

    def verify_webhook(self, payload: bytes, signature: str | None) -> dict[str, Any]:
        # Raises stripe.SignatureVerificationError on a bad/missing/expired signature.
        stripe.Webhook.construct_event(payload, signature or "", self._webhook_secret)
        return json.loads(payload)


@lru_cache(maxsize=1)
def get_gateway() -> PaymentGateway:
    return StripeGateway()


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------


@dataclass
class CheckoutStart:
    payment: Payment
    checkout_url: str


def start_checkout(db: Session, application: Application, person: Person, context: RequestContext) -> CheckoutStart:
    if application.person_id != person.id:
        raise WorkflowError("You can only pay for your own application.", status_code=403)
    eligibility = evaluate_payment_eligibility(db, application)
    refresh_eligibility(db, application)
    if not eligibility.eligible:
        db.commit()
        raise WorkflowError(" ".join(eligibility.reasons), status_code=409)

    gateway = get_gateway()
    settings = get_settings()
    payment = Payment(
        person_id=person.id,
        application_id=application.id,
        amount=eligibility.amount,
        status="pending",
        method="card",
        description="Kiowa Gun Club annual membership dues",
    )
    db.add(payment)
    db.flush()
    portal_url = settings.portal_app_url.rstrip("/")
    session = gateway.create_checkout_session(
        {
            "mode": "payment",
            "customer_email": person.email,
            "client_reference_id": str(payment.id),
            "submit_type": "pay",
            # No payment_method_types: Checkout offers the methods enabled in the Stripe Dashboard.
            # The club collects its own dues; Stripe acting as merchant of record (Managed
            # Payments, on by default for new accounts) would also demand a product tax code.
            "managed_payments": {"enabled": False},
            "line_items": [
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": to_cents(eligibility.amount),
                        "product_data": {"name": "Kiowa Gun Club annual membership dues"},
                    },
                }
            ],
            "metadata": {
                "payment_id": str(payment.id),
                "application_id": str(application.id),
                "person_id": str(person.id),
            },
            "payment_intent_data": {
                "metadata": {"payment_id": str(payment.id), "application_id": str(application.id)},
            },
            "success_url": f"{portal_url}/payments/return?session_id={{CHECKOUT_SESSION_ID}}",
            "cancel_url": f"{portal_url}/applications/{application.id}/pay?cancelled=1",
        },
        idempotency_key=f"kgc-checkout-{payment.id}",
    )
    payment.stripe_checkout_session_id = session["id"]
    application.payment_status = "pending"
    audit.record(db, actor=person, action="payment.checkout_started", entity_type="payment", entity_id=payment.id,
                 details={"amount": str(payment.amount), "application_id": application.id}, context=context)
    db.commit()
    return CheckoutStart(payment=payment, checkout_url=session["url"])


# ---------------------------------------------------------------------------
# Fulfillment (webhook / reconciliation)
# ---------------------------------------------------------------------------


def _apply_membership_payment(db: Session, payment: Payment) -> None:
    """What a successful dues payment does to the member's record."""
    person = payment.person
    settings_row = site_settings(db)
    today = club_today()
    person.renewal_date = next_cutoff_after_payment(settings_row, person.renewal_date, today)
    payment.covers_through = person.renewal_date
    person.membership_status = "member"
    person.terminated_at = None
    if person.member_since is None:
        person.member_since = today
    application = payment.application
    if application is not None:
        application.payment_status = "paid"
        application.status = "completed"
        application.completed_at = now_utc()
        refresh_eligibility(db, application)


def _send_receipt(payment: Payment) -> None:
    person = payment.person
    covers = f" Your membership is now paid through {format_long_date(payment.covers_through)}." if payment.covers_through else ""
    email_service.send_transactional(
        person.email,
        "Kiowa Gun Club dues payment received",
        f"<p>Hi {html.escape(person.first_name)},</p><p>We received your dues payment of "
        f"<strong>${payment.amount:.2f}</strong>.{covers}</p><p>Thank you for being part of the Kiowa Gun Club.</p>",
    )


def fulfill_checkout_session(db: Session, session: dict[str, Any], *, source: str) -> Payment | None:
    """Idempotent: a paid session is recorded once; later calls are no-ops."""
    payment = db.scalar(
        select(Payment).where(Payment.stripe_checkout_session_id == session.get("id")).with_for_update()
    )
    if payment is None:
        payment_id = (session.get("metadata") or {}).get("payment_id")
        if payment_id and str(payment_id).isdigit():
            payment = db.scalar(select(Payment).where(Payment.id == int(payment_id)).with_for_update())
    if payment is None:
        logger.error("stripe_session_unmatched", extra={"session_id": session.get("id")})
        return None
    if payment.status in ("paid", "refunded", "partially_refunded"):
        return payment
    if session.get("payment_status") != "paid":
        return payment

    expected = to_cents(payment.amount)
    if session.get("amount_total") != expected or (session.get("currency") or "usd") != payment.currency:
        payment.status = "failed"
        payment.failure_reason = (
            f"Stripe reported {session.get('amount_total')} {session.get('currency')} but {expected} {payment.currency} was expected."
        )
        audit.record(db, actor=None, action="payment.amount_mismatch", entity_type="payment", entity_id=payment.id,
                     details={"stripe_amount": session.get("amount_total"), "expected": expected})
        logger.error("stripe_amount_mismatch", extra={"payment_id": payment.id})
        return payment

    payment.status = "paid"
    payment.paid_at = now_utc()
    payment.stripe_payment_intent_id = session.get("payment_intent") if isinstance(session.get("payment_intent"), str) else payment.stripe_payment_intent_id
    _apply_membership_payment(db, payment)
    audit.record(db, actor=None, action="payment.succeeded", entity_type="payment", entity_id=payment.id,
                 summary=f"${payment.amount:.2f} dues paid by {payment.person.full_name}",
                 details={"source": source, "application_id": payment.application_id})
    db.flush()
    _send_receipt(payment)
    return payment


def _mark_session(db: Session, session: dict[str, Any], status: str, reason: str) -> None:
    payment = db.scalar(select(Payment).where(Payment.stripe_checkout_session_id == session.get("id")))
    if payment is None or payment.status != "pending":
        return
    payment.status = status
    payment.failure_reason = reason
    if payment.application is not None and payment.application.payment_status == "pending":
        payment.application.payment_status = "unpaid"
    audit.record(db, actor=None, action=f"payment.{status}", entity_type="payment", entity_id=payment.id, summary=reason)


def _apply_refund_totals(db: Session, payment_intent_id: str | None, refunded_cents: int) -> None:
    if not payment_intent_id:
        return
    payment = db.scalar(select(Payment).where(Payment.stripe_payment_intent_id == payment_intent_id))
    if payment is None:
        return
    payment.refunded_amount = from_cents(refunded_cents)
    if payment.refunded_amount >= payment.amount:
        payment.status = "refunded"
        if payment.application is not None:
            payment.application.payment_status = "refunded"
    elif payment.refunded_amount > 0:
        payment.status = "partially_refunded"
    audit.record(db, actor=None, action="payment.refund_recorded", entity_type="payment", entity_id=payment.id,
                 details={"refunded_amount": str(payment.refunded_amount)})


def handle_stripe_event(db: Session, event: dict[str, Any]) -> str:
    """Processes a verified Stripe event exactly once. Returns "processed",
    "duplicate" or "ignored"."""
    event_id = event.get("id")
    event_type = event.get("type", "")
    if not event_id:
        return "ignored"
    try:
        with db.begin_nested():
            db.add(StripeEvent(id=event_id, event_type=event_type))
            db.flush()
    except IntegrityError:
        return "duplicate"

    obj = (event.get("data") or {}).get("object") or {}
    if event_type in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        fulfill_checkout_session(db, obj, source=event_type)
    elif event_type == "checkout.session.async_payment_failed":
        _mark_session(db, obj, "failed", "The bank payment failed.")
    elif event_type == "checkout.session.expired":
        _mark_session(db, obj, "cancelled", "Checkout was abandoned or expired.")
    elif event_type == "charge.refunded":
        _apply_refund_totals(db, obj.get("payment_intent"), int(obj.get("amount_refunded") or 0))
    else:
        db.commit()
        return "ignored"
    db.commit()
    return "processed"


def reconcile_pending_payments(db: Session, *, older_than_minutes: int = 30) -> dict[str, int]:
    """Asks Stripe directly (server-to-server) about card payments still
    pending, in case a webhook delivery was missed."""
    from datetime import timedelta

    gateway = get_gateway()
    cutoff = now_utc() - timedelta(minutes=older_than_minutes)
    pending = db.scalars(
        select(Payment).where(
            Payment.status == "pending",
            Payment.method == "card",
            Payment.stripe_checkout_session_id.is_not(None),
            Payment.created_at < cutoff,
        )
    ).all()
    counts = {"checked": 0, "paid": 0, "cancelled": 0}
    for payment in pending:
        counts["checked"] += 1
        try:
            session = gateway.retrieve_checkout_session(payment.stripe_checkout_session_id or "")
        except PaymentProviderError:
            logger.exception("reconcile_retrieve_failed", extra={"payment_id": payment.id})
            continue
        if session.get("payment_status") == "paid":
            fulfill_checkout_session(db, session, source="reconciliation")
            counts["paid"] += 1
        elif session.get("status") == "expired":
            _mark_session(db, session, "cancelled", "Checkout expired (found during reconciliation).")
            counts["cancelled"] += 1
        db.commit()
    return counts


# ---------------------------------------------------------------------------
# Board actions
# ---------------------------------------------------------------------------


def record_manual_payment(
    db: Session,
    *,
    person: Person,
    application: Application | None,
    amount: Decimal,
    method: str,
    notes: str | None,
    actor: Person,
    context: RequestContext,
) -> Payment:
    """Cash/check dues recorded by the treasurer. Applies the same membership
    effects as an online payment."""
    if method not in ("cash", "check", "other"):
        raise WorkflowError("Manual payments must be cash, check or other.")
    if amount <= 0:
        raise WorkflowError("Amount must be greater than zero.")
    if application is not None:
        if application.person_id != person.id:
            raise WorkflowError("That application belongs to someone else.")
        if application.payment_status == "paid":
            raise WorkflowError("That application is already paid.", status_code=409)
    payment = Payment(
        person_id=person.id,
        application_id=application.id if application else None,
        amount=amount,
        status="paid",
        method=method,
        description="Kiowa Gun Club annual membership dues",
        paid_at=now_utc(),
        recorded_by_id=actor.id,
        notes=(notes or "").strip() or None,
    )
    db.add(payment)
    db.flush()
    db.refresh(payment)
    _apply_membership_payment(db, payment)
    audit.record(db, actor=actor, action="payment.manual_recorded", entity_type="payment", entity_id=payment.id,
                 summary=f"${amount:.2f} {method} payment recorded for {person.full_name}",
                 details={"application_id": payment.application_id}, context=context)
    db.commit()
    _send_receipt(payment)
    return payment


def refund_payment(db: Session, payment: Payment, amount: Decimal, reason: str, actor: Person, context: RequestContext) -> Payment:
    if payment.status not in ("paid", "partially_refunded"):
        raise WorkflowError("Only paid payments can be refunded.", status_code=409)
    remaining = payment.amount - payment.refunded_amount
    if amount <= 0 or amount > remaining:
        raise WorkflowError(f"Refund must be between $0.01 and ${remaining:.2f}.")
    if payment.method == "card":
        if not payment.stripe_payment_intent_id:
            raise WorkflowError("This card payment has no Stripe payment reference to refund.", status_code=409)
        refund = get_gateway().create_refund(
            payment.stripe_payment_intent_id, to_cents(amount),
            idempotency_key=f"kgc-refund-{payment.id}-{to_cents(payment.refunded_amount)}-{to_cents(amount)}",
        )
        if refund.get("status") not in ("succeeded", "pending"):
            raise PaymentProviderError(f"Stripe refund status: {refund.get('status')}")
    payment.refunded_amount = payment.refunded_amount + amount
    payment.status = "refunded" if payment.refunded_amount >= payment.amount else "partially_refunded"
    if payment.status == "refunded" and payment.application is not None:
        payment.application.payment_status = "refunded"
    payment.notes = "\n".join(filter(None, [payment.notes, f"Refund ${amount:.2f}: {reason.strip()}"]))
    audit.record(db, actor=actor, action="payment.refunded", entity_type="payment", entity_id=payment.id,
                 summary=f"Refunded ${amount:.2f} to {payment.person.full_name}", details={"reason": reason}, context=context)
    db.commit()
    return payment
