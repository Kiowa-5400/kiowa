"""Annual renewal cycle (ported from kiowa-gun lib/renewalCycle.ts and its cron routes).

Every member is due by the same clubwide cutoff each year (September 10 by
default, configurable in Settings), not a personal anniversary. A member's
``renewal_date`` is the cutoff they've paid through. That single shared date
drives the 45/15-day reminders and the annual termination sweep.
"""

from __future__ import annotations

import calendar
import html
import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.timeutil import club_today, format_long_date, now_utc
from app.models import (
    Document,
    EmailCampaign,
    EmailRecipient,
    JobRun,
    Person,
    RenewalReminder,
    SiteSettings,
    SmsCampaign,
    SmsRecipient,
)
from app.services import audit
from app.services import email as email_service
from app.services import sms as sms_service
from app.services.storage import delete_quietly

logger = logging.getLogger("kiowa.renewal")

REMINDER_THRESHOLDS = (15, 45)  # ascending: the smallest window a member is inside wins


def cutoff_date(settings_row: SiteSettings, year: int) -> date:
    month, day = settings_row.renewal_cutoff_month, settings_row.renewal_cutoff_day
    # A February 29 cutoff falls on the 28th in years that have no 29th.
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def next_cutoff_after_payment(settings_row: SiteSettings, current_renewal_date: date | None, today: date) -> date:
    """The cutoff a payment made ``today`` should count toward: the next cutoff
    still ahead of today and strictly after whatever is already paid through
    (so renewing early extends to the following year instead of re-stamping)."""
    year = today.year
    candidate = cutoff_date(settings_row, year)
    if today > candidate:
        year += 1
        candidate = cutoff_date(settings_row, year)
    while current_renewal_date and current_renewal_date >= candidate:
        year += 1
        candidate = cutoff_date(settings_row, year)
    return candidate


def current_cycle_cutoff(settings_row: SiteSettings, today: date) -> date:
    """The next cutoff on or after today: the date dues are currently due by."""
    cutoff = cutoff_date(settings_row, today.year)
    return cutoff if today <= cutoff else cutoff_date(settings_row, today.year + 1)


def dues_target_cutoff(settings_row: SiteSettings, today: date) -> date:
    """The cutoff a member must have paid through to count as paid up today.

    Inside the reminder window (45 days before the cutoff) that's the upcoming
    cutoff; the rest of the year it's the most recent one, so members who
    paid this year aren't shown as owing next year's dues months early."""
    upcoming = current_cycle_cutoff(settings_row, today)
    if (upcoming - today).days <= max(REMINDER_THRESHOLDS):
        return upcoming
    return cutoff_date(settings_row, upcoming.year - 1)


def renewal_summary(settings_row: SiteSettings, person: Person, today: date | None = None) -> dict[str, object]:
    today = today or club_today()
    current_cutoff = current_cycle_cutoff(settings_row, today)
    paid_through = person.renewal_date
    is_current = bool(paid_through and paid_through >= dues_target_cutoff(settings_row, today))
    return {
        "paid_through": paid_through.isoformat() if paid_through else None,
        "next_cutoff": current_cutoff.isoformat(),
        "is_current": is_current,
        "days_until_cutoff": (current_cutoff - today).days,
    }


@dataclass
class ReminderResult:
    emails_sent: int = 0
    sms_sent: int = 0
    failures: int = 0
    skipped_no_consent: int = 0
    details: list[str] = field(default_factory=list)


def _reminder_text(days_out: int, renewal_date: date, pay_link: str) -> str:
    return (
        f"Kiowa Gun Club: Your annual membership dues are due in {days_out} days "
        f"(by {format_long_date(renewal_date)}). Renew here: {pay_link}. Reply STOP to opt out."
    )


def _claim_reminder(db: Session, person: Person, cycle: date, threshold: int, channel: str) -> RenewalReminder | None:
    """Inserts the reminder marker first; the unique constraint makes the job
    idempotent even if two runs overlap."""
    marker = RenewalReminder(person_id=person.id, cycle_date=cycle, threshold_days=threshold, channel=channel)
    try:
        with db.begin_nested():
            db.add(marker)
            db.flush()
    except IntegrityError:
        return None
    return marker


