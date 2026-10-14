"""Board contact database: search, edit, groups, import and export."""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.api.deps import BoardAuth, get_db, request_context, require_permission
from app.api.serializers import (
    board_application_summary,
    document_out,
    open_application_statuses,
    payment_summary,
    pending_document_counts,
    person_detail,
    person_summary,
)
from app.core.permissions import Permission
from app.core.timeutil import club_today, now_utc
from app.models import Application, Document, EmailRecipient, Payment, Person, SmsRecipient
from app.schemas.common import Message, Page
from app.schemas.common import _phone as normalize_phone
from app.schemas.membership import BoardApplicationSummary, DocumentOut, PaymentSummary
from app.schemas.people import CsvImport, PersonCreate, PersonDetail, PersonSummary, PersonUpdate
from app.services import audit, duplicates, membership, roster_import
from app.services.auth import find_person_by_email
from app.services.people import GROUPS, group_condition, search_conditions

router = APIRouter(prefix="/api/board", tags=["board: people"])

can_view = require_permission(Permission.MEMBERS_VIEW)
can_edit = require_permission(Permission.MEMBERS_EDIT)
can_export = require_permission(Permission.MEMBERS_EXPORT)

SORTS = {
    "name": (Person.last_name, Person.first_name),
    "recent": (Person.created_at.desc(),),
    "renewal": (Person.renewal_date.asc().nulls_first(), Person.last_name),
}


@router.get("/people/groups")
def group_counts(auth: BoardAuth = Depends(can_view), db: Session = Depends(get_db)) -> list[dict[str, object]]:
    return [
        {"key": key, "label": label, "count": db.scalar(select(func.count()).select_from(Person).where(group_condition(key))) or 0}
        for key, label in GROUPS.items()
    ]


# ------------------------------------------------------- duplicates ----


def _card(values: Person | dict[str, object], person_id: int) -> dict[str, object]:
    """The few details the board compares when deciding whether two records are one person."""
    get = values.get if isinstance(values, dict) else lambda key: getattr(values, key)
    address = ", ".join(str(v) for v in (get("address_line1"), get("city"), get("state")) if v)
    return {"id": person_id, "first_name": get("first_name"), "last_name": get("last_name"), "email": get("email"),
            "phone": get("phone"), "address": address or None, "membership_status": get("membership_status"),
            "renewal_date": get("renewal_date"), "member_number": get("member_number"), "nra_number": get("nra_number"),
            "has_login": bool(get("password_hash"))}


@router.get("/people/duplicates")
def possible_duplicates(auth: BoardAuth = Depends(can_view), db: Session = Depends(get_db)) -> list[dict[str, object]]:
    return [{"keep": _card(a, a.id), "other": _card(b, b.id)} for a, b in duplicates.all_matches(db)]


@router.get("/people/{person_id}/matches")
def person_matches(person_id: int, auth: BoardAuth = Depends(can_view), db: Session = Depends(get_db)) -> list[dict[str, object]]:
    return [_card(p, p.id) for p in duplicates.matches_for(db, _get(db, person_id))]


def _two(db: Session, person_id: int, other_id: int) -> tuple[Person, Person]:
    if person_id == other_id:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="That's the same record.")
    return duplicates.keeper_first(_get(db, person_id), _get(db, other_id))


@router.get("/people/{person_id}/combine/{other_id}")
def combine_preview(person_id: int, other_id: int, auth: BoardAuth = Depends(can_edit), db: Session = Depends(get_db)) -> dict[str, object]:
    keep, other = _two(db, person_id, other_id)
    result = duplicates.preview(db, keep, other)
    return {"keep": _card(keep, keep.id), "other": _card(other, other.id), "combined": _card(result["values"], keep.id),
            "notes": result["notes"], "problem": result["problem"]}


@router.post("/people/{person_id}/combine/{other_id}")
def combine_people(person_id: int, other_id: int, request: Request, auth: BoardAuth = Depends(can_edit),
                   db: Session = Depends(get_db)) -> dict[str, int]:
    keep, other = _two(db, person_id, other_id)
    try:
        duplicates.combine(db, keep, other, auth.person, request_context(request))
    except duplicates.CombineError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    db.commit()
    return {"person_id": keep.id}


@router.post("/people/{person_id}/not-duplicate/{other_id}", response_model=Message)
def not_duplicate(person_id: int, other_id: int, request: Request, auth: BoardAuth = Depends(can_edit),
                  db: Session = Depends(get_db)) -> Message:
    keep, other = _two(db, person_id, other_id)
    duplicates.mark_different(db, keep, other, auth.person, request_context(request))
    db.commit()
    return Message(message="Got it. They won't be flagged again.")


