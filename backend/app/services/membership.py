"""Membership workflow: applications, board review, and payment eligibility.

``evaluate_payment_eligibility`` is the single source of truth for whether an
application can be paid (ported from kiowa-gun's recomputeCanPay). Every
payment entry point calls it; the result and reason are also cached on the
application so the board can see why someone can't pay yet.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.timeutil import club_today, format_long_date, now_utc
from app.models import Application, ApplicationNote, Document, Person, SiteSettings
from app.services import audit
from app.services import email as email_service
from app.services import sms as sms_service
from app.services.audit import RequestContext

logger = logging.getLogger("kiowa.membership")

OPEN_STATUSES = ("draft", "submitted", "needs_info", "approved")
DOCUMENT_LABELS = {
    "nra_proof": "Proof of National Rifle Association (NRA) membership",
    "background_check": "Background check cover page",
    "concealed_carry": "Concealed carry license from any state",
    "cleanup_discount": "Range cleanup-day discount card",
    "other": "Other document",
}
NRA_NUMBER_PATTERN = re.compile(r"^\d{5,12}$")


class WorkflowError(Exception):
    """A business-rule violation the user can fix. ``errors`` maps field -> message."""

    def __init__(self, message: str, errors: dict[str, str] | None = None, status_code: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.errors = errors or {}
        self.status_code = status_code


def site_settings(db: Session) -> SiteSettings:
    row = db.get(SiteSettings, 1)
    if row is None:
        raise RuntimeError("Site settings are missing; run the database migrations.")
    return row


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

PROFILE_FIELDS = (
    "first_name", "last_name", "phone", "address_line1", "address_line2", "city", "state", "zip_code",
    "nra_number", "nra_expiration_date",
)


def update_profile(db: Session, person: Person, data: dict[str, Any], *, source: str) -> None:
    """Applies a validated profile update (portal, application, or board).
    SMS consent changes are timestamped with their source as evidence."""
    old_phone = person.phone
    for key in PROFILE_FIELDS:
        if key not in data:
            continue
        value = data[key]
        if isinstance(value, str):
            value = value.strip()
            if not value and key not in ("first_name", "last_name"):
                value = None
        setattr(person, key, value)
    if person.phone != old_phone:
        # The cached carrier belongs to the old number; look it up again next time.
        person.sms_carrier = None
    if "sms_opt_in" in data and data["sms_opt_in"] is not None:
        set_sms_consent(person, bool(data["sms_opt_in"]), source=source)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError as exc:
        if "nra_number" in str(exc.orig):
            raise WorkflowError(
                "That NRA number is already on file for another member. Double-check it and try again.",
                {"nra_number": "Already on file for another member."},
                409,
            ) from exc
        raise


def set_sms_consent(person: Person, opted_in: bool, *, source: str) -> None:
    if opted_in and not person.sms_opt_in:
        person.sms_opt_in = True
        person.sms_opt_in_at = now_utc()
        person.sms_opt_in_source = source
        person.sms_opt_out_at = None
    elif not opted_in and person.sms_opt_in:
        person.sms_opt_in = False
        person.sms_opt_out_at = now_utc()


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------


def open_application(db: Session, person: Person) -> Application | None:
    return db.scalar(
        select(Application)
        .where(Application.person_id == person.id, Application.status.in_(OPEN_STATUSES))
        .order_by(Application.created_at.desc())
    )


def _check_waiting_list_allowed(db: Session, person: Person) -> None:
    if person.membership_status == "member":
        raise WorkflowError("You're already an active member. Choose a membership renewal instead.")
    if not site_settings(db).accepting_waiting_list:
        raise WorkflowError("The club isn't accepting new waiting-list applications right now.")


def _check_renewal_allowed(person: Person) -> None:
    """Renewal skips the waiting list and the background check, so it is only for people the
    club already has as members (current, lapsed or terminated)."""
    if person.membership_status in ("non_member", "waiting_list"):
        raise WorkflowError(
            "Renewal is for current and former members. If you're not a member yet, apply for the waiting list instead.",
            {"application_type": "Not available until you are a member."},
            409,
        )


def start_application(db: Session, person: Person, application_type: str) -> Application:
    existing = open_application(db, person)
    if existing is not None:
        if existing.status == "draft" and existing.application_type != application_type:
            # Switching a draft to another type has to pass the same checks as starting one.
            if application_type == "waiting_list":
                _check_waiting_list_allowed(db, person)
            else:
                _check_renewal_allowed(person)
            existing.application_type = application_type
            existing.documentation_method = None if application_type == "renewal" else existing.documentation_method
            existing.claims_cleanup_discount = False if application_type == "waiting_list" else existing.claims_cleanup_discount
        return existing
    if application_type == "waiting_list":
        _check_waiting_list_allowed(db, person)
    else:
        _check_renewal_allowed(person)
    application = Application(person_id=person.id, application_type=application_type, status="draft")
    db.add(application)
    db.flush()
    return application


def document_requirements(application: Application) -> list[dict[str, Any]]:
    requirements = [
        {
            "document_type": "nra_proof",
            "label": DOCUMENT_LABELS["nra_proof"],
            "required": True,
            "description": "A photo of your current NRA membership card, or the mailing label from an NRA magazine.",
        }
    ]
    if application.application_type == "renewal":
        requirements.append(
            {
                "document_type": "cleanup_discount",
                "label": DOCUMENT_LABELS["cleanup_discount"],
                "required": application.claims_cleanup_discount,
                "description": "Only needed if you're claiming the range cleanup-day discount.",
            }
        )
    else:
        method = application.documentation_method
        requirements.append(
            {
                "document_type": "background_check",
                "label": DOCUMENT_LABELS["background_check"],
                "required": method == "background_check",
                "description": "The cover page of your nationwide background check report.",
            }
        )
        requirements.append(
            {
                "document_type": "concealed_carry",
                "label": DOCUMENT_LABELS["concealed_carry"],
                "required": method == "concealed_carry",
                "description": "A photo of your current concealed carry license. A license from any state is accepted.",
            }
        )
    return requirements


def _usable_documents(application: Application) -> dict[str, list[Document]]:
    by_type: dict[str, list[Document]] = {}
    for document in application.documents:
        if document.review_status != "rejected" and document.purged_at is None:
            by_type.setdefault(document.document_type, []).append(document)
    return by_type


@dataclass
class Signature:
    rules_version: str
    accept_rules: bool
    printed_name: str
    signature_name: str


def submit_application(
    db: Session, application: Application, signature: Signature, *, ip_address: str | None
) -> Application:
    if application.status not in ("draft", "needs_info"):
        raise WorkflowError("This application has already been submitted.", status_code=409)
    person = application.person
    settings_row = site_settings(db)
    errors: dict[str, str] = {}

    for key, label in (("first_name", "First name"), ("last_name", "Last name"), ("phone", "Phone"),
                       ("address_line1", "Street address"), ("city", "City"), ("state", "State"), ("zip_code", "ZIP code")):
        if not (getattr(person, key) or "").strip():
            errors[key] = f"{label} is required."
    if person.nra_expiration_date is None:
        errors["nra_expiration_date"] = "Your NRA membership expiration date is required."
    elif person.nra_expiration_date < club_today():
        errors["nra_expiration_date"] = "Your NRA membership has expired. Renew it with the NRA before applying."
    if application.application_type == "renewal" and not person.nra_number:
        errors["nra_number"] = "Your NRA member number is required for renewal."
    if application.application_type == "waiting_list" and application.documentation_method not in ("background_check", "concealed_carry"):
        errors["documentation_method"] = "Choose whether you're providing a background check or a concealed carry license."

    present = _usable_documents(application)
    for requirement in document_requirements(application):
        if requirement["required"] and requirement["document_type"] not in present:
            errors[f"document_{requirement['document_type']}"] = f"Please upload your {requirement['label'].lower()}."

    if not signature.accept_rules:
        errors["accept_rules"] = "You must read and agree to the Range Rules."
    if signature.rules_version != settings_row.rules_version:
        errors["rules_version"] = "The Range Rules were updated while you were applying. Please review them again."
    printed = " ".join(signature.printed_name.split())
    signed = " ".join(signature.signature_name.split())
    if len(printed.split(" ")) < 2:
        errors["printed_name"] = "Enter your full name (first and last)."
    if not signed or signed.lower() != printed.lower():
        errors["signature_name"] = "Your typed signature must exactly match your printed name."

    if errors:
        raise WorkflowError("Please fix the highlighted items before submitting.", errors)

    now = now_utc()
    application.rules_version = settings_row.rules_version
    application.rules_acknowledged_at = now
    application.printed_name = printed
    application.signature_name = signed
    application.signed_at = now
    application.signature_ip = ip_address
    application.submitted_at = now
    application.status = "submitted"
    application.info_request_message = None
    application.submitted_profile = {
        "first_name": person.first_name,
        "last_name": person.last_name,
        "email": person.email,
        "phone": person.phone,
        "address_line1": person.address_line1,
        "address_line2": person.address_line2,
        "city": person.city,
        "state": person.state,
        "zip_code": person.zip_code,
        "nra_number": person.nra_number,
        "nra_expiration_date": person.nra_expiration_date.isoformat() if person.nra_expiration_date else None,
        "sms_opt_in": person.sms_opt_in,
    }
    if application.application_type == "waiting_list" and person.membership_status in ("non_member", "expired", "terminated"):
        person.membership_status = "waiting_list"
    refresh_eligibility(db, application)
    audit.record(
        db, actor=person, action="application.submitted", entity_type="application", entity_id=application.id,
        summary=f"{person.full_name} submitted a {application.application_type.replace('_', ' ')} application",
        context=RequestContext(ip_address=ip_address),
    )
    db.commit()

    kind = "membership renewal" if application.application_type == "renewal" else "waiting-list application"
    email_service.send_transactional(
        person.email,
        f"We received your Kiowa Gun Club {kind}",
        f"<p>Hi {html.escape(person.first_name)},</p><p>Thanks — your {kind} has been received and is waiting for "
        f"board review. Nothing else is needed from you right now; we'll email you when the board has reviewed it.</p>"
        + email_service.button(_application_link(application), "View your application"),
    )
    return application


def _application_link(application: Application) -> str:
    return f"{get_settings().portal_app_url.rstrip('/')}/applications/{application.id}"


# ---------------------------------------------------------------------------
# Payment eligibility (single source of truth)
# ---------------------------------------------------------------------------


@dataclass
class Eligibility:
    eligible: bool
    reasons: list[str] = field(default_factory=list)
    amount: Decimal = Decimal("0")


def amount_due(settings_row: SiteSettings, application: Application) -> Decimal:
    amount = Decimal(settings_row.dues_amount)
    if application.application_type == "renewal" and application.claims_cleanup_discount and application.discount_approved:
        amount -= Decimal(settings_row.cleanup_discount_amount)
    return max(amount, Decimal("0.00")).quantize(Decimal("0.01"))


def evaluate_payment_eligibility(db: Session, application: Application, today: date | None = None) -> Eligibility:
    today = today or club_today()
    person = application.person
    settings_row = site_settings(db)
    reasons: list[str] = []

    if application.payment_status == "paid" or application.status == "completed":
        reasons.append("Dues for this application have already been paid.")
    elif application.status != "approved":
        reasons.append("The board has not approved this application yet.")
    elif application.payment_requested_at is None:
        reasons.append("The board has not opened payment for this application yet.")

    if person.email_verified_at is None:
        reasons.append("Verify your email address before paying.")
    if application.nra_verified_at is None:
        reasons.append("Your NRA membership proof has not been verified by the board.")
    if not person.nra_active:
        reasons.append("Your NRA membership is not marked active. Upload current NRA proof for board review.")
    if person.nra_expiration_date and person.nra_expiration_date < today:
        reasons.append("Your NRA membership has expired.")
    if application.application_type == "waiting_list" and not person.background_check_cleared:
        reasons.append("Your background check has not been cleared by the board.")

    amount = amount_due(settings_row, application)
    if amount < Decimal("0.50"):
        reasons.append("The amount due is too small to charge online; contact the treasurer.")
    return Eligibility(eligible=not reasons, reasons=reasons, amount=amount)


def refresh_eligibility(db: Session, application: Application) -> Eligibility:
    result = evaluate_payment_eligibility(db, application)
    application.payment_eligible = result.eligible
    application.payment_block_reason = None if result.eligible else " ".join(result.reasons)
    return result


def refresh_open_applications(db: Session, person: Person) -> None:
    for application in person.applications:
        if application.status in OPEN_STATUSES:
            refresh_eligibility(db, application)


# ---------------------------------------------------------------------------
# Board review
# ---------------------------------------------------------------------------


def _require_reviewable(application: Application) -> None:
    if application.status not in ("submitted", "needs_info", "approved"):
        raise WorkflowError(f"This application is {application.status.replace('_', ' ')} and can't be changed.", status_code=409)


def add_note(db: Session, application: Application, author: Person, body: str, context: RequestContext) -> ApplicationNote:
    note = ApplicationNote(application_id=application.id, author_id=author.id, body=body.strip())
    db.add(note)
    audit.record(db, actor=author, action="application.note_added", entity_type="application", entity_id=application.id, context=context)
    return note


def verify_nra(db: Session, application: Application, actor: Person, context: RequestContext) -> None:
    application.nra_verified_at = now_utc()
    application.person.nra_active = True
    audit.record(db, actor=actor, action="application.nra_verified", entity_type="application", entity_id=application.id,
                 summary=f"NRA proof verified for {application.person.full_name}", context=context)


def set_background_check(db: Session, person: Person, cleared: bool, actor: Person, context: RequestContext) -> None:
    if person.background_check_cleared == cleared:
        return
    person.background_check_cleared = cleared
    person.background_check_cleared_at = now_utc() if cleared else None
    audit.record(db, actor=actor, action="member.background_check_" + ("cleared" if cleared else "uncleared"),
                 entity_type="person", entity_id=person.id, summary=person.full_name, context=context)
    refresh_open_applications(db, person)


@dataclass
class ApprovalOptions:
    verify_nra: bool = False
    clear_background_check: bool = False
    approve_discount: bool | None = None
    send_payment_request: bool = True
    note: str | None = None


def approve_application(db: Session, application: Application, actor: Person, options: ApprovalOptions, context: RequestContext) -> Application:
    _require_reviewable(application)
    person = application.person
    if options.verify_nra and application.nra_verified_at is None:
        verify_nra(db, application, actor, context)
    if options.clear_background_check:
        set_background_check(db, person, True, actor, context)
    if options.approve_discount is not None and application.claims_cleanup_discount:
        application.discount_approved = options.approve_discount

    problems: list[str] = []
    if application.nra_verified_at is None:
        problems.append("Verify the applicant's NRA proof before approving.")
    if application.application_type == "waiting_list" and not person.background_check_cleared:
        problems.append("Clear the applicant's background check before approving.")
    if problems:
        raise WorkflowError(" ".join(problems), status_code=409)

    application.status = "approved"
    application.reviewed_by_id = actor.id
    application.reviewed_at = now_utc()
    if options.note:
        add_note(db, application, actor, options.note, context)
    audit.record(db, actor=actor, action="application.approved", entity_type="application", entity_id=application.id,
                 summary=f"Approved {person.full_name}'s {application.application_type.replace('_', ' ')} application",
                 details={"discount_approved": application.discount_approved}, context=context)
    refresh_eligibility(db, application)
    db.commit()
    if options.send_payment_request:
        send_payment_request(db, application, actor, context)
    else:
        email_service.send_transactional(
            person.email, "Your Kiowa Gun Club application was approved",
            f"<p>Hi {html.escape(person.first_name)},</p><p>The board approved your application. "
            f"We'll email you a payment link when dues can be paid.</p>",
        )
    return application


def send_payment_request(db: Session, application: Application, actor: Person, context: RequestContext) -> Application:
    if application.status != "approved":
        raise WorkflowError("Only approved applications can be sent a payment request.", status_code=409)
    application.payment_requested_at = now_utc()
    eligibility = refresh_eligibility(db, application)
    audit.record(db, actor=actor, action="application.payment_requested", entity_type="application", entity_id=application.id,
                 details={"amount": str(eligibility.amount), "eligible": eligibility.eligible}, context=context)
    db.commit()

    person = application.person
    pay_link = f"{_application_link(application)}/pay"
    orientation = ""
    if application.application_type == "waiting_list":
        from app.models import PageSection

        section = db.scalar(select(PageSection).where(PageSection.page_slug == "membership", PageSection.section_key == "orientation"))
        orientation = section.body_html if section else ""
    email_service.send_transactional(
        person.email,
        "Your Kiowa Gun Club application was approved — dues payment",
        f"<p>Hi {html.escape(person.first_name)},</p><p>Good news — the board approved your application. "
        f"Your dues of <strong>${eligibility.amount:.2f}</strong> can now be paid securely online.</p>"
        + email_service.button(pay_link, "Pay dues")
        + orientation,
    )
    if person.sms_opt_in and person.sms_opt_in_at:
        try:
            sms_service.send_to_person(person, f"Kiowa Gun Club: Your application was approved. Pay your dues here: {pay_link}")
        except sms_service.ConsentError:
            pass
    return application


def decline_application(db: Session, application: Application, actor: Person, reason: str, notify: bool, context: RequestContext) -> Application:
    _require_reviewable(application)
    person = application.person
    application.status = "declined"
    application.decision_reason = reason.strip() or None
    application.reviewed_by_id = actor.id
    application.reviewed_at = now_utc()
    application.payment_requested_at = None
    if application.application_type == "waiting_list" and person.membership_status == "waiting_list":
        person.membership_status = "non_member"
    refresh_eligibility(db, application)
    audit.record(db, actor=actor, action="application.declined", entity_type="application", entity_id=application.id,
                 summary=f"Declined {person.full_name}'s application", details={"notified": notify}, context=context)
    db.commit()
    if notify:
        reason_html = f"<p>{html.escape(reason)}</p>" if reason.strip() else ""
        email_service.send_transactional(
            person.email, "An update on your Kiowa Gun Club application",
            f"<p>Hi {html.escape(person.first_name)},</p><p>After review, the board was unable to approve your application at this time.</p>"
            f"{reason_html}<p>If you have questions, please contact the club.</p>",
        )
    return application


def request_more_information(db: Session, application: Application, actor: Person, message: str, context: RequestContext) -> Application:
    _require_reviewable(application)
    if not message.strip():
        raise WorkflowError("Tell the applicant what information is needed.", {"message": "Required."})
    application.status = "needs_info"
    application.info_request_message = message.strip()
    application.payment_requested_at = None
    refresh_eligibility(db, application)
    audit.record(db, actor=actor, action="application.info_requested", entity_type="application", entity_id=application.id, context=context)
    db.commit()
    person = application.person
    email_service.send_transactional(
        person.email, "The Kiowa Gun Club board needs more information",
        f"<p>Hi {html.escape(person.first_name)},</p><p>The board reviewed your application and needs a bit more information:</p>"
        f"<blockquote>{html.escape(message)}</blockquote><p>Please update your application and resubmit it.</p>"
        + email_service.button(_application_link(application), "Update my application"),
    )
    return application


def review_document(db: Session, document: Document, actor: Person, status: str, notes: str | None, context: RequestContext) -> Document:
    """Approving NRA proof verifies NRA for its application; approving a
    background check or CCL clears the person's background check."""
    if status not in ("approved", "rejected", "pending"):
        raise WorkflowError("Invalid review status.")
    document.review_status = status
    document.review_notes = (notes or "").strip() or None
    document.reviewed_by_id = actor.id
    document.reviewed_at = now_utc()
    if status == "approved":
        if document.document_type == "nra_proof" and document.application is not None:
            verify_nra(db, document.application, actor, context)
        elif document.document_type == "nra_proof":
            document.person.nra_active = True
        if document.document_type in ("background_check", "concealed_carry"):
            set_background_check(db, document.person, True, actor, context)
    audit.record(db, actor=actor, action=f"document.{status}", entity_type="document", entity_id=document.id,
                 summary=f"{DOCUMENT_LABELS[document.document_type]} for {document.person.full_name} marked {status}",
                 context=context)
    refresh_open_applications(db, document.person)
    db.commit()
    return document


def describe_status(application: Application) -> str:
    return {
        "draft": "Not submitted yet",
        "submitted": "Waiting for board review",
        "needs_info": "The board needs more information",
        "approved": "Approved — payment pending" if application.payment_requested_at else "Approved",
        "declined": "Not approved",
        "completed": "Complete — dues paid",
        "withdrawn": "Withdrawn",
    }[application.status]


def format_date(value: date | None) -> str | None:
    return format_long_date(value) if value else None
