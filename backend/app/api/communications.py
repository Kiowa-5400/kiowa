"""Board email and SMS campaigns, provider webhooks, and unsubscribe."""

from __future__ import annotations

import html
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response
from pydantic import Field
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.api.deps import BoardAuth, get_db, request_context, require_permission
from app.core.config import get_settings
from app.core.permissions import Permission
from app.core.ratelimit import rate_limit
from app.core.timeutil import now_utc
from app.models import EmailAsset, EmailCampaign, EmailRecipient, Person, SmsCampaign, SmsRecipient
from app.schemas.common import APIModel, Message
from app.services import audit, membership, uploads
from app.services import email as email_service
from app.services import sms as sms_service
from app.services.html import sanitize_html
from app.services.people import GROUPS, resolve_recipients
from app.services.storage import get_storage, new_key

router = APIRouter(prefix="/api/board", tags=["board: communications"])
public_router = APIRouter(prefix="/api/public", tags=["public"])
logger = logging.getLogger("kiowa.communications")

webhook_router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

can_send = require_permission(Permission.COMMUNICATIONS_SEND)

MAX_ATTACHMENTS = 5
MAX_ATTACHMENT_TOTAL = 20 * 1024 * 1024


class Audience(APIModel):
    groups: list[str] = Field(default_factory=list)
    person_ids: list[int] = Field(default_factory=list, max_length=2000)


def _audience(db: Session, audience: Audience) -> list[Person]:
    try:
        people = resolve_recipients(db, groups=audience.groups, person_ids=audience.person_ids)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return people


def _summary(audience: Audience, db: Session) -> str:
    parts = [GROUPS[g] for g in audience.groups if g in GROUPS]
    if audience.person_ids:
        names = db.scalars(select(Person).where(Person.id.in_(audience.person_ids[:5]))).all()
        label = ", ".join(p.full_name for p in names)
        extra = len(audience.person_ids) - len(names)
        parts.append(label + (f" and {extra} more" if extra > 0 else ""))
    return "; ".join(parts) or "No one"


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------


def unsubscribe_links(person: Person) -> tuple[str, str]:
    settings = get_settings()
    page = f"{settings.portal_app_url.rstrip('/')}/unsubscribe?token={person.unsubscribe_token}"
    one_click = f"{settings.api_public_url.rstrip('/')}/api/public/unsubscribe?token={person.unsubscribe_token}"
    return page, one_click


def _campaign_footer(page_link: str) -> str:
    return (
        "You're receiving this because you're on the Kiowa Gun Club contact list. "
        f'<a href="{html.escape(page_link, quote=True)}" style="color:#4c5e3a;">Unsubscribe from club emails</a>.'
    )


@router.post("/email/audience")
def email_audience(payload: Audience, auth: BoardAuth = Depends(can_send), db: Session = Depends(get_db)) -> dict[str, object]:
    people = _audience(db, payload)
    included = [p for p in people if not p.email_opt_out]
    return {
        "count": len(included),
        "excluded_unsubscribed": len(people) - len(included),
        "recipients": [{"id": p.id, "name": p.full_name, "email": p.email} for p in included[:500]],
    }


class EmailDraft(APIModel):
    subject: str = Field(min_length=1, max_length=255)
    body_html: str = Field(min_length=1, max_length=200_000)


@router.post("/email/preview")
def email_preview(payload: EmailDraft, auth: BoardAuth = Depends(can_send)) -> dict[str, str]:
    body = sanitize_html(payload.body_html)
    return {"subject": payload.subject, "html": email_service.render_layout(body, footer_html=_campaign_footer("#"))}


