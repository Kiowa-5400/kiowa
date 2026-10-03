"""Applications, document uploads/authorization/review, eligibility, payments and the full workflows."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.models import Application, AuditLog, Document, Payment, Person
from app.services import payments as payment_service
from tests.conftest import email_outbox, sms_outbox
from tests.helpers import (
    FULL_PROFILE,
    JPEG,
    PDF,
    PNG,
    FakeGateway,
    board,
    completed_event,
    member,
    post_webhook,
    stripe_signature,
    submit,
    upload,
)


@pytest.fixture
def gateway(monkeypatch):
    fake = FakeGateway()
    monkeypatch.setattr(payment_service, "get_gateway", lambda: fake)
    return fake


def start(api, kind: str = "renewal") -> dict:
    response = api.post("/api/applications", json={"application_type": kind})
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Form definition & submission validation
# ---------------------------------------------------------------------------


def test_form_definition_matches_frontend_contract(api):
    form = api.get("/api/application/form").json()
    assert {t["value"] for t in form["application_types"]} == {"renewal", "waiting_list"}
    assert len(form["rules"]["rules"]) == 18
    assert form["rules"]["version"] == "2026-10-01"
    assert form["dues_amount"] == "150.00"
    assert form["background_check_url"] == "https://www.criminalwatchdog.com"


def test_submission_requires_documents_rules_and_matching_signature(api):
    member(api, "renew@example.com", **FULL_PROFILE)
    application = start(api)
    response = submit(api, application["id"])
    assert response.status_code == 422
    assert "document_nra_proof" in response.json()["errors"]

    assert upload(api, application["id"], "nra_proof").status_code == 201
    rules = api.get("/api/application/form").json()["rules"]
    bad = api.post(f"/api/applications/{application['id']}/submit",
                   json={"rules_version": rules["version"], "accept_rules": False, "printed_name": "Pat Shooter", "signature_name": "Someone Else"})
    errors = bad.json()["errors"]
    assert {"accept_rules", "signature_name"} <= set(errors)
    stale = api.post(f"/api/applications/{application['id']}/submit",
                     json={"rules_version": "1999-01-01", "accept_rules": True, "printed_name": "Pat Shooter", "signature_name": "Pat Shooter"})
    assert "rules_version" in stale.json()["errors"]

    ok = submit(api, application["id"])
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["status"] == "submitted" and body["rules_version"] == rules["version"]
    assert body["signature_name"] == "Pat Shooter" and body["signed_at"]
    assert any("received" in m.subject for m in email_outbox() if m.to == "renew@example.com")


def test_missing_profile_and_expired_nra_block_submission(api):
    member(api, "incomplete@example.com")
    application = start(api)
    upload(api, application["id"], "nra_proof")
    errors = submit(api, application["id"]).json()["errors"]
    assert {"phone", "address_line1", "nra_expiration_date", "nra_number"} <= set(errors)
    api.patch("/api/me", json={**FULL_PROFILE, "nra_expiration_date": (date.today() - timedelta(days=1)).isoformat()})
    assert "expired" in submit(api, application["id"]).json()["errors"]["nra_expiration_date"]


def test_cleanup_discount_document_required_only_when_claimed(api):
    member(api, "discount@example.com", **FULL_PROFILE)
    application = start(api)
    upload(api, application["id"], "nra_proof")
    api.patch(f"/api/applications/{application['id']}", json={"claims_cleanup_discount": True})
    assert "document_cleanup_discount" in submit(api, application["id"]).json()["errors"]
    upload(api, application["id"], "cleanup_discount", PNG, "card.png", "image/png")
    assert submit(api, application["id"]).status_code == 200


def test_waiting_list_needs_background_check_or_ccl_not_both(api):
    member(api, "wait@example.com", **{**FULL_PROFILE, "nra_number": None})
    application = start(api, "waiting_list")
    upload(api, application["id"], "nra_proof")
    errors = submit(api, application["id"]).json()["errors"]
    assert "documentation_method" in errors
    api.patch(f"/api/applications/{application['id']}", json={"documentation_method": "concealed_carry"})
    errors = submit(api, application["id"]).json()["errors"]
    assert "document_concealed_carry" in errors and "document_background_check" not in errors
    upload(api, application["id"], "concealed_carry", JPEG, "ccl.jpg", "image/jpeg")
    assert submit(api, application["id"]).status_code == 200


def test_only_one_open_application(api):
    member(api, "one@example.com", **FULL_PROFILE)
    first = start(api)
    second = start(api)
    assert first["id"] == second["id"]


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


def test_upload_validates_signature_type_extension_and_size(api):
    member(api, "files@example.com", **FULL_PROFILE)
    application = start(api)
    fake_pdf = upload(api, application["id"], "nra_proof", b"<script>alert(1)</script>", "proof.pdf", "application/pdf")
    assert fake_pdf.status_code == 400
    mislabeled = upload(api, application["id"], "nra_proof", PDF, "proof.png", "image/png")
    assert mislabeled.status_code == 400
    wrong_ext = upload(api, application["id"], "nra_proof", PNG, "proof.exe", "image/png")
    assert wrong_ext.status_code == 400
    too_big = upload(api, application["id"], "nra_proof", PDF + b"0" * (11 * 1024 * 1024), "big.pdf")
    assert too_big.status_code == 400
    not_applicable = upload(api, application["id"], "background_check")
    assert not_applicable.status_code == 400
    ok = upload(api, application["id"], "nra_proof", PNG, "card.png", "image/png")
    assert ok.status_code == 201 and ok.json()["mime_type"] == "image/png"


def test_document_storage_is_private_and_owner_scoped(api, new_api, db):
    member(api, "owner@example.com", **FULL_PROFILE)
    application = start(api)
    document = upload(api, application["id"], "nra_proof").json()
    stored = db.get(Document, document["id"])
    assert stored.storage_key.startswith("private/documents/") and "proof" not in stored.storage_key
    assert stored.sha256 and stored.size_bytes == len(PDF)

    own = api.get(f"/api/documents/{document['id']}/file")
    assert own.status_code == 200 and own.content == PDF
    assert own.headers["cache-control"] == "private, no-store"

    intruder = new_api()
    member(intruder, "intruder@example.com")
    assert intruder.get(f"/api/documents/{document['id']}/file").status_code == 404
    assert intruder.get(f"/api/applications/{application['id']}").status_code == 404
    assert intruder.post(f"/api/applications/{application['id']}/documents", data={"document_type": "nra_proof"},
                         files={"file": ("x.pdf", PDF, "application/pdf")}).status_code == 404
    assert new_api().get(f"/api/documents/{document['id']}/file").status_code == 401
    # Nothing private is served from a public route.
    assert api.get(f"/api/public/documents/{document['id']}/file").status_code == 404


def test_board_document_review_queue_and_audit(api, new_api, db):
    member(api, "reviewme@example.com", **FULL_PROFILE)
    application = start(api)
    document = upload(api, application["id"], "nra_proof").json()
    submit(api, application["id"])

    reviewer = new_api()
    board(reviewer, db, "reviewer@example.com", "board_member")
    queue = reviewer.get("/api/board/documents").json()
    assert [item["id"] for item in queue["items"]] == [document["id"]]
    assert reviewer.get(f"/api/board/documents/{document['id']}/file").content == PDF
    reviewed = reviewer.post(f"/api/board/documents/{document['id']}/review", json={"review_status": "approved", "notes": "Card valid"})
    assert reviewed.json()["review_status"] == "approved"
    # Approving NRA proof verifies NRA on the application.
    assert db.get(Application, application["id"]).nra_verified_at is not None
    actions = set(db.scalars(select(AuditLog.action)))
    assert {"document.viewed", "document.approved", "application.nra_verified", "document.uploaded"} <= actions


# ---------------------------------------------------------------------------
# Review decisions & eligibility
# ---------------------------------------------------------------------------


def _submitted_renewal(api, email="flow@example.com") -> dict:
    member(api, email, **FULL_PROFILE)
    application = start(api)
    upload(api, application["id"], "nra_proof")
    assert submit(api, application["id"]).status_code == 200
    return application


def test_payment_blocked_until_board_approves(api, new_api, db, gateway):
    application = _submitted_renewal(api)
    blocked = api.post(f"/api/applications/{application['id']}/checkout")
    assert blocked.status_code == 409 and "not approved" in blocked.json()["detail"]
    detail = api.get(f"/api/applications/{application['id']}").json()
    assert detail["eligibility"]["eligible"] is False

    reviewer = new_api()
    board(reviewer, db)
    # Approval needs verified NRA proof.
    refused = reviewer.post(f"/api/board/applications/{application['id']}/approve", json={"send_payment_request": False})
    assert refused.status_code == 409
    approved = reviewer.post(f"/api/board/applications/{application['id']}/approve", json={"verify_nra": True, "send_payment_request": False})
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    still_blocked = api.post(f"/api/applications/{application['id']}/checkout")
    assert "opened payment" in still_blocked.json()["detail"]
    board_view = reviewer.get(f"/api/board/applications/{application['id']}").json()
    assert board_view["eligibility"]["eligible"] is False

    reviewer.post(f"/api/board/applications/{application['id']}/payment-request")
    assert db.get(Application, application["id"]).payment_eligible is True
    assert any("/pay" in m.html for m in email_outbox() if m.to == "flow@example.com")


def test_request_info_and_resubmit(api, new_api, db):
    application = _submitted_renewal(api, "info@example.com")
    reviewer = new_api()
    board(reviewer, db)
    reviewer.post(f"/api/board/applications/{application['id']}/request-info", json={"message": "Please upload a clearer NRA card."})
    mine = api.get(f"/api/applications/{application['id']}").json()
    assert mine["status"] == "needs_info" and "clearer" in mine["info_request_message"]
    upload(api, application["id"], "nra_proof", PNG, "clear.png", "image/png")
    assert submit(api, application["id"]).json()["status"] == "submitted"
    reviewer.post(f"/api/board/applications/{application['id']}/notes", json={"body": "Looks good now"})
    notes = reviewer.get(f"/api/board/applications/{application['id']}").json()["notes"]
    assert notes[0]["body"] == "Looks good now"


def test_decline_waiting_list_returns_person_to_non_member(api, new_api, db):
    member(api, "decline@example.com", **FULL_PROFILE)
    application = start(api, "waiting_list")
    api.patch(f"/api/applications/{application['id']}", json={"documentation_method": "background_check"})
    upload(api, application["id"], "nra_proof")
    upload(api, application["id"], "background_check")
    submit(api, application["id"])
    person = db.scalar(select(Person).where(Person.email == "decline@example.com"))
    assert person.membership_status == "waiting_list"
    reviewer = new_api()
    board(reviewer, db)
    reviewer.post(f"/api/board/applications/{application['id']}/decline", json={"reason": "Incomplete check", "notify_applicant": True})
    db.refresh(person)
    assert person.membership_status == "non_member"


def test_eligibility_reasons_for_waiting_list(api, new_api, db, gateway):
    member(api, "elig@example.com", **FULL_PROFILE)
    application = start(api, "waiting_list")
    api.patch(f"/api/applications/{application['id']}", json={"documentation_method": "background_check"})
    upload(api, application["id"], "nra_proof")
    upload(api, application["id"], "background_check")
    submit(api, application["id"])
    reviewer = new_api()
    board(reviewer, db)
    refused = reviewer.post(f"/api/board/applications/{application['id']}/approve", json={"verify_nra": True})
    assert refused.status_code == 409 and "background check" in refused.json()["detail"]
    approved = reviewer.post(f"/api/board/applications/{application['id']}/approve", json={"verify_nra": True, "clear_background_check": True})
    assert approved.json()["eligibility"]["eligible"] is True
    # The board can revoke clearance; eligibility follows immediately.
    reviewer.post(f"/api/board/applications/{application['id']}/background-check?cleared=false")
    eligibility = api.get(f"/api/applications/{application['id']}").json()["eligibility"]
    assert eligibility["eligible"] is False and any("background check" in r for r in eligibility["reasons"])
    assert db.get(Application, application["id"]).payment_block_reason


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------


def _approved(api, new_api, db, email="pay@example.com"):
    application = _submitted_renewal(api, email)
    reviewer = new_api()
    board(reviewer, db, f"board-{email}")
    reviewer.post(f"/api/board/applications/{application['id']}/approve", json={"verify_nra": True})
    return application, reviewer


def test_checkout_uses_server_side_amount_and_metadata(api, new_api, db, gateway):
    application, _ = _approved(api, new_api, db)
    response = api.post(f"/api/applications/{application['id']}/checkout", json={"amount": 1})
    assert response.status_code == 200, response.text
    assert response.json()["checkout_url"].startswith("https://checkout.stripe.com/")
    session = next(iter(gateway.sessions.values()))
    assert session["params"]["line_items"][0]["price_data"]["unit_amount"] == 15000
    assert session["params"]["metadata"]["application_id"] == str(application["id"])
    assert "{CHECKOUT_SESSION_ID}" in session["params"]["success_url"]
    # Stripe returns members to the portal, not the application form.
    assert session["params"]["success_url"].startswith("http://localhost:5174/payments/return")
    assert session["params"]["cancel_url"] == f"http://localhost:5174/applications/{application['id']}/pay?cancelled=1"
    payment = db.scalar(select(Payment))
    assert payment.status == "pending" and payment.stripe_checkout_session_id == session["id"]
    # Returning from Stripe changes nothing: still pending until the webhook.
    status = api.get(f"/api/payments/checkout-status?session_id={session['id']}").json()
    assert status["status"] == "pending"


def test_webhook_rejects_bad_signatures(api, new_api, db, gateway):
    application, _ = _approved(api, new_api, db)
    api.post(f"/api/applications/{application['id']}/checkout")
    session = next(iter(gateway.sessions.values()))
    payload = completed_event(session)
    assert post_webhook(api, payload, "t=1,v1=deadbeef").status_code == 400
    assert post_webhook(api, payload, stripe_signature(payload, secret="whsec_wrong")).status_code == 400
    stale = stripe_signature(payload, timestamp=1_600_000_000)
    assert post_webhook(api, payload, stale).status_code == 400
    assert db.scalar(select(Payment)).status == "pending"


def test_webhook_records_payment_once_and_activates_membership(api, new_api, db, gateway):
    application, _ = _approved(api, new_api, db)
    api.post(f"/api/applications/{application['id']}/checkout")
    session = next(iter(gateway.sessions.values()))
    payload = completed_event(session)
    first = post_webhook(api, payload)
    assert first.status_code == 200 and first.json()["status"] == "processed"
    duplicate = post_webhook(api, payload)
    assert duplicate.json()["status"] == "duplicate"
    # A different event for the same session is also a no-op.
    assert post_webhook(api, completed_event(session, event_id="evt_test_2")).json()["status"] == "processed"

    payments = db.scalars(select(Payment)).all()
    assert len(payments) == 1 and payments[0].status == "paid" and payments[0].paid_at
    person = db.scalar(select(Person).where(Person.email == "pay@example.com"))
    assert person.membership_status == "member" and person.renewal_date is not None
    assert person.renewal_date.month == 9 and person.renewal_date.day == 10
    assert payments[0].covers_through == person.renewal_date
    app_row = db.get(Application, application["id"])
    assert app_row.status == "completed" and app_row.payment_status == "paid"
    assert len([m for m in email_outbox() if m.to == "pay@example.com" and "payment received" in m.subject]) == 1
    assert api.get(f"/api/payments/checkout-status?session_id={session['id']}").json()["status"] == "paid"


def test_amount_mismatch_is_not_fulfilled(api, new_api, db, gateway):
    application, _ = _approved(api, new_api, db)
    api.post(f"/api/applications/{application['id']}/checkout")
    session = next(iter(gateway.sessions.values()))
    post_webhook(api, completed_event(session, amount_total=100))
    assert db.scalar(select(Payment)).status == "failed"
    assert db.get(Application, application["id"]).status == "approved"


def test_expired_session_and_async_failure(api, new_api, db, gateway):
    application, _ = _approved(api, new_api, db)
    api.post(f"/api/applications/{application['id']}/checkout")
    session = next(iter(gateway.sessions.values()))
    payload = json.dumps({"id": "evt_exp", "type": "checkout.session.expired", "data": {"object": {"id": session["id"]}}}).encode()
    post_webhook(api, payload)
    assert db.scalar(select(Payment)).status == "cancelled"
    assert db.get(Application, application["id"]).payment_status == "unpaid"


def test_refund_and_reconciliation(api, new_api, db, gateway):
    application, reviewer = _approved(api, new_api, db)
    api.post(f"/api/applications/{application['id']}/checkout")
    session = next(iter(gateway.sessions.values()))
    # Webhook never arrived; reconciliation asks Stripe directly.
    session.update({"payment_status": "paid", "payment_intent": "pi_test_123"})
    db.execute(Payment.__table__.update().values(created_at=Payment.created_at - timedelta(hours=2)))
    db.commit()
    assert reviewer.post("/api/board/payments/reconcile").json()["paid"] == 1
    payment = db.scalar(select(Payment))
    db.refresh(payment)
    assert payment.status == "paid"

    too_much = reviewer.post(f"/api/board/payments/{payment.id}/refund", json={"amount": "200.00", "reason": "x"})
    assert too_much.status_code == 422
    partial = reviewer.post(f"/api/board/payments/{payment.id}/refund", json={"amount": "50.00", "reason": "Cleanup discount"})
    assert partial.json()["status"] == "partially_refunded"
    assert gateway.refunds == [("pi_test_123", 5000)]
    # Stripe's charge.refunded webhook carries the absolute total, so it's idempotent.
    refund_event = json.dumps({"id": "evt_ref", "type": "charge.refunded",
                               "data": {"object": {"payment_intent": "pi_test_123", "amount_refunded": 5000}}}).encode()
    post_webhook(api, refund_event)
    db.refresh(payment)
    assert str(payment.refunded_amount) == "50.00"
    assert db.scalar(select(AuditLog).where(AuditLog.action == "payment.refunded")) is not None


def test_manual_payment_and_reporting(api, new_api, db):
    member(api, "cash@example.com", **FULL_PROFILE)
    person = db.scalar(select(Person).where(Person.email == "cash@example.com"))
    treasurer = new_api()
    board(treasurer, db, "treasurer@example.com", "treasurer")
    recorded = treasurer.post("/api/board/payments/manual", json={"person_id": person.id, "amount": "150.00", "method": "check", "notes": "Check #1001"})
    assert recorded.status_code == 201 and recorded.json()["status"] == "paid"
    db.refresh(person)
    assert person.membership_status == "member" and person.renewal_date
    summary = treasurer.get("/api/board/payments/summary").json()
    assert summary["collected"] == "150.00"
    listing = treasurer.get("/api/board/payments?method=check").json()
    assert listing["total"] == 1 and listing["items"][0]["person_name"] == "Pat Shooter"
    history = api.get("/api/me/payments").json()
    assert history[0]["method"] == "check"


# ---------------------------------------------------------------------------
# End-to-end workflows
# ---------------------------------------------------------------------------


def test_end_to_end_renewal(api, new_api, db, gateway):
    """Register/login -> submit renewal -> upload NRA proof -> board review ->
    approve -> Stripe payment -> webhook -> active membership."""
    member(api, "e2e-renew@example.com", **FULL_PROFILE, sms_opt_in=True)
    application = start(api)
    upload(api, application["id"], "nra_proof", JPEG, "nra-card.jpg", "image/jpeg")
    assert submit(api, application["id"]).json()["status"] == "submitted"

    reviewer = new_api()
    board(reviewer, db)
    queue = reviewer.get("/api/board/applications?status=submitted").json()
    assert queue["items"][0]["id"] == application["id"]
    document_id = reviewer.get(f"/api/board/applications/{application['id']}").json()["documents"][0]["id"]
    reviewer.post(f"/api/board/documents/{document_id}/review", json={"review_status": "approved"})
    approved = reviewer.post(f"/api/board/applications/{application['id']}/approve", json={"send_payment_request": True})
    assert approved.json()["status"] == "approved"
    assert any("/pay" in body for _, body in sms_outbox())

    checkout = api.post(f"/api/applications/{application['id']}/checkout")
    assert checkout.status_code == 200
    session = next(iter(gateway.sessions.values()))
    assert post_webhook(api, completed_event(session)).json()["status"] == "processed"

    profile = api.get("/api/me").json()
    assert profile["membership_status"] == "member" and profile["renewal"]["is_current"] is True
    assert api.get(f"/api/applications/{application['id']}").json()["status"] == "completed"


def test_end_to_end_waiting_list(api, new_api, db, gateway):
    """Register -> waiting-list application -> documentation -> board review ->
    clearance -> eligibility -> payment -> membership activation."""
    member(api, "e2e-wait@example.com", **{**FULL_PROFILE, "nra_number": None})
    application = start(api, "waiting_list")
    api.patch(f"/api/applications/{application['id']}", json={"documentation_method": "background_check", "applicant_notes": "Referred by a member"})
    upload(api, application["id"], "nra_proof")
    upload(api, application["id"], "background_check")
    assert submit(api, application["id"]).json()["status"] == "submitted"
    assert api.get("/api/me").json()["membership_status"] == "waiting_list"

    reviewer = new_api()
    board(reviewer, db)
    for document in reviewer.get(f"/api/board/applications/{application['id']}").json()["documents"]:
        reviewer.post(f"/api/board/documents/{document['id']}/review", json={"review_status": "approved"})
    detail = reviewer.get(f"/api/board/applications/{application['id']}").json()
    assert detail["background_check_cleared"] is True and detail["nra_verified_at"]
    reviewer.post(f"/api/board/applications/{application['id']}/approve", json={})
    assert api.get(f"/api/applications/{application['id']}").json()["eligibility"]["eligible"] is True

    api.post(f"/api/applications/{application['id']}/checkout")
    session = next(iter(gateway.sessions.values()))
    post_webhook(api, completed_event(session))
    profile = api.get("/api/me").json()
    assert profile["membership_status"] == "member" and profile["member_since"] == date.today().isoformat()
