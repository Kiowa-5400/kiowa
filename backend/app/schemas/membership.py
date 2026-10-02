from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import APIModel, ProfileUpdate

ApplicationType = Literal["renewal", "waiting_list"]


class RulesOut(BaseModel):
    version: str
    rules: list[str]
    agreement_clause: str
    reporting_clause: str


class DocumentRequirement(BaseModel):
    document_type: str
    label: str
    required: bool
    description: str


class DocumentOut(BaseModel):
    id: int
    document_type: str
    label: str
    original_filename: str
    mime_type: str
    size_bytes: int
    uploaded_at: datetime
    review_status: str
    review_notes: str | None
    reviewed_at: datetime | None
    application_id: int | None
    purged: bool


class PaymentSummary(BaseModel):
    id: int
    amount: Decimal
    status: str
    method: str
    paid_at: datetime | None
    created_at: datetime
    refunded_amount: Decimal
    covers_through: date | None


class EligibilityOut(BaseModel):
    eligible: bool
    reasons: list[str]
    amount: Decimal


class ApplicationOut(BaseModel):
    id: int
    application_type: ApplicationType
    status: str
    status_label: str
    documentation_method: str | None
    claims_cleanup_discount: bool
    applicant_notes: str | None
    rules_version: str | None
    printed_name: str | None
    signature_name: str | None
    signed_at: datetime | None
    submitted_at: datetime | None
    info_request_message: str | None
    decision_reason: str | None
    payment_status: str
    payment_requested_at: datetime | None
    created_at: datetime
    document_requirements: list[DocumentRequirement]
    documents: list[DocumentOut]
    eligibility: EligibilityOut
    payments: list[PaymentSummary]


class ApplicationStart(APIModel):
    application_type: ApplicationType


class ApplicationDraftUpdate(APIModel):
    application_type: ApplicationType | None = None
    documentation_method: Literal["background_check", "concealed_carry"] | None = None
    claims_cleanup_discount: bool | None = None
    applicant_notes: str | None = Field(default=None, max_length=2000)
    profile: ProfileUpdate | None = None


class ApplicationSubmit(APIModel):
    rules_version: str
    accept_rules: bool
    printed_name: str = Field(max_length=200)
    signature_name: str = Field(max_length=200)


class FormDefinition(BaseModel):
    application_types: list[dict[str, str]]
    rules: RulesOut
    dues_amount: Decimal
    cleanup_discount_amount: Decimal
    accepting_waiting_list: bool
    background_check_url: str | None
    max_upload_mb: int
    accepted_file_types: list[str]


# ---- Board -----------------------------------------------------------------


class NoteOut(BaseModel):
    id: int
    body: str
    author_name: str | None
    created_at: datetime


class BoardApplicationSummary(BaseModel):
    id: int
    person_id: int
    applicant_name: str
    applicant_email: str
    application_type: ApplicationType
    status: str
    status_label: str
    submitted_at: datetime | None
    payment_status: str
    payment_eligible: bool
    payment_block_reason: str | None
    pending_documents: int
    created_at: datetime


class BoardApplicationDetail(ApplicationOut):
    person_id: int
    applicant: dict[str, object]
    submitted_profile: dict[str, object] | None
    nra_verified_at: datetime | None
    discount_approved: bool
    background_check_cleared: bool
    reviewed_by: str | None
    reviewed_at: datetime | None
    signature_ip: str | None
    notes: list[NoteOut]


class ApproveRequest(APIModel):
    verify_nra: bool = False
    clear_background_check: bool = False
    approve_discount: bool | None = None
    send_payment_request: bool = True
    note: str | None = Field(default=None, max_length=4000)


class DeclineRequest(APIModel):
    reason: str = Field(default="", max_length=4000)
    notify_applicant: bool = True


class InfoRequest(APIModel):
    message: str = Field(min_length=1, max_length=4000)


class NoteCreate(APIModel):
    body: str = Field(min_length=1, max_length=4000)


class DocumentReview(APIModel):
    review_status: Literal["approved", "rejected", "pending"]
    notes: str | None = Field(default=None, max_length=2000)
