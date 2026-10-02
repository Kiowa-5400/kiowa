"""Shared test helpers: account setup, sample files, Stripe test doubles."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.core.timeutil import now_utc
from app.models import BoardUser, Person
from app.services import payments as payment_service
from tests.conftest import Api, last_token

PASSWORD = "Correct-Horse-9"
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def register_and_verify(api: Api, email: str, first: str = "Pat", last: str = "Shooter") -> None:
    response = api.post("/api/auth/register", json={"first_name": first, "last_name": last, "email": email, "password": PASSWORD})
    assert response.status_code == 202, response.text
    token = last_token(email, "/verify-email")
    assert api.post("/api/auth/email/verify", json={"token": token}).status_code == 200


def sign_in(api: Api, email: str, password: str = PASSWORD) -> dict[str, Any]:
    response = api.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def member(api: Api, email: str, **profile: Any) -> dict[str, Any]:
    register_and_verify(api, email)
    session = sign_in(api, email)
    if profile:
        assert api.patch("/api/me", json=profile).status_code == 200
    return session


FULL_PROFILE = {
    "phone": "620-555-0100",
    "address_line1": "123 Range Rd",
    "city": "Great Bend",
    "state": "KS",
    "zip_code": "67530",
    "nra_number": "123456789",
    "nra_expiration_date": (date.today() + timedelta(days=400)).isoformat(),
}


def create_board_user(db: Session, email: str, role: str = "president", password: str = PASSWORD) -> Person:
    person = Person(first_name="Board", last_name=role.title(), email=email, membership_status="member",
                    password_hash=hash_password(password), email_verified_at=now_utc(), on_board=True)
    db.add(person)
    db.flush()
    db.add(BoardUser(person_id=person.id, role=role))
    db.commit()
    return person


def board_sign_in(api: Api, email: str, password: str = PASSWORD) -> dict[str, Any]:
    response = api.post("/api/board/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def board(api: Api, db: Session, email: str = "president@example.com", role: str = "president") -> dict[str, Any]:
    create_board_user(db, email, role)
    return board_sign_in(api, email)


def upload(api: Api, application_id: int, document_type: str, content: bytes = PDF, filename: str = "proof.pdf",
           mime: str = "application/pdf"):  # noqa: ANN201
    return api.post(
        f"/api/applications/{application_id}/documents",
        data={"document_type": document_type},
        files={"file": (filename, content, mime)},
    )


def submit(api: Api, application_id: int, name: str = "Pat Shooter"):  # noqa: ANN201
    rules = api.get("/api/application/form").json()["rules"]
    return api.post(
        f"/api/applications/{application_id}/submit",
        json={"rules_version": rules["version"], "accept_rules": True, "printed_name": name, "signature_name": name},
    )


class FakeGateway(payment_service.StripeGateway):
    """Real webhook signature verification; no network calls."""

    def __init__(self) -> None:
        super().__init__()
        self.sessions: dict[str, dict[str, Any]] = {}
        self.refunds: list[tuple[str, int]] = []

    def create_checkout_session(self, params: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        session_id = f"cs_test_{len(self.sessions) + 1}"
        session = {"id": session_id, "url": f"https://checkout.stripe.com/c/pay/{session_id}", "params": params,
                   "amount_total": params["line_items"][0]["price_data"]["unit_amount"], "currency": "usd",
                   "metadata": params["metadata"], "payment_status": "unpaid", "status": "open"}
        self.sessions[session_id] = session
        return session

    def retrieve_checkout_session(self, session_id: str) -> dict[str, Any]:
        return self.sessions[session_id]

    def create_refund(self, payment_intent_id: str, amount_cents: int, idempotency_key: str) -> dict[str, Any]:
        self.refunds.append((payment_intent_id, amount_cents))
        return {"id": "re_test", "status": "succeeded"}


def stripe_signature(payload: bytes, secret: str = "whsec_unit_tests_only", timestamp: int | None = None) -> str:
    timestamp = timestamp or int(time.time())
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def completed_event(session: dict[str, Any], event_id: str = "evt_test_1", **overrides: Any) -> bytes:
    obj = {"id": session["id"], "object": "checkout.session", "payment_status": "paid", "status": "complete",
           "amount_total": session["amount_total"], "currency": "usd", "metadata": session["metadata"],
           "payment_intent": "pi_test_123"}
    obj.update(overrides)
    return json.dumps({"id": event_id, "type": "checkout.session.completed", "data": {"object": obj}}).encode()


def post_webhook(api: Api, payload: bytes, signature: str | None = None):  # noqa: ANN201
    return api.client.post("/api/webhooks/stripe", content=payload,
                           headers={"Stripe-Signature": signature or stripe_signature(payload), "Content-Type": "application/json"})


def start(api: Api, kind: str = "renewal") -> dict[str, Any]:
    response = api.post("/api/applications", json={"application_type": kind})
    assert response.status_code == 201, response.text
    return response.json()