@router.get("/people", response_model=Page[PersonSummary])
def list_people(
    q: str | None = None,
    group: list[str] = Query(default=[]),
    status_filter: str | None = Query(default=None, alias="status"),
    sms_opt_in: bool | None = None,
    pending_documents: bool | None = None,
    sort: Literal["name", "recent", "renewal"] = "name",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    auth: BoardAuth = Depends(can_view),
    db: Session = Depends(get_db),
) -> Page[PersonSummary]:
    try:
        conditions = search_conditions(q, group, status_filter)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if sms_opt_in is not None:
        conditions.append(Person.sms_opt_in.is_(sms_opt_in))
    if pending_documents:
        conditions.append(
            select(Document.id).where(Document.person_id == Person.id, Document.review_status == "pending", Document.purged_at.is_(None)).exists()
        )
    query = select(Person).where(and_(*conditions)) if conditions else select(Person)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(*SORTS[sort]).offset((page - 1) * page_size).limit(page_size)).all()
    ids = [p.id for p in rows]
    pending = pending_document_counts(db, ids)
    open_status = open_application_statuses(db, ids)
    return Page(
        items=[person_summary(p, pending.get(p.id, 0), open_status.get(p.id)) for p in rows],
        total=total, page=page, page_size=page_size,
    )


def _get(db: Session, person_id: int) -> Person:
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Contact not found.")
    return person


@router.post("/people", response_model=PersonDetail, status_code=status.HTTP_201_CREATED)
def create_person(payload: PersonCreate, request: Request, auth: BoardAuth = Depends(can_edit), db: Session = Depends(get_db)) -> PersonDetail:
    if find_person_by_email(db, payload.email):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="A contact with that email already exists.")
    data = payload.model_dump()
    sms_opt_in = data.pop("sms_opt_in")
    person = Person(**data)
    if person.membership_status == "member" and person.member_since is None:
        person.member_since = club_today()
    db.add(person)
    membership.update_profile(db, person, {"sms_opt_in": sms_opt_in}, source=f"board:{auth.person.id}")
    db.flush()
    audit.record(db, actor=auth.person, action="person.created", entity_type="person", entity_id=person.id,
                 summary=f"Added {person.full_name}", context=request_context(request))
    db.commit()
    return person_detail(db, person)


class PersonRecord(BaseModel):
    person: PersonDetail
    applications: list[BoardApplicationSummary]
    payments: list[PaymentSummary]
    documents: list[DocumentOut]
    communications: list[dict[str, object]]


@router.get("/people/{person_id}", response_model=PersonRecord)
def get_person(person_id: int, auth: BoardAuth = Depends(can_view), db: Session = Depends(get_db)) -> PersonRecord:
    person = _get(db, person_id)
    applications = db.scalars(select(Application).where(Application.person_id == person.id).order_by(Application.created_at.desc())).all()
    payments = db.scalars(select(Payment).where(Payment.person_id == person.id).order_by(Payment.created_at.desc())).all()
    documents = db.scalars(select(Document).where(Document.person_id == person.id).order_by(Document.uploaded_at.desc())).all()
    emails = db.scalars(select(EmailRecipient).where(EmailRecipient.person_id == person.id).order_by(EmailRecipient.id.desc()).limit(25)).all()
    texts = db.scalars(select(SmsRecipient).where(SmsRecipient.person_id == person.id).order_by(SmsRecipient.id.desc()).limit(25)).all()
    comms: list[dict[str, object]] = [
        {"channel": "email", "campaign_id": r.campaign_id, "subject": r.campaign.subject, "status": r.status,
         "sent_at": r.sent_at, "opened_at": r.opened_at} for r in emails
    ] + [
        {"channel": "sms", "campaign_id": r.campaign_id, "subject": r.campaign.body[:80], "status": r.status,
         "sent_at": r.sent_at, "opened_at": None} for r in texts
    ]
    comms.sort(key=lambda c: c["sent_at"] or datetime.min.replace(tzinfo=now_utc().tzinfo), reverse=True)
    return PersonRecord(
        person=person_detail(db, person),
        applications=[board_application_summary(a, 0) for a in applications],
        payments=[payment_summary(p) for p in payments],
        documents=[document_out(d) for d in documents],
        communications=comms,
    )


