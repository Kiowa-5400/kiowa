"""Spotting and combining two records for the same person.

Signing up only finds an existing record by email, so a roster member the club
had no email for (or an old one for) ends up with a second record. Records with
the same last name and phone number are flagged; the board either combines
them or says they're different people (a couple sharing a landline).

Combining keeps one record and folds the other into it: everything that points
at the other record (applications, payments, documents, messages, history)
moves over, blanks are filled in from it, and it is deleted.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.models import Application, AuditLog, AuthSession, AuthToken, Base, NotDuplicate, Person, RenewalReminder
from app.services import audit
from app.services.audit import RequestContext
from app.services.sms import ten_digits

# Which status wins when two records disagree.
STATUS_RANK = {"member": 5, "expired": 4, "terminated": 3, "waiting_list": 2, "non_member": 1}
ROSTER_STATUSES = ("member", "expired", "terminated")
OPEN_STATUSES = ("draft", "submitted", "needs_info", "approved")
# Filled in from the other record when the kept one is blank.
FILL_BLANKS = ("first_name", "last_name", "phone", "address_line1", "address_line2", "city", "state", "zip_code",
               "nra_number", "member_number")


class CombineError(Exception):
    pass


def _last(person: Person) -> str:
    return (person.last_name or "").strip().lower()


def _pair(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def _dismissed(db: Session, ids: list[int] | None = None) -> set[tuple[int, int]]:
    query = select(NotDuplicate.person_a_id, NotDuplicate.person_b_id)
    if ids is not None:
        query = query.where(or_(NotDuplicate.person_a_id.in_(ids), NotDuplicate.person_b_id.in_(ids)))
    return {(a, b) for a, b in db.execute(query)}


def matches_for(db: Session, person: Person) -> list[Person]:
    """Other records with this person's last name and phone number, not marked as different people."""
    phone = ten_digits(person.phone)
    if not phone or not _last(person):
        return []
    candidates = [p for p in db.scalars(select(Person).where(Person.id != person.id,
                                                             func.lower(func.trim(Person.last_name)) == _last(person)))
                  if ten_digits(p.phone) == phone]
    dismissed = _dismissed(db, [person.id])
    return [p for p in candidates if _pair(person.id, p.id) not in dismissed]


def all_matches(db: Session) -> list[tuple[Person, Person]]:
    """Every flagged pair, the record that would be kept first."""
    groups: dict[tuple[str, str], list[Person]] = {}
    for person in db.scalars(select(Person).where(Person.phone.is_not(None)).order_by(Person.id)):
        phone = ten_digits(person.phone)
        if phone and _last(person):
            groups.setdefault((_last(person), phone), []).append(person)
    dismissed = _dismissed(db)
    pairs = []
    for people in groups.values():
        for i, a in enumerate(people):
            for b in people[i + 1:]:
                if _pair(a.id, b.id) not in dismissed:
                    pairs.append(keeper_first(a, b))
    return sorted(pairs, key=lambda pair: (pair[0].last_name.lower(), pair[0].first_name.lower()))


def mark_different(db: Session, a: Person, b: Person, actor: Person, context: RequestContext | None) -> None:
    pair = _pair(a.id, b.id)
    if db.get(NotDuplicate, pair) is None:
        db.add(NotDuplicate(person_a_id=pair[0], person_b_id=pair[1]))
    audit.record(db, actor=actor, action="person.marked_not_duplicate", entity_type="person", entity_id=a.id,
                 summary=f"{a.full_name} and {b.full_name} are different people", details={"other_person_id": b.id},
                 context=context)


def keeper_first(a: Person, b: Person) -> tuple[Person, Person]:
    """The record to keep is the one further along with the club (a roster member over a
    new sign-up), then the older one."""
    def rank(p: Person) -> tuple[int, float]:
        return STATUS_RANK.get(p.membership_status, 0), -p.id
    return (a, b) if rank(a) >= rank(b) else (b, a)


def _latest(*values: datetime | None) -> datetime | None:
    present = [v for v in values if v is not None]
    return max(present) if present else None