class _ReminderLog:
    """Records automated reminders as campaigns so they appear in the board's
    email and text history with delivery analytics."""

    def __init__(self, db: Session, threshold: int, cycle: date) -> None:
        self.db = db
        self.summary = f"Automatic {threshold}-day dues reminder ({format_long_date(cycle)})"
        self.email_campaign: EmailCampaign | None = None
        self.sms_campaign: SmsCampaign | None = None

    def email(self, person: Person, subject: str, body: str, result: email_service.SendResult) -> None:
        if self.email_campaign is None:
            self.email_campaign = EmailCampaign(kind="renewal_reminder", subject=subject, body_html=body, recipient_summary=self.summary,
                                                sent_count=0, failed_count=0)
            self.db.add(self.email_campaign)
        self.email_campaign.recipients.append(EmailRecipient(
            person_id=person.id, email=person.email, provider_message_id=result.message_id,
            status="sent" if result.ok else "failed", error=result.error, sent_at=now_utc() if result.ok else None,
        ))
        if result.ok:
            self.email_campaign.sent_count += 1
        else:
            self.email_campaign.failed_count += 1

    def sms(self, person: Person, body: str, result: sms_service.SmsResult) -> None:
        if self.sms_campaign is None:
            self.sms_campaign = SmsCampaign(kind="renewal_reminder", body=body, recipient_summary=self.summary,
                                            sent_count=0, failed_count=0, skipped_count=0, fallback_email_count=0)
            self.db.add(self.sms_campaign)
        self.sms_campaign.recipients.append(SmsRecipient(
            person_id=person.id, phone=person.phone or "", gateway_address=result.gateway_address,
            provider_message_id=result.message_id, status=result.status, error=result.error,
            sent_at=now_utc() if result.ok else None,
        ))
        if result.ok:
            self.sms_campaign.sent_count += 1
        else:
            self.sms_campaign.failed_count += 1


def send_renewal_reminders(db: Session, today: date | None = None) -> ReminderResult:
    today = today or club_today()
    settings_row = db.get(SiteSettings, 1)
    result = ReminderResult()
    if settings_row is None:
        return result
    pay_link = f"{get_settings().apply_app_url.rstrip('/')}/?type=renewal"
    cycle = current_cycle_cutoff(settings_row, today)
    days_out = (cycle - today).days

    threshold = next((t for t in REMINDER_THRESHOLDS if days_out <= t), None)
    if threshold is None:
        return result

    # Members who haven't paid through this cycle yet.
    due = db.scalars(
        select(Person).where(
            Person.membership_status == "member",
            or_(Person.renewal_date.is_(None), Person.renewal_date < cycle),
        )
    ).all()

    log = _ReminderLog(db, threshold, cycle)
    subject = f"Kiowa Gun Club dues are due by {format_long_date(cycle)}"
    for person in due:
        text = _reminder_text(days_out, cycle, pay_link)
        # Email reminder (a notice about their own membership, so it is sent
        # even to people who unsubscribed from newsletters).
        marker = _claim_reminder(db, person, cycle, threshold, "email")
        if marker is not None:
            body = (
                f"<p>Hi {html.escape(person.first_name)},</p>"
                f"<p>Your annual Kiowa Gun Club membership dues of ${settings_row.dues_amount:.2f} are due by "
                f"<strong>{format_long_date(cycle)}</strong> ({days_out} days from today). Members who have not "
                f"renewed by then are removed from the membership roster.</p>"
                + email_service.button(pay_link, "Renew my membership")
            )
            sent = email_service.get_email_provider().send(email_service.EmailMessage(
                to=person.email, subject=subject,
                html=email_service.render_layout(body, footer_html="You received this reminder because you are a Kiowa Gun Club member."),
                tags={"category": "renewal_reminder"},
            ))
            log.email(person, subject, body, sent)
            marker.succeeded = sent.ok
            marker.error = sent.error
            if sent.ok:
                result.emails_sent += 1
            else:
                result.failures += 1
        # SMS reminder only with recorded consent.
        if not (person.sms_opt_in and person.sms_opt_in_at):
            result.skipped_no_consent += 1
            continue
        marker = _claim_reminder(db, person, cycle, threshold, "sms")
        if marker is None:
            continue
        sms = sms_service.send_to_person(person, text)
        log.sms(person, text, sms)
        marker.succeeded = sms.ok
        marker.error = sms.error
        if sms.ok:
            result.sms_sent += 1
        else:
            result.failures += 1
    # Mark the larger thresholds as done too, so a late-added member doesn't
    # get the 45-day text right after the 15-day one.
    for person in due:
        channels = ("email", "sms") if person.sms_opt_in and person.sms_opt_in_at else ("email",)
        for larger in (t for t in REMINDER_THRESHOLDS if t > threshold):
            for channel in channels:
                marker = _claim_reminder(db, person, cycle, larger, channel)
                if marker is not None:
                    marker.succeeded = False
                    marker.error = f"Skipped: superseded by the {threshold}-day reminder"
    db.commit()
    logger.info("renewal_reminders_sent", extra={"threshold": threshold, **result.__dict__})
    return result