@router.patch("/people/{person_id}", response_model=PersonDetail)
def update_person(person_id: int, payload: PersonUpdate, request: Request, auth: BoardAuth = Depends(can_edit),
                  db: Session = Depends(get_db)) -> PersonDetail:
    person = _get(db, person_id)
    data = payload.model_dump(exclude_unset=True)
    context = request_context(request)
    changes: dict[str, object] = {}

    # A blank email is ignored: an address can be added or changed here, never removed.
    if data.get("email") and data["email"] != person.email:
        other = find_person_by_email(db, data["email"])
        if other is not None and other.id != person.id:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Another contact already uses that email.")
        changes["email"] = [person.email, data["email"]]
        person.email = data["email"]
        person.email_verified_at = None
    if "membership_status" in data and data["membership_status"] != person.membership_status:
        changes["membership_status"] = [person.membership_status, data["membership_status"]]
        person.membership_status = data["membership_status"]
        if person.membership_status == "member":
            person.terminated_at = None
            person.member_since = person.member_since or club_today()
            membership.close_unneeded_waiting_list(db, person, auth.person, context)
        elif person.membership_status == "terminated":
            person.terminated_at = now_utc()
    for flag in ("on_board", "on_shooting_committee", "nra_active", "nra_life_member", "member_number", "renewal_date", "notes"):
        if flag in data and data[flag] != getattr(person, flag):
            changes[flag] = [str(getattr(person, flag)), str(data[flag])]
            setattr(person, flag, data[flag])
    if "email_opt_out" in data and data["email_opt_out"] != person.email_opt_out:
        person.email_opt_out = bool(data["email_opt_out"])
        person.email_opt_out_at = now_utc() if person.email_opt_out else None
        changes["email_opt_out"] = person.email_opt_out
    if "background_check_cleared" in data and data["background_check_cleared"] is not None:
        membership.set_background_check(db, person, bool(data["background_check_cleared"]), auth.person, context)

    profile = {k: v for k, v in data.items() if k in membership.PROFILE_FIELDS or k == "sms_opt_in"}
    if "sms_opt_in" in profile and profile["sms_opt_in"] != person.sms_opt_in:
        changes["sms_opt_in"] = profile["sms_opt_in"]
    membership.update_profile(db, person, profile, source=f"board:{auth.person.id}")
    changes.update({k: "updated" for k in profile if k != "sms_opt_in"})
    membership.refresh_open_applications(db, person)

    action = "person.status_changed" if "membership_status" in changes else "person.updated"
    audit.record(db, actor=auth.person, action=action, entity_type="person", entity_id=person.id,
                 summary=f"Updated {person.full_name}", details=changes, context=context)
    db.commit()
    return person_detail(db, person)


@router.post("/people/import")
def import_people(payload: CsvImport, request: Request, auth: BoardAuth = Depends(can_edit), db: Session = Depends(get_db)) -> dict[str, object]:
    """Spreadsheet import (ported from kiowa-gun). Takes the app's template or
    the club roster saved as CSV; see services/roster_import.py for the columns.
    Email is the one thing the import doesn't insist on: a row with a name but
    no usable email is added without one. People already on file (same email,
    or same name when the row has no email) are skipped, never overwritten.
    People added as members with a mobile number are signed up for texts."""
    try:
        rows = list(roster_import.read_rows(payload.csv))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    settings_row = membership.site_settings(db)
    created, skipped, errors = 0, 0, []
    for row in rows:
        first_name, last_name = row.get("first_name"), row.get("last_name")
        if row.get("name") and not first_name:
            parts = row.get("name").split()
            first_name, last_name = (parts[0] if parts else ""), " ".join(parts[1:])
        email: str | None = row.get("email").lower() or None
        if not first_name:
            errors.append(f"Line {row.line}: missing name")
            continue
        who = f"Line {row.line} ({first_name} {last_name})".replace(" )", ")")
        if email and not roster_import.is_email(email):
            errors.append(f'{who}: "{email}" is not a valid email address; added without an email')
            email = None
        elif not email:
            errors.append(f"{who}: no email; added without one")
        if email:
            existing = find_person_by_email(db, email)
        else:
            existing = db.scalar(select(Person.id).where(func.lower(Person.first_name) == first_name.lower(),
                                                         func.lower(Person.last_name) == last_name.lower()))
        if existing:
            if not email:
                errors.pop()
            skipped += 1
            continue

        # A cell that can't be read is left blank and reported; the person is still added.
        notes = list(row.remarks) + ([row.get("notes")] if row.get("notes") else [])
        phone = row.get("phone")[:40] or None
        try:
            phone = normalize_phone(phone)
        except ValueError:
            pass
        nra_number: str | None = re.sub(r"[\s-]", "", row.get("nra_number")) or None
        if nra_number and not re.fullmatch(r"\d{5,12}", nra_number):
            errors.append(f'{who}: NRA number "{nra_number}" is not 5 to 12 digits; left blank')
            nra_number = None
        elif nra_number and db.scalar(select(Person.id).where(Person.nra_number == nra_number)):
            errors.append(f"{who}: NRA number {nra_number} is already on file for someone else; left blank")
            nra_number = None
        nra_expiration_date, nra_life_member, renewal_date = None, False, None
        try:
            nra_expiration_date, nra_life_member = roster_import.nra_expiration(row.get("nra_expiration"))
        except ValueError as exc:
            errors.append(f"{who}: {exc}; left blank")
        try:
            renewal_date = roster_import.paid_through(settings_row, row)
        except ValueError as exc:
            errors.append(f"{who}: {exc}; left blank")
        member_number = int(row.get("member_number")) if row.get("member_number").isdigit() else None
        for column, label in (("rules", "Rules"), ("card", "Card")):
            if row.get(column) and row.get(column).upper() not in ("Y", "YES"):
                notes.append(f"{label}: {row.get(column)}")

        person = Person(
            first_name=first_name[:120], last_name=last_name[:120], email=email, phone=phone,
            address_line1=row.get("address_line1")[:255] or None, address_line2=row.get("address_line2")[:255] or None,
            city=row.get("city")[:120] or None, state=row.get("state").upper()[:40] or None, zip_code=row.get("zip_code")[:20] or None,
            membership_status=payload.membership_status, member_number=member_number, renewal_date=renewal_date,
            nra_number=nra_number, nra_expiration_date=nra_expiration_date, nra_life_member=nra_life_member,
            notes="\n".join(notes) or None,
        )
        membership.enroll_roster_member_in_texts(person)
        db.add(person)
        db.flush()
        created += 1
    audit.record(db, actor=auth.person, action="person.imported", entity_type="person",
                 details={"created": created, "skipped": skipped}, context=request_context(request))
    db.commit()
    return {"created": created, "skipped": skipped, "errors": errors[:50]}


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