def _plan(keep: Person, other: Person) -> dict[str, Any]:
    """The combined record's values."""
    values: dict[str, Any] = {k: getattr(keep, k) if getattr(keep, k) not in (None, "") else getattr(other, k)
                              for k in FILL_BLANKS}
    values["sms_carrier"] = keep.sms_carrier if values["phone"] == keep.phone else other.sms_carrier

    status_from = keep if STATUS_RANK.get(keep.membership_status, 0) >= STATUS_RANK.get(other.membership_status, 0) else other
    values["membership_status"] = status_from.membership_status
    values["terminated_at"] = status_from.terminated_at
    values["renewal_date"] = max(filter(None, (keep.renewal_date, other.renewal_date)), default=None)
    values["member_since"] = min(filter(None, (keep.member_since, other.member_since)), default=None)

    values["nra_expiration_date"] = max(filter(None, (keep.nra_expiration_date, other.nra_expiration_date)), default=None)
    values["nra_life_member"] = keep.nra_life_member or other.nra_life_member
    values["nra_active"] = keep.nra_active or other.nra_active
    values["background_check_cleared"] = keep.background_check_cleared or other.background_check_cleared
    values["background_check_cleared_at"] = _latest(keep.background_check_cleared_at, other.background_check_cleared_at)
    values["on_board"] = keep.on_board or other.on_board
    values["on_shooting_committee"] = keep.on_shooting_committee or other.on_shooting_committee

    # Whichever record heard most recently about texts decides; an unsubscribe from either sticks.
    newer = keep
    if _naive(_latest(other.sms_opt_in_at, other.sms_opt_out_at)) > _naive(_latest(keep.sms_opt_in_at, keep.sms_opt_out_at)):
        newer = other
    for key in ("sms_opt_in", "sms_opt_in_at", "sms_opt_in_source", "sms_opt_out_at"):
        values[key] = getattr(newer, key)
    values["email_opt_out"] = keep.email_opt_out or other.email_opt_out
    values["email_opt_out_at"] = _latest(keep.email_opt_out_at, other.email_opt_out_at)

    values["notes"] = "\n\n".join(n.strip() for n in (keep.notes, other.notes) if n and n.strip()) or None

    # Sign-in: whichever record has a password (the most recently used one if both do).
    login = keep
    if other.password_hash and (not keep.password_hash or _naive(other.last_login_at) > _naive(keep.last_login_at)):
        login = other
    if not login.email:
        login = other if other.email else keep
    for key in ("email", "email_verified_at", "password_hash", "last_login_at", "failed_login_count", "locked_until"):
        values[key] = getattr(login, key)
    return values


def _naive(value: datetime | None) -> datetime:
    return value.replace(tzinfo=None) if value else datetime.min


def _open(db: Session, person: Person) -> Application | None:
    return db.scalar(select(Application).where(Application.person_id == person.id, Application.status.in_(OPEN_STATUSES)))


def _applications_to_cancel(db: Session, keep: Person, other: Person, status: str) -> list[Application]:
    """At most one application can be in progress, and someone on the roster doesn't need the waiting list.
    Raises CombineError when both have one under way and neither is just a draft."""
    mine, theirs = _open(db, keep), _open(db, other)
    cancel = []
    for app in (theirs, mine):
        if (app is not None and status in ROSTER_STATUSES and app.application_type == "waiting_list"
                and app.status != "approved"):
            cancel.append(app)
    remaining = [a for a in (theirs, mine) if a is not None and a not in cancel]
    if len(remaining) == 2:
        drafts = [a for a in remaining if a.status == "draft"]
        if not drafts:
            raise CombineError("Both records have an application in progress. Approve, decline or finish one of them first.")
        cancel.append(drafts[0])
    return cancel


