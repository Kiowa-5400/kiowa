from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.common import APIModel, Email, Name, NraNumber, OptionalText, Phone, ProfileUpdate, State, Zip

MembershipStatus = Literal["member", "waiting_list", "non_member", "expired", "terminated"]


class RenewalInfo(BaseModel):
    paid_through: date | None
    next_cutoff: date
    is_current: bool
    days_until_cutoff: int


class MemberProfile(BaseModel):
    """What a member sees about themselves in the portal."""

    id: int
    first_name: str
    last_name: str
    email: str
    phone: str | None
    address_line1: str | None
    address_line2: str | None
    city: str | None
    state: str | None
    zip_code: str | None
    membership_status: MembershipStatus
    member_since: date | None
    nra_number: str | None
    nra_expiration_date: date | None
    nra_active: bool
    background_check_cleared: bool
    sms_opt_in: bool
    sms_opt_in_at: datetime | None
    email_opt_out: bool
    email_verified: bool
    is_board: bool
    renewal: RenewalInfo


class PersonSummary(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: str
    phone: str | None
    city: str | None
    membership_status: MembershipStatus
    groups: list[str]
    renewal_date: date | None
    nra_expiration_date: date | None
    nra_active: bool
    sms_opt_in: bool
    email_opt_out: bool
    pending_documents: int
    open_application_status: str | None
    has_login: bool


class PersonDetail(PersonSummary):
    address_line1: str | None
    address_line2: str | None
    state: str | None
    zip_code: str | None
    on_board: bool
    on_shooting_committee: bool
    member_since: date | None
    terminated_at: datetime | None
    nra_number: str | None
    background_check_cleared: bool
    background_check_cleared_at: datetime | None
    sms_opt_in_at: datetime | None
    sms_opt_in_source: str | None
    sms_opt_out_at: datetime | None
    email_opt_out_at: datetime | None
    email_verified: bool
    notes: str | None
    board_role: str | None
    created_at: datetime
    updated_at: datetime


class PersonCreate(APIModel):
    first_name: Name
    last_name: Name
    email: Email
    phone: Phone = None
    address_line1: OptionalText = None
    address_line2: OptionalText = None
    city: OptionalText = None
    state: State = None
    zip_code: Zip = None
    membership_status: MembershipStatus = "member"
    on_board: bool = False
    on_shooting_committee: bool = False
    renewal_date: date | None = None
    nra_number: NraNumber = None
    nra_expiration_date: date | None = None
    sms_opt_in: bool = False
    notes: str | None = None


class PersonUpdate(ProfileUpdate):
    email: Email | None = None
    membership_status: MembershipStatus | None = None
    on_board: bool | None = None
    on_shooting_committee: bool | None = None
    renewal_date: date | None = None
    nra_active: bool | None = None
    background_check_cleared: bool | None = None
    email_opt_out: bool | None = None
    notes: str | None = None


class CsvImport(APIModel):
    csv: str
    membership_status: MembershipStatus = "member"
