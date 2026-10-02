"""Member-facing routes: profile, applications, document uploads, payments.

Object-level authorization: every lookup is scoped to the signed-in person,
so one member can never read or change another member's records.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import MemberAuth, get_db, request_context, require_member, require_verified_member
from app.api.serializers import application_out, document_out, member_profile, payment_summary
from app.core.config import get_settings
from app.core.timeutil import now_utc
from app.models import Application, Document, Payment
from app.schemas.common import APIModel, Message, ProfileUpdate
from app.schemas.membership import (
    ApplicationDraftUpdate,
    ApplicationOut,
    ApplicationStart,
    ApplicationSubmit,
    DocumentOut,
    FormDefinition,
    PaymentSummary,
    RulesOut,
)
from app.schemas.people import MemberProfile
from app.services import audit, membership, uploads
from app.services import payments as payment_service
from app.services.storage import delete_quietly, get_storage, new_key

router = APIRouter(prefix="/api", tags=["member"])

def rules_out(db: Session) -> RulesOut:
    row = membership.site_settings(db)
    return RulesOut(
        version=row.rules_version,
        rules=list(row.range_rules),
        agreement_clause=row.rules_agreement_clause,
        reporting_clause=row.rules_reporting_clause,
    )


@router.get("/application/form", response_model=FormDefinition)
def form_definition(db: Session = Depends(get_db)) -> FormDefinition:
    row = membership.site_settings(db)
    return FormDefinition(
        application_types=[
            {"value": "renewal", "label": "Renew my membership"},
            {"value": "waiting_list", "label": "Apply for the waiting list"},
        ],
        rules=rules_out(db),
        dues_amount=row.dues_amount,
        cleanup_discount_amount=row.cleanup_discount_amount,
        accepting_waiting_list=row.accepting_waiting_list,
        background_check_url=row.background_check_url,
        max_upload_mb=get_settings().max_upload_mb,
        accepted_file_types=sorted(uploads.MEMBERSHIP_DOCUMENT_TYPES),
    )


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


@router.get("/me", response_model=MemberProfile)
def my_profile(auth: MemberAuth = Depends(require_member), db: Session = Depends(get_db)) -> MemberProfile:
    return member_profile(db, auth.person)


@router.patch("/me", response_model=MemberProfile)
def update_my_profile(payload: ProfileUpdate, request: Request, auth: MemberAuth = Depends(require_member),
                      db: Session = Depends(get_db)) -> MemberProfile:
    data = payload.model_dump(exclude_unset=True)
    _apply_profile(db, auth, data, request)
    db.commit()
    return member_profile(db, auth.person)


def _apply_profile(db: Session, auth: MemberAuth, data: dict[str, object], request: Request) -> None:
    for required in ("first_name", "last_name"):
        if required in data and not data[required]:
            raise membership.WorkflowError(f"{required.replace('_', ' ').capitalize()} is required.", {required: "Required."})
    membership.update_profile(db, auth.person, data, source="member_portal")
    if data:
        audit.record(db, actor=auth.person, action="profile.updated", entity_type="person", entity_id=auth.person.id,
                     details={"fields": sorted(data)}, context=request_context(request))


class EmailPreferences(APIModel):
    email_opt_out: bool


@router.put("/me/email-preferences", response_model=MemberProfile)
def set_email_preferences(payload: EmailPreferences, auth: MemberAuth = Depends(require_member),
                          db: Session = Depends(get_db)) -> MemberProfile:
    person = auth.person
    if payload.email_opt_out != person.email_opt_out:
        person.email_opt_out = payload.email_opt_out
        person.email_opt_out_at = now_utc() if payload.email_opt_out else None
    db.commit()
    return member_profile(db, person)


@router.get("/me/documents", response_model=list[DocumentOut])
def my_documents(auth: MemberAuth = Depends(require_member), db: Session = Depends(get_db)) -> list[DocumentOut]:
    rows = db.scalars(select(Document).where(Document.person_id == auth.person.id).order_by(Document.uploaded_at.desc()))
    return [document_out(d) for d in rows]


@router.get("/me/payments", response_model=list[PaymentSummary])
def my_payments(auth: MemberAuth = Depends(require_member), db: Session = Depends(get_db)) -> list[PaymentSummary]:
    rows = db.scalars(select(Payment).where(Payment.person_id == auth.person.id).order_by(Payment.created_at.desc()))
    return [payment_summary(p) for p in rows]


@router.post("/me/nra-proof", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_nra_proof(
    request: Request,
    file: UploadFile = File(...),
    auth: MemberAuth = Depends(require_verified_member),
    db: Session = Depends(get_db),
) -> DocumentOut:
    """Updated NRA proof outside an application (e.g. after a lapse). Queued
    for board review; it does not reactivate NRA status by itself."""
    document = await _store_document(db, auth, None, "nra_proof", file, request)
    db.commit()
    return document_out(document)


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------


def _own_application(db: Session, auth: MemberAuth, application_id: int) -> Application:
    application = db.get(Application, application_id)
    if application is None or application.person_id != auth.person.id:
        # 404 rather than 403, so ids of other people's applications aren't confirmed.
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Application not found.")
    return application


@router.get("/applications", response_model=list[ApplicationOut])
def my_applications(auth: MemberAuth = Depends(require_member), db: Session = Depends(get_db)) -> list[ApplicationOut]:
    rows = db.scalars(select(Application).where(Application.person_id == auth.person.id).order_by(Application.created_at.desc()))
    return [application_out(db, a) for a in rows]


@router.post("/applications", response_model=ApplicationOut, status_code=status.HTTP_201_CREATED)
def start_application(payload: ApplicationStart, request: Request, auth: MemberAuth = Depends(require_member),
                      db: Session = Depends(get_db)) -> ApplicationOut:
    application = membership.start_application(db, auth.person, payload.application_type)
    audit.record(db, actor=auth.person, action="application.started", entity_type="application", entity_id=application.id,
                 context=request_context(request))
    db.commit()
    db.refresh(application)
    return application_out(db, application)


@router.get("/applications/{application_id}", response_model=ApplicationOut)
def get_application(application_id: int, auth: MemberAuth = Depends(require_member), db: Session = Depends(get_db)) -> ApplicationOut:
    return application_out(db, _own_application(db, auth, application_id))


@router.patch("/applications/{application_id}", response_model=ApplicationOut)
def update_application(application_id: int, payload: ApplicationDraftUpdate, request: Request,
                       auth: MemberAuth = Depends(require_member), db: Session = Depends(get_db)) -> ApplicationOut:
    application = _own_application(db, auth, application_id)
    if application.status not in ("draft", "needs_info"):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="This application can no longer be edited.")
    data = payload.model_dump(exclude_unset=True)
    if "application_type" in data and data["application_type"] != application.application_type:
        if application.status != "draft":
            raise HTTPException(status.HTTP_409_CONFLICT, detail="The application type can't be changed after submitting.")
        membership.start_application(db, auth.person, data["application_type"])
    if "documentation_method" in data:
        application.documentation_method = data["documentation_method"]
    if "claims_cleanup_discount" in data:
        application.claims_cleanup_discount = bool(data["claims_cleanup_discount"]) and application.application_type == "renewal"
    if "applicant_notes" in data:
        application.applicant_notes = (data["applicant_notes"] or "").strip() or None
    if payload.profile is not None:
        _apply_profile(db, auth, payload.profile.model_dump(exclude_unset=True), request)
    db.commit()
    db.refresh(application)
    return application_out(db, application)


@router.post("/applications/{application_id}/submit", response_model=ApplicationOut,
             dependencies=[Depends(require_verified_member)])
def submit_application(application_id: int, payload: ApplicationSubmit, request: Request,
                       auth: MemberAuth = Depends(require_member), db: Session = Depends(get_db)) -> ApplicationOut:
    application = _own_application(db, auth, application_id)
    membership.submit_application(
        db,
        application,
        membership.Signature(
            rules_version=payload.rules_version,
            accept_rules=payload.accept_rules,
            printed_name=payload.printed_name,
            signature_name=payload.signature_name,
        ),
        ip_address=request_context(request).ip_address,
    )
    db.refresh(application)
    return application_out(db, application)


@router.post("/applications/{application_id}/withdraw", response_model=ApplicationOut)
def withdraw_application(application_id: int, request: Request, auth: MemberAuth = Depends(require_member),
                         db: Session = Depends(get_db)) -> ApplicationOut:
    application = _own_application(db, auth, application_id)
    if application.status not in ("draft", "submitted", "needs_info"):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="This application can't be withdrawn now.")
    application.status = "withdrawn"
    if application.application_type == "waiting_list" and auth.person.membership_status == "waiting_list":
        auth.person.membership_status = "non_member"
    audit.record(db, actor=auth.person, action="application.withdrawn", entity_type="application", entity_id=application.id,
                 context=request_context(request))
    db.commit()
    return application_out(db, application)


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


async def _store_document(db: Session, auth: MemberAuth, application: Application | None, document_type: str,
                          file: UploadFile, request: Request) -> Document:
    upload = await uploads.validate_upload(
        file, uploads.MEMBERSHIP_DOCUMENT_TYPES, label=membership.DOCUMENT_LABELS[document_type]
    )
    key = new_key(f"private/documents/{auth.person.id}", upload.extension)
    get_storage().put(key, upload.data, upload.mime_type)
    document = Document(
        person_id=auth.person.id,
        application_id=application.id if application else None,
        document_type=document_type,
        original_filename=upload.original_filename,
        storage_key=key,
        mime_type=upload.mime_type,
        size_bytes=upload.size_bytes,
        sha256=upload.sha256,
        uploaded_by_id=auth.person.id,
    )
    db.add(document)
    db.flush()
    audit.record(db, actor=auth.person, action="document.uploaded", entity_type="document", entity_id=document.id,
                 details={"document_type": document_type, "application_id": document.application_id, "size": upload.size_bytes},
                 context=request_context(request))
    return document


@router.post("/applications/{application_id}/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_application_document(
    application_id: int,
    request: Request,
    document_type: Literal["nra_proof", "background_check", "concealed_carry", "cleanup_discount"] = Form(...),
    file: UploadFile = File(...),
    auth: MemberAuth = Depends(require_member),
    db: Session = Depends(get_db),
) -> DocumentOut:
    application = _own_application(db, auth, application_id)
    if application.status not in ("draft", "needs_info"):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Documents can't be added to this application anymore.")
    allowed = {r["document_type"] for r in membership.document_requirements(application)}
    if document_type not in allowed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="That document type doesn't apply to this application.")
    document = await _store_document(db, auth, application, document_type, file, request)
    db.commit()
    return document_out(document)


@router.delete("/documents/{document_id}", response_model=Message)
def delete_my_document(document_id: int, request: Request, auth: MemberAuth = Depends(require_member),
                       db: Session = Depends(get_db)) -> Message:
    document = db.get(Document, document_id)
    if document is None or document.person_id != auth.person.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found.")
    editable = document.application is not None and document.application.status in ("draft", "needs_info")
    if document.review_status != "pending" or not editable:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="This document has already been submitted for review.")
    delete_quietly(document.storage_key)
    audit.record(db, actor=auth.person, action="document.deleted", entity_type="document", entity_id=document.id,
                 context=request_context(request))
    db.delete(document)
    db.commit()
    return Message(message="Document removed.")


def stream_private_document(document: Document) -> Response:
    if document.purged_at is not None:
        raise HTTPException(status.HTTP_410_GONE, detail="This document has been deleted.")
    data = get_storage().get(document.storage_key)
    disposition = "inline" if document.mime_type.startswith("image/") or document.mime_type == "application/pdf" else "attachment"
    safe_name = "".join(c for c in document.original_filename if c.isalnum() or c in "._- ")[:100] or "document"
    return Response(
        content=data,
        media_type=document.mime_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{safe_name}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox",
        },
    )


@router.get("/documents/{document_id}/file")
def download_my_document(document_id: int, auth: MemberAuth = Depends(require_member), db: Session = Depends(get_db)) -> Response:
    document = db.get(Document, document_id)
    if document is None or document.person_id != auth.person.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return stream_private_document(document)


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------


@router.post("/applications/{application_id}/checkout")
def start_checkout(application_id: int, request: Request, auth: MemberAuth = Depends(require_verified_member),
                   db: Session = Depends(get_db)) -> dict[str, str]:
    application = _own_application(db, auth, application_id)
    try:
        started = payment_service.start_checkout(db, application, auth.person, request_context(request))
    except payment_service.PaymentsNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Online payment isn't available yet. Contact the treasurer to pay another way.") from exc
    except payment_service.PaymentProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=f"The payment processor couldn't start checkout: {exc}") from exc
    return {"checkout_url": started.checkout_url}


@router.get("/payments/checkout-status")
def checkout_status(session_id: str, auth: MemberAuth = Depends(require_member), db: Session = Depends(get_db)) -> dict[str, object]:
    """What the return page polls. Reports the database state only, which is
    changed exclusively by the Stripe webhook / reconciliation."""
    payment = db.scalar(select(Payment).where(Payment.stripe_checkout_session_id == session_id))
    if payment is None or payment.person_id != auth.person.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Payment not found.")
    return {
        "status": payment.status,
        "amount": str(payment.amount),
        "application_id": payment.application_id,
        "covers_through": payment.covers_through.isoformat() if payment.covers_through else None,
    }