def claim_job_period(db: Session, job_name: str, period_key: str) -> JobRun | None:
    run = JobRun(job_name=job_name, period_key=period_key)
    try:
        with db.begin_nested():
            db.add(run)
            db.flush()
    except IntegrityError:
        return None
    return run


def run_termination_sweep(db: Session, today: date | None = None) -> dict[str, object]:
    """Once per year after the cutoff, members who haven't paid through this
    year's cutoff are terminated. Contact info is kept (they move to the
    "former members" group) and payment/audit history is never deleted, but
    their private membership documents (NRA cards, background checks) are
    purged from storage."""
    today = today or club_today()
    settings_row = db.get(SiteSettings, 1)
    if settings_row is None:
        return {"ran": False}
    cutoff = cutoff_date(settings_row, today.year)
    if today <= cutoff:
        return {"ran": False, "reason": "before cutoff"}
    run = claim_job_period(db, "termination_sweep", str(today.year))
    if run is None:
        return {"ran": False, "reason": "already ran this year"}

    unpaid = db.scalars(
        select(Person).where(
            Person.membership_status == "member",
            or_(Person.renewal_date.is_(None), Person.renewal_date < cutoff),
        )
    ).all()
    now = now_utc()
    for person in unpaid:
        person.membership_status = "terminated"
        person.terminated_at = now
        for document in db.scalars(select(Document).where(Document.person_id == person.id, Document.purged_at.is_(None))):
            delete_quietly(document.storage_key)
            document.purged_at = now
        audit.record(
            db,
            actor=None,
            action="member.terminated_nonpayment",
            entity_type="person",
            entity_id=person.id,
            summary=f"{person.full_name} terminated for non-payment after the {format_long_date(cutoff)} cutoff",
        )
    run.status = "succeeded"
    run.finished_at = now
    run.result = {"terminated": len(unpaid)}
    db.commit()

    if unpaid:
        names = "".join(f"<li>{html.escape(p.full_name)} ({html.escape(p.email)})</li>" for p in unpaid)
        from app.services.people import active_board_people

        for board_person in active_board_people(db):
            email_service.send_transactional(
                board_person.email,
                "Annual membership termination sweep ran",
                f"<p>The annual dues deadline ({format_long_date(cutoff)}) has passed. {len(unpaid)} member(s) who had not "
                f"paid were moved to Terminated. Their contact records and payment history were kept; their uploaded "
                f"membership documents were deleted.</p><ul>{names}</ul>",
            )
    return {"ran": True, "terminated": len(unpaid)}


def run_nra_expiration_check(db: Session, today: date | None = None) -> int:
    """Members whose NRA membership has lapsed lose payment eligibility until
    the board verifies new proof (ported from kiowa-gun cron/nra-check)."""
    today = today or club_today()
    lapsed = db.scalars(
        select(Person).where(
            Person.membership_status == "member",
            Person.nra_active.is_(True),
            Person.nra_expiration_date.is_not(None),
            Person.nra_expiration_date < today,
        )
    ).all()
    for person in lapsed:
        person.nra_active = False
        audit.record(db, actor=None, action="member.nra_lapsed", entity_type="person", entity_id=person.id,
                     summary=f"NRA membership for {person.full_name} expired {person.nra_expiration_date}")
    if lapsed:
        from app.services.membership import refresh_open_applications

        for person in lapsed:
            refresh_open_applications(db, person)
    db.commit()
    return len(lapsed)