@router.post("/email/attachments", status_code=status.HTTP_201_CREATED)
async def upload_attachment(request: Request, file: UploadFile = File(...), auth: BoardAuth = Depends(can_send),
                            db: Session = Depends(get_db)) -> dict[str, object]:
    upload = await uploads.validate_upload(file, uploads.EMAIL_ATTACHMENT_TYPES, label="Attachment")
    key = new_key("private/email-attachments", upload.extension)
    get_storage().put(key, upload.data, upload.mime_type)
    asset = EmailAsset(kind="attachment", storage_key=key, original_filename=upload.original_filename,
                       mime_type=upload.mime_type, size_bytes=upload.size_bytes, uploaded_by_id=auth.person.id)
    db.add(asset)
    db.commit()
    return {"id": asset.id, "filename": asset.original_filename, "size_bytes": asset.size_bytes}


class EmailSend(EmailDraft, Audience):
    attachment_ids: list[int] = Field(default_factory=list, max_length=MAX_ATTACHMENTS)


@router.post("/email/send")
def send_email(payload: EmailSend, request: Request, auth: BoardAuth = Depends(can_send), db: Session = Depends(get_db)) -> dict[str, object]:
    people = [p for p in _audience(db, payload) if not p.email_opt_out]
    if not people:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="No recipients selected (or everyone selected has unsubscribed).")
    assets = db.scalars(select(EmailAsset).where(EmailAsset.id.in_(payload.attachment_ids), EmailAsset.kind == "attachment")).all()
    if len(assets) != len(set(payload.attachment_ids)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="An attachment could not be found. Upload it again.")
    if sum(a.size_bytes for a in assets) > MAX_ATTACHMENT_TOTAL:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Attachments must total 20 MB or less.")
    attachments = [email_service.EmailAttachment(a.original_filename, get_storage().get(a.storage_key), a.mime_type) for a in assets]

    body = sanitize_html(payload.body_html)
    campaign = EmailCampaign(
        kind="manual", subject=payload.subject.strip(), body_html=body, recipient_summary=_summary(payload, db),
        attachment_names=[a.original_filename for a in assets], created_by_id=auth.person.id,
    )
    db.add(campaign)
    db.flush()

    messages: list[email_service.EmailMessage] = []
    for person in people:
        page_link, one_click = unsubscribe_links(person)
        messages.append(email_service.EmailMessage(
            to=person.email,
            subject=campaign.subject,
            html=email_service.render_layout(body, footer_html=_campaign_footer(page_link)),
            attachments=attachments,
            headers={"List-Unsubscribe": f"<{one_click}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"},
            tags={"campaign": str(campaign.id)},
        ))
    results = email_service.get_email_provider().send_batch(messages)
    now = now_utc()
    for person, result in zip(people, results, strict=True):
        campaign.recipients.append(EmailRecipient(
            person_id=person.id, email=person.email, provider_message_id=result.message_id,
            status="sent" if result.ok else "failed", error=result.error, sent_at=now if result.ok else None,
        ))
    campaign.sent_count = sum(1 for r in results if r.ok)
    campaign.failed_count = len(results) - campaign.sent_count
    audit.record(db, actor=auth.person, action="communication.email_sent", entity_type="email_campaign", entity_id=campaign.id,
                 summary=f'"{campaign.subject}" to {len(people)} recipients',
                 details={"sent": campaign.sent_count, "failed": campaign.failed_count, "audience": campaign.recipient_summary},
                 context=request_context(request))
    db.commit()
    return {"campaign_id": campaign.id, "sent": campaign.sent_count, "failed": campaign.failed_count}


def _email_stats():
    def count(column):  # noqa: ANN001, ANN202
        return func.count(case((column.is_not(None), 1)))

    return (
        count(EmailRecipient.delivered_at).label("delivered"),
        count(EmailRecipient.opened_at).label("opened"),
        count(EmailRecipient.clicked_at).label("clicked"),
        count(EmailRecipient.bounced_at).label("bounced"),
        count(EmailRecipient.complained_at).label("complained"),
    )


