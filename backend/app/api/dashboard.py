"""Board dashboard summary."""

from __future__ import annotations

from datetime import time, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import BoardAuth, get_db, require_board
from app.api.events import event_out
from app.core.permissions import Permission
from app.core.timeutil import club_local_to_utc, club_today, now_utc
from app.models import Application, BoardUser, CalendarEvent, Document, EmailCampaign, Match, Payment, Person, SmsCampaign
from app.services import membership, renewal
from app.services.people import GROUPS, group_condition

router = APIRouter(prefix="/api/board", tags=["board: dashboard"])


@router.get("/dashboard")
def dashboard(auth: BoardAuth = Depends(require_board), db: Session = Depends(get_db)) -> dict[str, object]:
    today = club_today()
    count = lambda *conditions: db.scalar(select(func.count()).select_from(Application).where(*conditions)) or 0  # noqa: E731
    settings_row = membership.site_settings(db)
    cutoff = renewal.current_cycle_cutoff(settings_row, today)
    target = renewal.dues_target_cutoff(settings_row, today)

    data: dict[str, object] = {
        "applications": {
            "pending_renewals": count(Application.status == "submitted", Application.application_type == "renewal"),
            "pending_waiting_list": count(Application.status == "submitted", Application.application_type == "waiting_list"),
            "needs_info": count(Application.status == "needs_info"),
            "awaiting_payment": count(Application.status == "approved"),
        },
        "groups": [
            {"key": key, "label": label, "count": db.scalar(select(func.count()).select_from(Person).where(group_condition(key))) or 0}
            for key, label in GROUPS.items()
        ],
        "needs_attention": _needs_attention(db),
        "documents_pending_review": db.scalar(
            select(func.count()).select_from(Document).where(Document.review_status == "pending", Document.purged_at.is_(None))
        ) or 0,
        "renewal": {
            "next_cutoff": cutoff.isoformat(),
            "days_until_cutoff": (cutoff - today).days,
            "dues_season": target == cutoff,
            # Dues are one-time payments: "paid up" means renewal_date reaches the current cutoff.
            "members_paid_up": db.scalar(
                select(func.count()).select_from(Person).where(Person.membership_status == "member", Person.renewal_date >= target)
            ) or 0,
            "members_not_renewed": db.scalar(
                select(func.count()).select_from(Person).where(
                    Person.membership_status == "member",
                    (Person.renewal_date.is_(None)) | (Person.renewal_date < target),
                )
            ) or 0,
            "nra_lapsed": db.scalar(
                select(func.count()).select_from(Person).where(Person.membership_status == "member", Person.nra_active.is_(False))
            ) or 0,
        },
        "upcoming_events": [
            event_out(e).model_dump(mode="json")
            for e in db.scalars(
                select(CalendarEvent).where(CalendarEvent.starts_at >= club_local_to_utc(today, time.min))
                .order_by(CalendarEvent.starts_at).limit(5)
            )
        ],
        "upcoming_matches": [
            {"id": m.id, "discipline": m.discipline, "event_date": m.event_date.isoformat(), "has_results": bool(m.results_url)}
            for m in db.scalars(select(Match).where(Match.event_date >= today).order_by(Match.event_date).limit(5))
        ],
        "recent_matches_missing_results": db.scalar(
            select(func.count()).select_from(Match).where(
                Match.event_date < today, Match.event_date >= today - timedelta(days=60), Match.results_url.is_(None)
            )
        ) or 0,
        "last_email": _last_email(db),
        "last_sms": _last_sms(db),
    }
    if auth.can(Permission.PAYMENTS_VIEW):
        year_start = club_local_to_utc(today.replace(month=1, day=1), time.min)
        data["payments"] = {
            "collected_this_year": str(Decimal(db.scalar(
                select(func.coalesce(func.sum(Payment.amount - Payment.refunded_amount), 0))
                .where(Payment.status.in_(("paid", "partially_refunded")), Payment.paid_at >= year_start)
            ) or 0).quantize(Decimal("0.01"))),
            "recent": [
                {"id": p.id, "name": p.person.full_name, "amount": str(p.amount), "method": p.method, "status": p.status,
                 "paid_at": p.paid_at.isoformat() if p.paid_at else None}
                for p in db.scalars(select(Payment).where(Payment.status != "pending").order_by(Payment.created_at.desc()).limit(6))
            ],
        }
    if auth.can(Permission.BOARD_MANAGE):
        data["locked_board_accounts"] = [
            {"board_user_id": b.id, "name": b.person.full_name, "locked_until": b.person.locked_until.isoformat()}
            for b in db.scalars(select(BoardUser).join(Person, Person.id == BoardUser.person_id).where(BoardUser.is_active.is_(True), Person.locked_until > now_utc()))
        ]
    return data


def _last_email(db: Session) -> dict[str, object] | None:
    campaign = db.scalar(select(EmailCampaign).order_by(EmailCampaign.created_at.desc()).limit(1))
    if campaign is None:
        return None
    opened = sum(1 for r in campaign.recipients if r.opened_at)
    return {"id": campaign.id, "subject": campaign.subject, "created_at": campaign.created_at.isoformat(),
            "sent": campaign.sent_count, "failed": campaign.failed_count, "opened": opened,
            "bounced": sum(1 for r in campaign.recipients if r.bounced_at)}


def _last_sms(db: Session) -> dict[str, object] | None:
    campaign = db.scalar(select(SmsCampaign).order_by(SmsCampaign.created_at.desc()).limit(1))
    if campaign is None:
        return None
    return {"id": campaign.id, "body": campaign.body[:120], "created_at": campaign.created_at.isoformat(),
            "sent": campaign.sent_count, "failed": campaign.failed_count, "emailed_instead": campaign.fallback_email_count}


def _needs_attention(db: Session) -> list[dict[str, object]]:
    """One list of everything waiting on a board decision, oldest first."""
    from app.services.membership import DOCUMENT_LABELS

    items: list[dict[str, object]] = []
    for application in db.scalars(
        select(Application).where(Application.status == "submitted").order_by(Application.submitted_at).limit(50)
    ):
        kind = "renewal" if application.application_type == "renewal" else "waiting-list application"
        items.append({"kind": "application", "id": application.id, "person_id": application.person_id,
                      "title": f"{application.person.full_name}: {kind} to review",
                      "since": application.submitted_at.isoformat() if application.submitted_at else None})
    for document in db.scalars(
        select(Document).where(Document.review_status == "pending", Document.purged_at.is_(None))
        .order_by(Document.uploaded_at).limit(50)
    ):
        items.append({"kind": "document", "id": document.id, "person_id": document.person_id,
                      "application_id": document.application_id,
                      "title": f"{document.person.full_name}: {DOCUMENT_LABELS[document.document_type]} to check",
                      "since": document.uploaded_at.isoformat()})
    items.sort(key=lambda item: str(item["since"] or ""))
    return items