def preview(db: Session, keep: Person, other: Person) -> dict[str, Any]:
    """What combining would do, in plain words, plus anything stopping it."""
    values = _plan(keep, other)
    problem = None
    cancel: list[Application] = []
    try:
        if keep.board_user and other.board_user:
            raise CombineError("Both records have their own board sign-in. Remove one under Board users first.")
        cancel = _applications_to_cancel(db, keep, other, values["membership_status"])
    except CombineError as exc:
        problem = str(exc)

    notes = []
    for app in cancel:
        kind = "waiting-list application" if app.application_type == "waiting_list" else "renewal"
        why = (" since they're already on the club roster" if app.application_type == "waiting_list"
               and values["membership_status"] in ROSTER_STATUSES else "")
        notes.append(f"Their {'unfinished' if app.status == 'draft' else 'open'} {kind} will be cancelled{why}.")
    if values["password_hash"]:
        notes.append(f"They'll sign in to the member website with {values['email']} and the password they already use.")
    elif values["email"]:
        notes.append(f"Club emails will go to {values['email']}.")
    def same(label: str, a: str, b: str) -> bool:
        # (620) 555-0177 and 620-555-0177 are the same number.
        return ten_digits(a) == ten_digits(b) if label == "phone number" else a.strip().lower() == b.strip().lower()

    for label, key in (("email", "email"), ("phone number", "phone"), ("address", "address_line1")):
        a, b = getattr(keep, key), getattr(other, key)
        if a and b and not same(label, a, b):
            dropped = b if values[key] == a else a
            notes.append(f"The {label} {dropped} won't be kept. You can change it on their page afterwards.")
    notes.append("Their payments, documents, applications and message history will all be kept together.")
    return {"keep": keep, "other": other, "values": values, "notes": notes, "problem": problem}


def combine(db: Session, keep: Person, other: Person, actor: Person, context: RequestContext | None) -> Person:
    """Folds ``other`` into ``keep`` and deletes it. Raises CombineError when it can't be done yet."""
    if keep.id == other.id:
        raise CombineError("That's the same record.")
    result = preview(db, keep, other)
    if result["problem"]:
        raise CombineError(result["problem"])
    values = result["values"]
    snapshot = {k: str(getattr(other, k)) for k in ("first_name", "last_name", "email", "phone", "membership_status")
                if getattr(other, k) is not None}

    for app in _applications_to_cancel(db, keep, other, values["membership_status"]):
        app.status = "withdrawn"
        audit.record(db, actor=actor, action="application.withdrawn", entity_type="application", entity_id=app.id,
                     summary="Cancelled when two records for the same person were combined", context=context)

    # Free the unique values so the kept record can take them.
    other.email, other.nra_number = None, None
    db.flush()

    # Point everything at the kept record. Sign-in sessions and emailed links for the other record just end.
    db.execute(delete(AuthSession).where(AuthSession.person_id == other.id))
    db.execute(delete(AuthToken).where(AuthToken.person_id == other.id))
    db.execute(delete(NotDuplicate).where(or_(NotDuplicate.person_a_id == other.id, NotDuplicate.person_b_id == other.id)))
    already_sent = select(RenewalReminder.cycle_date, RenewalReminder.threshold_days, RenewalReminder.channel).where(
        RenewalReminder.person_id == keep.id)
    sent = {tuple(row) for row in db.execute(already_sent)}
    for reminder in db.scalars(select(RenewalReminder).where(RenewalReminder.person_id == other.id)):
        if (reminder.cycle_date, reminder.threshold_days, reminder.channel) in sent:
            db.delete(reminder)
    db.flush()
    for table in Base.metadata.sorted_tables:
        for fk in table.foreign_keys:
            if fk.column.table.name == "people" and table.name not in ("people", "not_duplicates"):
                db.execute(update(table).where(fk.parent == other.id).values({fk.parent.name: keep.id}))
    db.execute(update(AuditLog).where(AuditLog.entity_type == "person", AuditLog.entity_id == str(other.id))
               .values(entity_id=str(keep.id)))
    other_id = other.id
    db.expunge(other)
    db.execute(delete(Person).where(Person.id == other_id))

    db.expire_all()  # rows moved behind the session's back
    for key, value in values.items():
        setattr(keep, key, value)
    db.flush()
    audit.record(db, actor=actor, action="person.combined", entity_type="person", entity_id=keep.id,
                 summary=f"Combined two records for {keep.full_name}",
                 details={"removed_person_id": other_id, "removed": snapshot}, context=context)
    return keep