@router.get("/email/campaigns")
def email_campaigns(page: int = Query(default=1, ge=1), auth: BoardAuth = Depends(can_send), db: Session = Depends(get_db)) -> list[dict[str, object]]:
    stats = db.execute(
        select(EmailRecipient.campaign_id, *_email_stats()).group_by(EmailRecipient.campaign_id)
    ).all()
    by_campaign = {row.campaign_id: row for row in stats}
    campaigns = db.scalars(select(EmailCampaign).order_by(EmailCampaign.created_at.desc()).offset((page - 1) * 50).limit(50)).all()
    result = []
    for c in campaigns:
        s = by_campaign.get(c.id)
        result.append({
            "id": c.id, "kind": c.kind, "subject": c.subject, "recipient_summary": c.recipient_summary,
            "created_at": c.created_at, "created_by": c.created_by.full_name if c.created_by else "System",
            "sent": c.sent_count, "failed": c.failed_count, "attachments": c.attachment_names,
            "delivered": s.delivered if s else 0, "opened": s.opened if s else 0, "clicked": s.clicked if s else 0,
            "bounced": s.bounced if s else 0, "complained": s.complained if s else 0,
        })
    return result


@router.get("/email/campaigns/{campaign_id}")
def email_campaign(campaign_id: int, auth: BoardAuth = Depends(can_send), db: Session = Depends(get_db)) -> dict[str, object]:
    campaign = db.get(EmailCampaign, campaign_id)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Campaign not found.")
    return {
        "id": campaign.id, "subject": campaign.subject, "body_html": campaign.body_html, "kind": campaign.kind,
        "recipient_summary": campaign.recipient_summary, "attachments": campaign.attachment_names,
        "created_at": campaign.created_at, "created_by": campaign.created_by.full_name if campaign.created_by else "System",
        "recipients": [
            {"email": r.email, "person_id": r.person_id, "status": r.status, "error": r.error, "sent_at": r.sent_at,
             "delivered_at": r.delivered_at, "opened_at": r.opened_at, "clicked_at": r.clicked_at,
             "bounced_at": r.bounced_at, "bounce_type": r.bounce_type, "complained_at": r.complained_at}
            for r in sorted(campaign.recipients, key=lambda r: r.email)
        ],
    }


# ---------------------------------------------------------------------------
# SMS
# ---------------------------------------------------------------------------


@router.post("/media", status_code=status.HTTP_201_CREATED)
async def upload_sms_media(file: UploadFile = File(...), auth: BoardAuth = Depends(can_send), db: Session = Depends(get_db)) -> dict[str, object]:
    upload = await uploads.validate_upload(file, uploads.WEB_IMAGE_TYPES, label="Text picture")
    key = new_key("private/sms-media", upload.extension)
    get_storage().put(key, upload.data, upload.mime_type)
    asset = EmailAsset(kind="image", storage_key=key, original_filename=upload.original_filename,
                       mime_type=upload.mime_type, size_bytes=upload.size_bytes, uploaded_by_id=auth.person.id)
    db.add(asset)
    db.commit()
    return {"id": asset.id, "url": f"{get_settings().api_public_url.rstrip('/')}/api/public/media/{asset.public_token}"}


@public_router.get("/media/{token}")
def public_media(token: str, db: Session = Depends(get_db)) -> Response:
    asset = db.scalar(select(EmailAsset).where(EmailAsset.public_token == token, EmailAsset.kind == "image"))
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Media not found.")
    return Response(content=get_storage().get(asset.storage_key), media_type=asset.mime_type,
                    headers={"Cache-Control": "public, max-age=3600"})


@router.post("/sms/audience")
def sms_audience(payload: Audience, auth: BoardAuth = Depends(can_send), db: Session = Depends(get_db)) -> dict[str, object]:
    people = _audience(db, payload)
    consented = [p for p in people if p.sms_opt_in and p.sms_opt_in_at and sms_service.ten_digits(p.phone)]
    return {
        "count": len(consented),
        "no_consent": sum(1 for p in people if not (p.sms_opt_in and p.sms_opt_in_at)),
        "no_valid_phone": sum(1 for p in people if p.sms_opt_in and p.sms_opt_in_at and not sms_service.ten_digits(p.phone)),
        "recipients": [{"id": p.id, "name": p.full_name, "phone": p.phone} for p in consented[:500]],
    }


class SmsCheck(APIModel):
    body: str = Field(min_length=1, max_length=1600)


@router.post("/sms/check")
def sms_check(payload: SmsCheck, auth: BoardAuth = Depends(can_send)) -> dict[str, object]:
    risky = sms_service.find_risky_words(payload.body)
    safe = sms_service.build_safe_message(payload.body) if risky else payload.body
    return {"risky_words": risky, "safe_body": safe, "segments": (len(payload.body) - 1) // 153 + 1 if len(payload.body) > 160 else 1}


class SmsSend(SmsCheck, Audience):
    use_safe_version: bool = True
    email_if_text_fails: bool = True
    media_asset_id: int | None = None


def _email_fallback(person: Person, body: str) -> email_service.SendResult | None:
    """Emails the text to someone whose text couldn't be sent. Respects club-email unsubscribes."""
    if person.email_opt_out:
        return None
    page_link, one_click = unsubscribe_links(person)
    html_body = (
        "<p>We tried to send you this text message but couldn't reach your phone, so here it is by email:</p>"
        f"<blockquote>{html.escape(body).replace(chr(10), '<br>')}</blockquote>"
        "<p class=\"small\">If your mobile number has changed, update it in the member portal.</p>"
    )
    return email_service.get_email_provider().send(email_service.EmailMessage(
        to=person.email,
        subject="Message from the Kiowa Gun Club",
        html=email_service.render_layout(html_body, footer_html=_campaign_footer(page_link)),
        headers={"List-Unsubscribe": f"<{one_click}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"},
        tags={"category": "sms_fallback"},
    ))


@router.post("/sms/send")
def send_sms(payload: SmsSend, request: Request, auth: BoardAuth = Depends(can_send), db: Session = Depends(get_db)) -> dict[str, object]:
    people = _audience(db, payload)
    if not people:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="No recipients selected.")
    risky = sms_service.find_risky_words(payload.body)
    body = sms_service.build_safe_message(payload.body) if risky and payload.use_safe_version else payload.body

    campaign = SmsCampaign(kind="manual", body=body, recipient_summary=_summary(payload, db), created_by_id=auth.person.id)
    if payload.media_asset_id:
        media_asset = db.get(EmailAsset, payload.media_asset_id)
        if media_asset is None or media_asset.kind != "image":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="The selected picture could not be found.")
        campaign.media_asset_id = media_asset.id
    db.add(campaign)
    db.flush()
    media_url = None
    if campaign.media_asset_id:
        media_asset = db.get(EmailAsset, campaign.media_asset_id)
        media_url = f"{get_settings().api_public_url.rstrip('/')}/api/public/media/{media_asset.public_token}"
    now = now_utc()
    for person in people:
        try:
            result = sms_service.send_to_person(person, body, media_url)
        except sms_service.ConsentError:
            campaign.skipped_count += 1
            continue
        recipient = SmsRecipient(
            person_id=person.id, phone=person.phone or "", gateway_address=result.gateway_address,
            provider_message_id=result.message_id, status=result.status, error=result.error,
            sent_at=now if result.ok else None,
        )
        campaign.recipients.append(recipient)
        if result.ok:
            campaign.sent_count += 1
            continue
        campaign.failed_count += 1
        # The email isn't subject to carrier filtering, so it carries the board's original wording.
        if payload.email_if_text_fails and (fallback := _email_fallback(person, payload.body)) and fallback.ok:
            recipient.fallback_email_sent = True
            campaign.fallback_email_count += 1
    audit.record(db, actor=auth.person, action="communication.sms_sent", entity_type="sms_campaign", entity_id=campaign.id,
                 summary=f"Text to {campaign.sent_count + campaign.failed_count} recipients",
                 details={"sent": campaign.sent_count, "failed": campaign.failed_count, "skipped_no_consent": campaign.skipped_count,
                          "emailed_instead": campaign.fallback_email_count, "rewritten": bool(risky and payload.use_safe_version)},
                 context=request_context(request))
    db.commit()
    return {"campaign_id": campaign.id, "sent": campaign.sent_count, "failed": campaign.failed_count,
            "emailed_instead": campaign.fallback_email_count, "skipped_no_consent": campaign.skipped_count, "body_sent": body}


@router.get("/sms/campaigns")
def sms_campaigns(page: int = Query(default=1, ge=1), auth: BoardAuth = Depends(can_send), db: Session = Depends(get_db)) -> list[dict[str, object]]:
    campaigns = db.scalars(select(SmsCampaign).order_by(SmsCampaign.created_at.desc()).offset((page - 1) * 50).limit(50)).all()
    return [
        {
            "id": c.id, "kind": c.kind, "body": c.body, "recipient_summary": c.recipient_summary, "created_at": c.created_at,
            "created_by": c.created_by.full_name if c.created_by else "System", "sent": c.sent_count,
            "failed": c.failed_count, "emailed_instead": c.fallback_email_count, "skipped_no_consent": c.skipped_count,
            "delivered": sum(1 for r in c.recipients if r.delivered_at),
            "undelivered": sum(1 for r in c.recipients if r.status == "undelivered"),
            "in_flight": sum(1 for r in c.recipients if r.status == "sent"),
            "has_media": bool(c.media_asset_id),
        }
        for c in campaigns
    ]


@router.get("/sms/campaigns/{campaign_id}")
def sms_campaign(campaign_id: int, auth: BoardAuth = Depends(can_send), db: Session = Depends(get_db)) -> dict[str, object]:
    campaign = db.get(SmsCampaign, campaign_id)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Campaign not found.")
    names = {p.id: p.full_name for p in db.scalars(select(Person).where(Person.id.in_([r.person_id for r in campaign.recipients if r.person_id])))}
    return {
        "id": campaign.id, "body": campaign.body, "kind": campaign.kind, "recipient_summary": campaign.recipient_summary,
        "created_at": campaign.created_at, "created_by": campaign.created_by.full_name if campaign.created_by else "System",
        "recipients": [
            {"name": names.get(r.person_id or 0), "phone": r.phone, "gateway_address": r.gateway_address, "status": r.status,
             "error": r.error, "error_code": r.error_code, "sent_at": r.sent_at, "delivered_at": r.delivered_at,
             "failed_at": r.failed_at, "emailed_instead": r.fallback_email_sent}
            for r in campaign.recipients
        ],
    }


# ---------------------------------------------------------------------------
# Unsubscribe (public)
# ---------------------------------------------------------------------------


@public_router.post("/unsubscribe", response_model=Message, dependencies=[Depends(rate_limit("unsubscribe", 30, 60))])
def unsubscribe(token: str = Query(min_length=8, max_length=64), db: Session = Depends(get_db)) -> Message:
    """Works for the unsubscribe page and RFC 8058 one-click (List-Unsubscribe-Post)."""
    person = db.scalar(select(Person).where(Person.unsubscribe_token == token))
    if person is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="This unsubscribe link isn't valid.")
    if not person.email_opt_out:
        person.email_opt_out = True
        person.email_opt_out_at = now_utc()
        audit.record(db, actor=person, action="communication.email_unsubscribed", entity_type="person", entity_id=person.id)
        db.commit()
    return Message(message="You've been unsubscribed from Kiowa Gun Club emails. Account and dues notices will still be sent.")


def _record_text_consent(db: Session, phone: str | None, opted_in: bool, reason: str) -> int:
    """Applies a STOP/START from a phone to everyone with that number on file, and
    returns how many people have that number."""
    digits = sms_service.ten_digits(phone)
    if not digits:
        return 0
    on_file = func.right(func.regexp_replace(Person.phone, r"\D", "", "g"), 10)
    people = db.scalars(select(Person).where(on_file == digits)).all()
    for person in people:
        if person.sms_opt_in == opted_in:
            continue
        membership.set_sms_consent(person, opted_in, source=f"sms:{reason}")
        audit.record(db, actor=None, action="communication.sms_opted_in" if opted_in else "communication.sms_opted_out",
                     entity_type="person", entity_id=person.id, summary=f"{person.full_name} replied {reason}")
    return len(people)


# The standard carrier opt-out/opt-in keywords. The club phone doesn't act on
# them itself, so a reply is the only way consent changes by text.
_STOP_WORDS = {"STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT", "OPTOUT", "REVOKE"}
_START_WORDS = {"START", "UNSTOP", "OPTIN"}
_HELP_WORDS = {"HELP", "INFO"}


def _keyword_reply(db: Session, keyword: str, on_file: int) -> str:
    """The confirmation texted back for a STOP/START/HELP, in the wording the
    message program terms (www Terms page) promise."""
    site = membership.site_settings(db)
    name = site.site_title
    if keyword in _STOP_WORDS:
        return f"{name}: You're unsubscribed and won't get any more texts from us. Reply START to resume."
    if keyword in _START_WORDS and on_file:
        return (f"{name}: You're subscribed to texts about matches, events and dues reminders. Msg frequency varies. "
                "Msg & data rates may apply. Reply HELP for help, STOP to opt out.")
    if keyword in _START_WORDS:
        return f"{name}: This number isn't on file with the club. Members can turn on texts in their member profile at {get_settings().portal_app_url}."
    contact = " or ".join(c for c in (site.contact_email, site.contact_phone) if c)
    return (f"{name}: Texts about matches, events and dues reminders. "
            f"For help, contact {contact or 'us'} or visit {get_settings().public_site_url}. "
            "Msg & data rates may apply. Reply STOP to opt out.")

_HTTPSMS_DELIVERY_EVENTS = {"message.phone.sent", "message.phone.delivered", "message.send.failed", "message.send.expired"}
# httpSMS reports when the club phone stops (or resumes) checking in; while it's
# offline no text goes out, so this is logged as an error for monitoring.
_HTTPSMS_PHONE_EVENTS = {"phone.heartbeat.offline", "phone.heartbeat.online"}


@webhook_router.post("/sms/httpsms")
async def httpsms_webhook(request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    """Record httpSMS delivery events, STOP/START/HELP replies (each answered with
    a confirmation text) and club phone online/offline alerts (CloudEvents JSON)
    idempotently."""
    signing_key = get_settings().httpsms_webhook_signing_key
    if not signing_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="httpSMS webhook is not configured.")
    if not sms_service.verify_httpsms_token(signing_key, request.headers.get("Authorization", "")):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid signature.")

    payload = await request.json()
    event_type = payload.get("type") or request.headers.get("X-Event-Type", "")
    data = payload.get("data") or {}
    event_id = str(payload.get("id") or "")
    if not event_id or event_type not in _HTTPSMS_DELIVERY_EVENTS | _HTTPSMS_PHONE_EVENTS | {"message.phone.received"}:
        return {"status": "ignored"}

    from app.models import SmsProviderEvent
    if db.get(SmsProviderEvent, f"httpsms:{event_id}"):
        return {"status": "duplicate"}

    if event_type in _HTTPSMS_PHONE_EVENTS:
        db.add(SmsProviderEvent(id=f"httpsms:{event_id}", event_type=event_type))
        db.commit()
        if event_type == "phone.heartbeat.offline":
            logger.error("httpsms_phone_offline", extra={"last_heartbeat": data.get("last_heartbeat_timestamp")})
        else:
            logger.info("httpsms_phone_online")
        return {"status": "recorded"}

    if event_type == "message.phone.received":
        keyword = "" if data.get("encrypted") else str(data.get("content") or "").strip().upper()
        if keyword not in _STOP_WORDS | _START_WORDS | _HELP_WORDS:
            return {"status": "ignored"}
        db.add(SmsProviderEvent(id=f"httpsms:{event_id}", event_type=event_type))
        on_file = 0
        if keyword in _STOP_WORDS:
            on_file = _record_text_consent(db, data.get("contact"), False, "STOP")
        elif keyword in _START_WORDS:
            on_file = _record_text_consent(db, data.get("contact"), True, "START")
        reply = _keyword_reply(db, keyword, on_file)
        # Consent is saved first: a failed confirmation never undoes a STOP.
        db.commit()
        result = sms_service.send_keyword_reply(data.get("contact"), reply)
        if result is not None and not result.ok:
            logger.warning("sms_keyword_reply_failed", extra={"keyword": keyword, "error": result.error})
        return {"status": "recorded"}

    # Expired events carry the message as data.message_id; the others as data.id.
    message_id = str(data.get("message_id") or data.get("id") or "") if event_type == "message.send.expired" else str(data.get("id") or "")
    if not message_id:
        return {"status": "ignored"}

    db.add(SmsProviderEvent(id=f"httpsms:{event_id}", event_type=event_type))
    recipient = db.scalar(select(SmsRecipient).where(SmsRecipient.provider_message_id == message_id))
    if recipient is None:
        db.commit()
        return {"status": "unknown message"}

    if event_type == "message.send.expired" and data.get("is_final") is False:
        db.commit()  # httpSMS will try again
        return {"status": "recorded"}

    when = now_utc()
    if event_type == "message.phone.sent":
        # A late "sent" never moves a delivered or failed message backwards.
        if recipient.status == "queued":
            recipient.status = "sent"
        recipient.sent_at = recipient.sent_at or when
    elif event_type == "message.phone.delivered":
        recipient.status = "delivered"
        recipient.delivered_at = recipient.delivered_at or when
    else:
        recipient.status = "failed"
        recipient.failed_at = recipient.failed_at or when
        recipient.error_code = "expired" if event_type == "message.send.expired" else (str(data.get("error_message") or "")[:80] or None)
        recipient.error = (
            "The club phone didn't send the text in time."
            if event_type == "message.send.expired"
            else f"The club phone couldn't send the text ({data.get('error_message') or 'unknown error'})."
        )

    db.commit()
    return {"status": "recorded"}


# ---------------------------------------------------------------------------
# Provider webhooks
# ---------------------------------------------------------------------------


@webhook_router.post("/email/resend")
async def resend_webhook(request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    body = await request.body()
    secret = get_settings().resend_webhook_secret
    if not email_service.verify_svix_signature(secret, {k.lower(): v for k, v in request.headers.items()}, body):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid signature.")
    import json

    payload = json.loads(body)
    event_type = payload.get("type", "")
    data = payload.get("data") or {}
    message_id = data.get("email_id")
    if not message_id:
        return {"status": "ignored"}
    recipient = db.scalar(select(EmailRecipient).where(EmailRecipient.provider_message_id == message_id))
    if recipient is None:
        return {"status": "unknown message"}
    when = _parse_time(payload.get("created_at")) or now_utc()
    if event_type == "email.delivered":
        recipient.delivered_at = recipient.delivered_at or when
        if recipient.status == "sent":
            recipient.status = "delivered"
    elif event_type == "email.opened":
        recipient.opened_at = recipient.opened_at or when
    elif event_type == "email.clicked":
        recipient.clicked_at = recipient.clicked_at or when
    elif event_type == "email.bounced":
        recipient.bounced_at = when
        bounce = data.get("bounce") or {}
        recipient.bounce_type = (bounce.get("subType") or bounce.get("type") or "")[:100] or None
        recipient.status = "bounced"
    elif event_type == "email.complained":
        recipient.complained_at = when
        recipient.status = "complained"
        # A spam complaint is an unambiguous "stop emailing me".
        if recipient.person_id and (person := db.get(Person, recipient.person_id)) and not person.email_opt_out:
            person.email_opt_out = True
            person.email_opt_out_at = now_utc()
    else:
        return {"status": "ignored"}
    db.commit()
    return {"status": "recorded"}


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
