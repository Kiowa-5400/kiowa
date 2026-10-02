"""Model -> response schema conversion shared by member and board routes."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Application, Document, Payment, Person
from app.schemas.membership import (
    ApplicationOut,
    BoardApplicationDetail,
    BoardApplicationSummary,
    DocumentOut,
    DocumentRequirement,
    EligibilityOut,
    NoteOut,
    PaymentSummary,
)
from app.schemas.people import MemberProfile, PersonDetail, PersonSummary, RenewalInfo
from app.services import membership, renewal
from app.services.people import groups_for


def document_out(document: Document) -> DocumentOut:
    return DocumentOut(
        id=document.id,
        document_type=document.document_type,
        label=membership.DOCUMENT_LABELS[document.document_type],
        original_filename=document.original_filename,
        mime_type=document.mime_type,
        size_bytes=document.size_bytes,
        uploaded_at=document.uploaded_at,
        review_status=document.review_status,
        review_notes=document.review_notes,
        reviewed_at=document.reviewed_at,
        application_id=document.application_id,
        purged=document.purged_at is not None,
    )


def payment_summary(payment: Payment) -> PaymentSummary:
    return PaymentSummary(
        id=payment.id,
        amount=payment.amount,
        status=payment.status,
        method=payment.method,
        paid_at=payment.paid_at,
        created_at=payment.created_at,
        refunded_amount=payment.refunded_amount,
        covers_through=payment.covers_through,
    )


def _application_fields(db: Session, application: Application) -> dict[str, object]:
    eligibility = membership.evaluate_payment_eligibility(db, application)
    return dict(
        id=application.id,
        application_type=application.application_type,
        status=application.status,
        status_label=membership.describe_status(application),
        documentation_method=application.documentation_method,
        claims_cleanup_discount=application.claims_cleanup_discount,
        applicant_notes=application.applicant_notes,
        rules_version=application.rules_version,
        printed_name=application.printed_name,
        signature_name=application.signature_name,
        signed_at=application.signed_at,
        submitted_at=application.submitted_at,
        info_request_message=application.info_request_message,
        decision_reason=application.decision_reason,
        payment_status=application.payment_status,
        payment_requested_at=application.payment_requested_at,
        created_at=application.created_at,
        document_requirements=[DocumentRequirement(**r) for r in membership.document_requirements(application)],
        documents=[document_out(d) for d in sorted(application.documents, key=lambda d: d.uploaded_at)],
        eligibility=EligibilityOut(eligible=eligibility.eligible, reasons=eligibility.reasons, amount=eligibility.amount),
        payments=[payment_summary(p) for p in sorted(application.payments, key=lambda p: p.created_at, reverse=True)],
    )


def application_out(db: Session, application: Application) -> ApplicationOut:
    return ApplicationOut(**_application_fields(db, application))


def board_application_detail(db: Session, application: Application) -> BoardApplicationDetail:
    person = application.person
    return BoardApplicationDetail(
        **_application_fields(db, application),
        person_id=person.id,
        applicant={
            "id": person.id,
            "name": person.full_name,
            "email": person.email,
            "phone": person.phone,
            "membership_status": person.membership_status,
            "nra_number": person.nra_number,
            "nra_expiration_date": person.nra_expiration_date.isoformat() if person.nra_expiration_date else None,
            "nra_active": person.nra_active,
            "email_verified": person.email_verified_at is not None,
        },
        submitted_profile=application.submitted_profile,
        nra_verified_at=application.nra_verified_at,
        discount_approved=application.discount_approved,
        background_check_cleared=person.background_check_cleared,
        reviewed_by=application.reviewed_by.full_name if application.reviewed_by else None,
        reviewed_at=application.reviewed_at,
        signature_ip=application.signature_ip,
        notes=[
            NoteOut(id=n.id, body=n.body, author_name=n.author.full_name if n.author else None, created_at=n.created_at)
            for n in application.notes
        ],
    )


def board_application_summary(application: Application, pending_documents: int) -> BoardApplicationSummary:
    return BoardApplicationSummary(
        id=application.id,
        person_id=application.person_id,
        applicant_name=application.person.full_name,
        applicant_email=application.person.email,
        application_type=application.application_type,
        status=application.status,
        status_label=membership.describe_status(application),
        submitted_at=application.submitted_at,
        payment_status=application.payment_status,
        payment_eligible=application.payment_eligible,
        payment_block_reason=application.payment_block_reason,
        pending_documents=pending_documents,
        created_at=application.created_at,
    )


def member_profile(db: Session, person: Person) -> MemberProfile:
    settings_row = membership.site_settings(db)
    return MemberProfile(
        id=person.id,
        first_name=person.first_name,
        last_name=person.last_name,
        email=person.email,
        phone=person.phone,
        address_line1=person.address_line1,
        address_line2=person.address_line2,
        city=person.city,
        state=person.state,
        zip_code=person.zip_code,
        membership_status=person.membership_status,
        member_since=person.member_since,
        nra_number=person.nra_number,
        nra_expiration_date=person.nra_expiration_date,
        nra_active=person.nra_active,
        background_check_cleared=person.background_check_cleared,
        sms_opt_in=person.sms_opt_in,
        sms_opt_in_at=person.sms_opt_in_at,
        email_opt_out=person.email_opt_out,
        email_verified=person.email_verified_at is not None,
        is_board=bool(person.board_user and person.board_user.is_active),
        renewal=RenewalInfo(**renewal.renewal_summary(settings_row, person)),
    )


def pending_document_counts(db: Session, person_ids: list[int]) -> dict[int, int]:
    if not person_ids:
        return {}
    rows = db.execute(
        select(Document.person_id, func.count())
        .where(Document.person_id.in_(person_ids), Document.review_status == "pending", Document.purged_at.is_(None))
        .group_by(Document.person_id)
    ).all()
    return {person_id: count for person_id, count in rows}


def open_application_statuses(db: Session, person_ids: list[int]) -> dict[int, str]:
    if not person_ids:
        return {}
    rows = db.execute(
        select(Application.person_id, Application.status)
        .where(Application.person_id.in_(person_ids), Application.status.in_(membership.OPEN_STATUSES))
        .order_by(Application.created_at)
    ).all()
    return {person_id: status for person_id, status in rows}


def person_summary(person: Person, pending_docs: int, open_status: str | None) -> PersonSummary:
    return PersonSummary(
        id=person.id,
        first_name=person.first_name,
        last_name=person.last_name,
        email=person.email,
        phone=person.phone,
        city=person.city,
        membership_status=person.membership_status,
        groups=groups_for(person),
        renewal_date=person.renewal_date,
        nra_expiration_date=person.nra_expiration_date,
        nra_active=person.nra_active,
        sms_opt_in=person.sms_opt_in,
        email_opt_out=person.email_opt_out,
        pending_documents=pending_docs,
        open_application_status=open_status,
        has_login=person.password_hash is not None,
    )


def person_detail(db: Session, person: Person) -> PersonDetail:
    pending = pending_document_counts(db, [person.id]).get(person.id, 0)
    open_status = open_application_statuses(db, [person.id]).get(person.id)
    summary = person_summary(person, pending, open_status)
    return PersonDetail(
        **summary.model_dump(),
        address_line1=person.address_line1,
        address_line2=person.address_line2,
        state=person.state,
        zip_code=person.zip_code,
        on_board=person.on_board,
        on_shooting_committee=person.on_shooting_committee,
        member_since=person.member_since,
        terminated_at=person.terminated_at,
        nra_number=person.nra_number,
        background_check_cleared=person.background_check_cleared,
        background_check_cleared_at=person.background_check_cleared_at,
        sms_opt_in_at=person.sms_opt_in_at,
        sms_opt_in_source=person.sms_opt_in_source,
        sms_opt_out_at=person.sms_opt_out_at,
        email_opt_out_at=person.email_opt_out_at,
        email_verified=person.email_verified_at is not None,
        notes=person.notes,
        board_role=person.board_user.role if person.board_user and person.board_user.is_active else None,
        created_at=person.created_at,
        updated_at=person.updated_at,
    )