EXPORT_FORMATS = {
    "mailing_list": ["First name", "Last name", "Email"],
    "postal_labels": ["Name", "Address line 1", "Address line 2", "City", "State", "ZIP"],
    "full": ["First name", "Last name", "Email", "Phone", "Address line 1", "Address line 2", "City", "State", "ZIP",
             "Status", "Groups", "Renewal date", "NRA number", "NRA expiration", "Texts OK"],
}


def _csv_cell(value: object) -> str:
    text = "" if value is None else str(value)
    # Neutralize spreadsheet formula injection.
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        text = "'" + text
    return text


@router.get("/exports/contacts.csv")
def export_contacts(
    request: Request,
    export_format: Literal["mailing_list", "postal_labels", "full"] = Query(default="mailing_list", alias="format"),
    group: list[str] = Query(default=["active_members"]),
    include_opted_out: bool = False,
    auth: BoardAuth = Depends(can_export),
    db: Session = Depends(get_db),
) -> Response:
    try:
        conditions = search_conditions(None, group, None)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if export_format == "mailing_list":
        conditions.append(Person.email.is_not(None))
    if export_format == "mailing_list" and not include_opted_out:
        conditions.append(Person.email_opt_out.is_(False))
    if export_format == "postal_labels":
        conditions.append(Person.address_line1.is_not(None))
    people = db.scalars(select(Person).where(and_(*conditions)).order_by(Person.last_name, Person.first_name)).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(EXPORT_FORMATS[export_format])
    from app.services.people import groups_for

    for p in people:
        if export_format == "mailing_list":
            row: list[object] = [p.first_name, p.last_name, p.email]
        elif export_format == "postal_labels":
            row = [p.full_name, p.address_line1, p.address_line2, p.city, p.state, p.zip_code]
        else:
            row = [p.first_name, p.last_name, p.email, p.phone, p.address_line1, p.address_line2, p.city, p.state, p.zip_code,
                   p.membership_status, "; ".join(GROUPS[g] for g in groups_for(p)), p.renewal_date, p.nra_number,
                   p.nra_expiration_date, "yes" if p.sms_opt_in else "no"]
        writer.writerow([_csv_cell(v) for v in row])

    audit.record(db, actor=auth.person, action="export.contacts", entity_type="person",
                 summary=f"Exported {len(people)} contacts ({export_format})",
                 details={"format": export_format, "groups": group, "count": len(people)}, context=request_context(request))
    db.commit()
    filename = f"kiowa-{export_format.replace('_', '-')}-{club_today().isoformat()}.csv"
    return Response(
        content="﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )


