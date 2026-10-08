"""Contacts, exports, communications + analytics webhooks, renewal jobs, audit log."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import date, timedelta

from sqlalchemy import func, select

from app.core.timeutil import now_utc
from app.models import AuditLog, Document, EmailRecipient, Person, RenewalReminder, SiteSettings
from app.services import renewal
from tests.conftest import email_outbox, sms_outbox
from tests.helpers import FULL_PROFILE, board, member, start, upload


def _person(db, email, **kw) -> Person:
    defaults = {"first_name": email.split("@")[0].title(), "last_name": "Test", "membership_status": "member"}
    person = Person(email=email, **{**defaults, **kw})
    db.add(person)
    db.commit()
    return person


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------


def test_people_filtering_groups_and_search(api, db):
    board(api, db, role="board_member")
    _person(db, "alice@example.com", on_shooting_committee=True, city="Great Bend")
    _person(db, "bob@example.com", membership_status="waiting_list")
    _person(db, "carl@example.com", membership_status="terminated")
    _person(db, "dana@example.com", membership_status="non_member", phone="(620) 555-0199")
    groups = {g["key"]: g["count"] for g in api.get("/api/board/people/groups").json()}
    assert groups["active_members"] == 2 and groups["board"] == 1 and groups["shooting_committee"] == 1
    assert groups["waiting_list"] == 1 and groups["former"] == 1 and groups["non_members"] == 1

    committee = api.get("/api/board/people?group=shooting_committee").json()
    assert [p["email"] for p in committee["items"]] == ["alice@example.com"]
    assert set(committee["items"][0]["groups"]) == {"active_members", "shooting_committee"}
    multi = api.get("/api/board/people?group=waiting_list&group=former").json()
    assert {p["email"] for p in multi["items"]} == {"bob@example.com", "carl@example.com"}
    assert api.get("/api/board/people?q=555-0199").json()["items"][0]["email"] == "dana@example.com"
    assert api.get("/api/board/people?group=bogus").status_code == 400


def test_board_edits_contact_and_status_with_audit(api, db):
    board(api, db)
    person = _person(db, "edit@example.com", membership_status="waiting_list")
    response = api.patch(f"/api/board/people/{person.id}", json={
        "membership_status": "member", "on_board": True, "phone": "6205550100", "sms_opt_in": True,
        "nra_number": "987654", "renewal_date": "2027-09-10", "notes": "Paid at meeting",
    })
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["phone"] == "(620) 555-0100" and detail["sms_opt_in_source"].startswith("board:")
    assert "board" in detail["groups"] and detail["member_since"]
    record = api.get(f"/api/board/people/{person.id}").json()
    assert record["person"]["renewal_date"] == "2027-09-10"
    audit_row = db.scalar(select(AuditLog).where(AuditLog.action == "person.status_changed"))
    assert audit_row.details["membership_status"] == ["waiting_list", "member"]
    other = _person(db, "dupe@example.com")
    assert api.patch(f"/api/board/people/{other.id}", json={"nra_number": "987654"}).status_code == 409


def test_member_profile_scoped_to_self(api, new_api, db):
    member(api, "self@example.com", **FULL_PROFILE)
    response = api.patch("/api/me", json={"city": "Ellinwood", "sms_opt_in": True})
    assert response.json()["city"] == "Ellinwood" and response.json()["sms_opt_in"] is True
    # No way to escalate through the profile endpoint.
    assert api.patch("/api/me", json={"membership_status": "member"}).status_code == 422
    assert api.patch("/api/me", json={"email": "x@example.com"}).status_code == 422
    assert api.get("/api/board/people").status_code == 401
    person = db.scalar(select(Person).where(Person.email == "self@example.com"))
    assert person.sms_opt_in_at is not None and person.sms_opt_in_source == "member_portal"


def test_csv_import(api, db):
    board(api, db)
    _person(db, "existing@example.com")
    result = api.post("/api/board/people/import", json={"csv": "name,email,phone\nJane Doe,jane@example.com,620-555-0100\nX,existing@example.com,\n,bad,\n"}).json()
    assert result == {"created": 1, "skipped": 1, "errors": ["Line 4: missing name or email"]}


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------


def test_exports_formats_injection_guard_and_audit(api, new_api, db):
    board(api, db, role="treasurer")
    _person(db, "label@example.com", address_line1="=HYPERLINK(1)", city="Great Bend", state="KS", zip_code="67530")
    _person(db, "noaddress@example.com", email_opt_out=True)
    labels = api.get("/api/board/exports/contacts.csv?format=postal_labels&group=active_members")
    assert labels.status_code == 200 and "attachment" in labels.headers["content-disposition"]
    text = labels.text.lstrip("﻿")
    assert "'=HYPERLINK(1)" in text and "noaddress" not in text
    mailing = api.get("/api/board/exports/contacts.csv?format=mailing_list").text
    assert "label@example.com" in mailing and "noaddress@example.com" not in mailing
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "export.contacts").order_by(AuditLog.id))
    assert entry.details["format"] == "postal_labels" and entry.details["count"] == 1

    restricted = new_api()
    board(restricted, db, "bm@example.com", "board_member")
    assert restricted.get("/api/board/exports/contacts.csv").status_code == 403


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------


def svix_headers(body: bytes, secret: str = "whsec_dGVzdC1yZXNlbmQtc2VjcmV0") -> dict[str, str]:
    msg_id, ts = "msg_1", str(int(time.time()))
    key = base64.b64decode(secret.removeprefix("whsec_"))
    sig = base64.b64encode(hmac.new(key, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()).decode()
    return {"svix-id": msg_id, "svix-timestamp": ts, "svix-signature": f"v1,{sig}", "content-type": "application/json"}


def test_email_campaign_to_groups_with_unsubscribe_and_analytics(api, new_api, db):
    board(api, db, role="board_member")
    _person(db, "m1@example.com")
    _person(db, "m2@example.com", email_opt_out=True)
    _person(db, "w1@example.com", membership_status="waiting_list")
    audience = api.post("/api/board/email/audience", json={"groups": ["active_members"]}).json()
    assert audience["count"] == 2 and audience["excluded_unsubscribed"] == 1  # m1 + the president
    preview = api.post("/api/board/email/preview", json={"subject": "Hi", "body_html": "<p>Hello<script>x</script></p>"}).json()
    assert "<script>" not in preview["html"] and "Unsubscribe" in preview["html"]
    attachment = api.post("/api/board/email/attachments", files={"file": ("flyer.pdf", b"%PDF-1.4 test", "application/pdf")}).json()

    sent = api.post("/api/board/email/send", json={
        "subject": "Work day Saturday", "body_html": '<p>Join us. <a href="https://kiowagunclub.org">Details</a></p>',
        "groups": ["active_members"], "person_ids": [db.scalar(select(Person.id).where(Person.email == "w1@example.com"))],
        "attachment_ids": [attachment["id"]],
    }).json()
    assert sent["sent"] == 3 and sent["failed"] == 0
    messages = [m for m in email_outbox() if m.subject == "Work day Saturday"]
    assert {m.to for m in messages} == {"m1@example.com", "w1@example.com", "president@example.com"}
    assert messages[0].attachments[0].filename == "flyer.pdf"
    assert "List-Unsubscribe" in messages[0].headers and "/unsubscribe?token=" in messages[0].html

    recipient = db.scalar(select(EmailRecipient).where(EmailRecipient.email == "m1@example.com"))
    for event in ("email.delivered", "email.opened", "email.clicked"):
        body = json.dumps({"type": event, "created_at": "2026-10-02T15:00:00Z", "data": {"email_id": recipient.provider_message_id}}).encode()
        assert api.client.post("/api/webhooks/email/resend", content=body, headers=svix_headers(body)).json()["status"] == "recorded"
    forged = json.dumps({"type": "email.opened", "data": {"email_id": recipient.provider_message_id}}).encode()
    assert api.client.post("/api/webhooks/email/resend", content=forged, headers=svix_headers(forged, "whsec_d3Jvbmc=")).status_code == 401

    complaint_target = db.scalar(select(EmailRecipient).where(EmailRecipient.email == "w1@example.com"))
    body = json.dumps({"type": "email.complained", "data": {"email_id": complaint_target.provider_message_id}}).encode()
    api.client.post("/api/webhooks/email/resend", content=body, headers=svix_headers(body))

    campaign = api.get("/api/board/email/campaigns").json()[0]
    assert (campaign["sent"], campaign["delivered"], campaign["opened"], campaign["clicked"], campaign["complained"]) == (3, 1, 1, 1, 1)
    assert db.scalar(select(Person).where(Person.email == "w1@example.com")).email_opt_out is True

    # One-click unsubscribe from the email link.
    m1 = db.scalar(select(Person).where(Person.email == "m1@example.com"))
    assert new_api().post(f"/api/public/unsubscribe?token={m1.unsubscribe_token}").status_code == 200
    db.refresh(m1)
    assert m1.email_opt_out


def test_communications_require_board(api, new_api, db):
    member(api, "nosy@example.com")
    assert api.post("/api/board/email/send", json={"subject": "x", "body_html": "<p>x</p>", "groups": ["active_members"]}).status_code == 401


# ---------------------------------------------------------------------------
# SMS
# ---------------------------------------------------------------------------


def test_sms_only_reaches_consenting_contacts(api, db):
    board(api, db)
    _person(db, "yes@example.com", phone="(620) 555-0101", sms_opt_in=True, sms_opt_in_at=now_utc())
    _person(db, "no@example.com", phone="(620) 555-0102", sms_opt_in=False)
    _person(db, "flag-only@example.com", phone="(620) 555-0103", sms_opt_in=True)  # no recorded consent timestamp
    audience = api.post("/api/board/sms/audience", json={"groups": ["active_members"]}).json()
    assert audience["count"] == 1 and audience["no_consent"] == 3  # includes the president (no consent)

    check = api.post("/api/board/sms/check", json={"body": "Rifle match Saturday, bring ammo"}).json()
    assert set(check["risky_words"]) == {"ammo", "rifle"} and "rifle" not in check["safe_body"].lower()

    sent = api.post("/api/board/sms/send", json={"body": "Rifle match Saturday", "groups": ["active_members"], "use_safe_version": True}).json()
    assert sent["sent"] == 1 and sent["skipped_no_consent"] == 3 and sent["emailed_instead"] == 0
    assert sms_outbox() == [("+16205550101", sent["body_sent"])]
    campaign = api.get("/api/board/sms/campaigns").json()[0]
    assert (campaign["sent"], campaign["failed"], campaign["skipped_no_consent"]) == (1, 0, 3)


def test_failed_text_is_emailed_instead(api, db):
    board(api, db)
    _person(db, "badphone@example.com", phone="555-01", sms_opt_in=True, sms_opt_in_at=now_utc())
    _person(db, "badphone-unsub@example.com", phone="12", sms_opt_in=True, sms_opt_in_at=now_utc(), email_opt_out=True)
    sent = api.post("/api/board/sms/send", json={"body": "Rifle match Saturday", "groups": ["active_members"], "use_safe_version": True}).json()
    assert (sent["sent"], sent["failed"], sent["emailed_instead"]) == (0, 2, 1)
    fallback = [m for m in email_outbox() if m.to == "badphone@example.com"]
    # The email carries the board's original wording (no carrier filtering).
    assert len(fallback) == 1 and "Rifle match Saturday" in fallback[0].html
    assert not [m for m in email_outbox() if m.to == "badphone-unsub@example.com"]
    detail = api.get(f"/api/board/sms/campaigns/{sent['campaign_id']}").json()
    assert sorted(r["emailed_instead"] for r in detail["recipients"]) == [False, True]
    skipped = api.post("/api/board/sms/send", json={"body": "Hi", "groups": ["active_members"], "email_if_text_fails": False}).json()
    assert skipped["emailed_instead"] == 0


class FakeLookup:
    def __init__(self, carrier: str | None) -> None:
        self.carrier, self.calls = carrier, 0

    def lookup(self, phone_e164: str):  # noqa: ANN201
        self.calls += 1
        return (self.carrier, None) if self.carrier else (None, "Phone number is not valid")


def test_gateway_provider_caches_carrier_and_emails_gateway(db):
    from app.services import membership
    from app.services import sms as sms_service

    person = _person(db, "verizon@example.com", phone="(620) 555-0199", sms_opt_in=True, sms_opt_in_at=now_utc())
    lookup = FakeLookup("Verizon Wireless")
    provider = sms_service.GatewaySmsProvider(lookup)
    first = provider.send(person, "Range closed Saturday")
    assert first.ok and first.gateway_address == "6205550199@vtext.com" and person.sms_carrier == "Verizon Wireless"
    gateway_mail = [m for m in email_outbox() if m.to == "6205550199@vtext.com"][0]
    assert gateway_mail.text == "Range closed Saturday" and gateway_mail.html == "" and gateway_mail.from_override
    provider.send(person, "Again")
    assert lookup.calls == 1  # cached
    membership.update_profile(db, person, {"phone": "(620) 555-0198"}, source="test")
    assert person.sms_carrier is None  # new number, new lookup

    assert sms_service.gateway_domain_for_carrier("Metro by T-Mobile") == "mymetropcs.com"
    assert sms_service.gateway_domain_for_carrier("T-Mobile USA") == "tmomail.net"
    assert sms_service.gateway_domain_for_carrier("AT&T Mobility") == "txt.att.net"
    unsupported = sms_service.GatewaySmsProvider(FakeLookup("Some Rural Cellular")).send(person, "x")
    assert not unsupported.ok and "can't be sent" in (unsupported.error or "")
    invalid = sms_service.GatewaySmsProvider(FakeLookup(None)).send(person, "x")
    assert not invalid.ok


def test_httpsms_provider_sends_from_club_phone(db, monkeypatch):
    import httpx

    from app.core.config import get_settings
    from app.services import sms as sms_service

    settings = get_settings()
    monkeypatch.setattr(settings, "httpsms_api_key", "httpsms-test-key")
    monkeypatch.setattr(settings, "httpsms_from_number", "+16205550100")
    calls = []

    def fake_post(url, json, headers, timeout):  # noqa: ANN001, ANN202, A002
        calls.append((url, json, headers))
        status = 201 if json["to"] != "+16205550177" else 422
        body = {"data": {"id": "msg-123", "status": "pending"}} if status == 201 else {"message": "invalid phone"}
        return httpx.Response(status, json=body)

    monkeypatch.setattr(sms_service.httpx, "post", fake_post)
    person = _person(db, "httpsms@example.com", phone="(620) 555-0144", sms_opt_in=True, sms_opt_in_at=now_utc())
    result = sms_service.HttpSmsProvider().send(person, "Range closed Saturday", media_url="https://example.com/a.png")
    assert result.ok and result.message_id == "msg-123"
    assert calls == [(sms_service.HTTPSMS_SEND_URL,
                      {"from": "+16205550100", "to": "+16205550144", "content": "Range closed Saturday", "attachments": ["https://example.com/a.png"]},
                      {"x-api-key": "httpsms-test-key"})]

    person.phone = "(620) 555-0177"
    rejected = sms_service.HttpSmsProvider().send(person, "x")
    assert not rejected.ok and "422" in (rejected.error or "") and "invalid phone" in (rejected.error or "")


def httpsms_token(key: str = "httpsms-signing-key", **claims) -> str:  # noqa: ANN003
    def b64(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()
    signing_input = f"{b64({'alg': 'HS256', 'typ': 'JWT'})}.{b64({'exp': int(time.time()) + 300, **claims})}"
    signature = base64.urlsafe_b64encode(hmac.new(key.encode(), signing_input.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    return f"Bearer {signing_input}.{signature}"


def test_httpsms_webhook_records_delivery(api, db, monkeypatch):
    from app.core.config import get_settings
    from app.models import SmsRecipient

    monkeypatch.setattr(get_settings(), "httpsms_webhook_signing_key", "httpsms-signing-key")
    board(api, db)
    _person(db, "delivered@example.com", phone="(620) 555-0111", sms_opt_in=True, sms_opt_in_at=now_utc())
    _person(db, "expired@example.com", phone="(620) 555-0112", sms_opt_in=True, sms_opt_in_at=now_utc())
    sent = api.post("/api/board/sms/send", json={"body": "Range closed", "groups": ["active_members"], "email_if_text_fails": False}).json()
    recipients = {r.phone: r for r in db.scalars(select(SmsRecipient).where(SmsRecipient.campaign_id == sent["campaign_id"]))}
    delivered, expired = recipients["(620) 555-0111"], recipients["(620) 555-0112"]

    def post(event_id, event_type, data, token=None):  # noqa: ANN001, ANN202
        return api.client.post("/api/webhooks/sms/httpsms", json={"id": event_id, "type": event_type, "specversion": "1.0", "data": data},
                               headers={"Authorization": token or httpsms_token(), "X-Event-Type": event_type})

    event = ("evt-1", "message.phone.delivered", {"id": delivered.provider_message_id})
    assert post(*event, token=httpsms_token("wrong-key")).status_code == 401
    assert post(*event, token=httpsms_token(exp=int(time.time()) - 3600)).status_code == 401
    assert post(*event).json() == {"status": "recorded"}
    assert post(*event).json() == {"status": "duplicate"}
    assert post("evt-2", "message.phone.sent", {"id": delivered.provider_message_id}).json() == {"status": "recorded"}

    assert post("evt-3", "message.send.expired", {"message_id": expired.provider_message_id, "is_final": False}).json() == {"status": "recorded"}
    db.refresh(expired)
    assert expired.status == "sent"
    assert post("evt-4", "message.send.expired", {"message_id": expired.provider_message_id, "is_final": True}).json() == {"status": "recorded"}
    assert post("evt-5", "message.phone.received", {"id": "inbound"}).json() == {"status": "ignored"}

    db.refresh(delivered)
    db.refresh(expired)
    assert delivered.status == "delivered" and delivered.delivered_at is not None
    assert expired.status == "failed" and expired.error_code == "expired"


# ---------------------------------------------------------------------------
# Renewal cycle & scheduled jobs
# ---------------------------------------------------------------------------


def test_next_cutoff_after_payment(db):
    settings_row = db.get(SiteSettings, 1)
    assert renewal.next_cutoff_after_payment(settings_row, None, date(2026, 8, 1)) == date(2026, 9, 10)
    assert renewal.next_cutoff_after_payment(settings_row, None, date(2026, 9, 11)) == date(2027, 9, 10)
    # Renewing early extends to the following year rather than re-stamping.
    assert renewal.next_cutoff_after_payment(settings_row, date(2026, 9, 10), date(2026, 8, 1)) == date(2027, 9, 10)


def test_paid_up_depends_on_dues_season(db):
    settings_row = db.get(SiteSettings, 1)
    paid_2026 = Person(first_name="A", last_name="B", email="x@example.com", renewal_date=date(2026, 9, 10))
    # Mid-season for 2026: paid through 2026 counts as paid up.
    assert renewal.renewal_summary(settings_row, paid_2026, date(2026, 8, 15))["is_current"] is True
    # October: 2027 dues aren't due yet, so still paid up.
    assert renewal.renewal_summary(settings_row, paid_2026, date(2026, 10, 2))["is_current"] is True
    # Inside the 45-day window before the 2027 cutoff: now owes 2027 dues.
    assert renewal.renewal_summary(settings_row, paid_2026, date(2027, 8, 1))["is_current"] is False


def test_renewal_reminders_are_idempotent_and_respect_consent(db):
    today = date(2026, 7, 28)  # 44 days before Sept 10
    _person(db, "due@example.com", phone="(620) 555-0110", sms_opt_in=True, sms_opt_in_at=now_utc(), renewal_date=date(2025, 9, 10))
    _person(db, "nosms@example.com", renewal_date=None)
    _person(db, "paid@example.com", renewal_date=date(2026, 9, 10))
    first = renewal.send_renewal_reminders(db, today)
    assert (first.emails_sent, first.sms_sent, first.skipped_no_consent) == (2, 1, 1)
    again = renewal.send_renewal_reminders(db, today)
    assert (again.emails_sent, again.sms_sent) == (0, 0)
    fifteen = renewal.send_renewal_reminders(db, date(2026, 8, 27))
    assert (fifteen.emails_sent, fifteen.sms_sent) == (2, 1)
    assert db.scalar(select(func.count()).select_from(RenewalReminder)) == 6  # consenting member: 2 thresholds x 2 channels; the other: email only
    assert not [m for m in email_outbox() if m.to == "paid@example.com"]
    from app.models import EmailCampaign, SmsCampaign

    assert [c.sent_count for c in db.scalars(select(EmailCampaign).where(EmailCampaign.kind == "renewal_reminder"))] == [2, 2]
    assert [c.sent_count for c in db.scalars(select(SmsCampaign).where(SmsCampaign.kind == "renewal_reminder"))] == [1, 1]


def test_termination_sweep_runs_once_and_keeps_history(api, db):
    member(api, "lapsed@example.com", **FULL_PROFILE)
    application = start(api)
    upload(api, application["id"], "nra_proof")
    person = db.scalar(select(Person).where(Person.email == "lapsed@example.com"))
    person.membership_status, person.renewal_date = "member", date(2025, 9, 10)
    current = _person(db, "current@example.com", renewal_date=date(2026, 9, 10))
    db.commit()
    assert renewal.run_termination_sweep(db, date(2026, 9, 10))["ran"] is False  # cutoff day itself is still OK
    result = renewal.run_termination_sweep(db, date(2026, 9, 11))
    assert result == {"ran": True, "terminated": 1}
    assert renewal.run_termination_sweep(db, date(2026, 9, 12))["ran"] is False
    db.refresh(person)
    db.refresh(current)
    assert person.membership_status == "terminated" and person.email == "lapsed@example.com"
    assert current.membership_status == "member"
    assert db.scalar(select(Document).where(Document.person_id == person.id)).purged_at is not None


def test_nra_expiration_check(db):
    person = _person(db, "nra@example.com", nra_expiration_date=date.today() - timedelta(days=1))
    assert renewal.run_nra_expiration_check(db) == 1
    db.refresh(person)
    assert person.nra_active is False
    assert renewal.run_nra_expiration_check(db) == 0


def test_job_http_trigger_requires_secret(api):
    assert api.client.post("/api/jobs/daily").status_code == 401
    assert api.client.post("/api/jobs/daily", headers={"Authorization": "Bearer wrong"}).status_code == 401
    response = api.client.post("/api/jobs/nra-check", headers={"Authorization": "Bearer cron-test-secret"})
    assert response.status_code == 200 and response.json() == {"nra-check": {"suspended": 0}}


# ---------------------------------------------------------------------------
# Dashboard & audit log
# ---------------------------------------------------------------------------


def test_dashboard_and_audit_log(api, new_api, db):
    board(api, db)
    data = api.get("/api/board/dashboard").json()
    assert {"applications", "groups", "renewal", "upcoming_events", "payments", "locked_board_accounts", "needs_attention"} <= set(data)
    assert data["renewal"]["members_paid_up"] == 0
    restricted = new_api()
    board(restricted, db, "bm@example.com", "board_member")
    assert "payments" not in restricted.get("/api/board/dashboard").json()

    log = api.get("/api/board/audit?action=board.").json()
    assert log["total"] >= 2 and all(item["action"].startswith("board.") for item in log["items"])
    serialized = json.dumps(api.get("/api/board/audit").json())
    assert "password" not in serialized.lower() or "password_reset" in serialized
