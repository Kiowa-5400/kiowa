"""Authentication, sessions, CSRF, lockout, password reset, email verification, roles."""

from __future__ import annotations

from sqlalchemy import select

from app.models import AuditLog, Person
from tests.conftest import email_outbox, last_token
from tests.helpers import PASSWORD, board, board_sign_in, create_board_user, register_and_verify, sign_in


def test_health_and_readiness(api):
    assert api.get("/health").json() == {"status": "ok"}
    ready = api.get("/health/ready").json()
    assert ready["status"] == "ok" and ready["migration"] == "0004"


def test_security_headers_and_request_id(api):
    response = api.get("/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Request-ID"]


def test_oversized_request_rejected_before_reading(api):
    response = api.client.post("/api/auth/login", content=b"{}", headers={"content-length": str(200 * 1024 * 1024), "content-type": "application/json"})
    assert response.status_code == 413


def test_cors_allows_only_configured_origins(api):
    allowed = api.client.options("/api/auth/session", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    blocked = api.client.options("/api/auth/session", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in blocked.headers


def test_registration_requires_email_verification(api):
    response = api.post("/api/auth/register", json={"first_name": "Pat", "last_name": "Shooter", "email": "Pat@Example.com", "password": PASSWORD})
    assert response.status_code == 202
    blocked = api.post("/api/auth/login", json={"email": "pat@example.com", "password": PASSWORD})
    assert blocked.status_code == 403 and "verify" in blocked.json()["detail"].lower()
    token = last_token("pat@example.com", "/verify-email")
    assert api.post("/api/auth/email/verify", json={"token": token}).status_code == 200
    # One-time: the same link can't be reused.
    assert api.post("/api/auth/email/verify", json={"token": token}).status_code == 400
    session = sign_in(api, "pat@example.com")
    assert session["profile"]["email"] == "pat@example.com"
    assert session["profile"]["membership_status"] == "non_member"


def test_registration_does_not_reveal_existing_accounts(api, db):
    register_and_verify(api, "taken@example.com")
    response = api.post("/api/auth/register", json={"first_name": "X", "last_name": "Y", "email": "taken@example.com", "password": "another-password-1"})
    assert response.status_code == 202
    # The existing password still works; the inbox owner got a reset link instead.
    sign_in(api, "taken@example.com")
    assert last_token("taken@example.com", "/reset-password")


def test_existing_contact_claims_record_by_email_link(api, db):
    db.add(Person(first_name="Old", last_name="Member", email="old@example.com", membership_status="member"))
    db.commit()
    api.post("/api/auth/register", json={"first_name": "Old", "last_name": "Member", "email": "old@example.com", "password": PASSWORD})
    token = last_token("old@example.com", "/reset-password")
    assert api.post("/api/auth/password/reset", json={"token": token, "password": "New-Password-123"}).status_code == 200
    session = sign_in(api, "old@example.com", "New-Password-123")
    assert session["profile"]["membership_status"] == "member"


def test_weak_password_rejected(api):
    response = api.post("/api/auth/register", json={"first_name": "A", "last_name": "B", "email": "a@example.com", "password": "short"})
    assert response.status_code == 422
    assert "password" in response.json()["errors"]


def test_session_cookie_is_httponly_and_logout_invalidates(api):
    register_and_verify(api, "cookie@example.com")
    response = api.post("/api/auth/login", json={"email": "cookie@example.com", "password": PASSWORD})
    cookie = response.headers["set-cookie"]
    assert "kgc_member_session=" in cookie and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
    stolen = api.client.cookies.get("kgc_member_session")
    assert api.get("/api/auth/session").status_code == 200
    assert api.post("/api/auth/logout").status_code == 200
    assert api.get("/api/auth/session").status_code == 401
    # The old cookie value is dead server-side, not just deleted in the browser.
    api.client.cookies.set("kgc_member_session", stolen)
    assert api.get("/api/auth/session").status_code == 401


def test_csrf_header_required_for_state_changes(api):
    register_and_verify(api, "csrf@example.com")
    sign_in(api, "csrf@example.com")
    good_csrf = api.csrf
    api.csrf = None
    assert api.patch("/api/me", json={"city": "Hoisington"}).status_code == 403
    assert api.patch("/api/me", json={"city": "Hoisington"}, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    api.csrf = good_csrf
    assert api.patch("/api/me", json={"city": "Hoisington"}).json()["city"] == "Hoisington"


def test_lockout_after_repeated_failures(api, db):
    register_and_verify(api, "lock@example.com")
    for _ in range(8):
        assert api.post("/api/auth/login", json={"email": "lock@example.com", "password": "wrong-password"}).status_code == 401
    locked = api.post("/api/auth/login", json={"email": "lock@example.com", "password": PASSWORD})
    assert locked.status_code == 429
    person = db.scalar(select(Person).where(Person.email == "lock@example.com"))
    assert person.locked_until is not None


def test_login_rate_limit_per_ip(api):
    for _ in range(10):
        api.post("/api/auth/login", json={"email": "nobody@example.com", "password": "whatever-123"})
    assert api.post("/api/auth/login", json={"email": "nobody@example.com", "password": "whatever-123"}).status_code == 429


def test_password_reset_flow_revokes_sessions(api, new_api):
    register_and_verify(api, "reset@example.com")
    sign_in(api, "reset@example.com")
    other = new_api()
    other.post("/api/auth/password/forgot", json={"email": "reset@example.com"})
    token = last_token("reset@example.com", "/reset-password")
    assert other.post("/api/auth/password/reset", json={"token": token, "password": "Brand-New-Pass-1"}).status_code == 200
    assert api.get("/api/auth/session").status_code == 401
    assert other.post("/api/auth/password/reset", json={"token": token, "password": "Another-Pass-12"}).status_code == 400
    sign_in(other, "reset@example.com", "Brand-New-Pass-1")


def test_forgot_password_is_generic_for_unknown_email(api):
    response = api.post("/api/auth/password/forgot", json={"email": "ghost@example.com"})
    assert response.status_code == 200
    assert not [m for m in email_outbox() if m.to == "ghost@example.com"]


def test_change_password_keeps_current_session(api):
    register_and_verify(api, "change@example.com")
    sign_in(api, "change@example.com")
    bad = api.post("/api/auth/password/change", json={"current_password": "nope-nope-nope", "new_password": "Whatever-12345"})
    assert bad.status_code == 400
    ok = api.post("/api/auth/password/change", json={"current_password": PASSWORD, "new_password": "Whatever-12345"})
    assert ok.status_code == 200
    assert api.get("/api/auth/session").status_code == 200


def test_member_cannot_use_board_realm(api, new_api):
    register_and_verify(api, "plain@example.com")
    board_client = new_api()
    assert board_client.post("/api/board/auth/login", json={"email": "plain@example.com", "password": PASSWORD}).status_code == 401
    sign_in(api, "plain@example.com")
    # A member session cookie does not authenticate board routes.
    assert api.get("/api/board/dashboard").status_code == 401


def test_board_login_and_permissions_by_role(api, new_api, db):
    session = board(api, db, "treasurer@example.com", "treasurer")
    assert session["role"] == "treasurer" and "payments.view" in session["permissions"]
    assert "board.manage" not in session["permissions"]
    assert api.get("/api/board/payments").status_code == 200
    assert api.get("/api/board/users").status_code == 403

    member_board = new_api()
    board(member_board, db, "bm@example.com", "board_member")
    assert member_board.get("/api/board/payments").status_code == 403
    assert member_board.get("/api/board/exports/contacts.csv").status_code == 403
    assert member_board.get("/api/board/audit").status_code == 403
    assert member_board.get("/api/board/applications").status_code == 200

    assert db.scalar(select(AuditLog).where(AuditLog.action == "board.signed_in")) is not None


def test_board_invite_accept_and_deactivate(api, new_api, db):
    board(api, db)
    invite = api.post("/api/board/users", json={"first_name": "Vera", "last_name": "Vice", "email": "vp@example.com", "role": "vice_president", "position": "Vice President"})
    assert invite.status_code == 201, invite.text
    token = last_token("vp@example.com", "/accept-invite")
    vp = new_api()
    assert vp.post("/api/board/auth/password/reset", json={"token": token, "password": "Vice-Pres-Pass-1"}).status_code == 200
    assert board_sign_in(vp, "vp@example.com", "Vice-Pres-Pass-1")["role"] == "vice_president"
    # The invited board member is also on the contact list as a member.
    assert db.scalar(select(Person).where(Person.email == "vp@example.com")).on_board

    board_user_id = invite.json()["id"]
    assert api.patch(f"/api/board/users/{board_user_id}", json={"is_active": False}).status_code == 200
    assert vp.get("/api/board/dashboard").status_code == 401


def test_board_role_hierarchy(api, db):
    board(api, db, "pres@example.com", "president")
    tech = create_board_user(db, "tech@example.com", "tech_admin")
    response = api.post("/api/board/users", json={"first_name": "T", "last_name": "A", "email": "t2@example.com", "role": "tech_admin"})
    assert response.status_code == 403
    assert api.patch(f"/api/board/users/{tech.board_user.id}", json={"role": "board_member"}).status_code == 403


def test_last_president_cannot_be_removed(api, db):
    board(api, db, "only-pres@example.com", "president")
    me = api.get("/api/board/users").json()[0]
    response = api.patch(f"/api/board/users/{me['id']}", json={"role": "board_member"})
    assert response.status_code == 409
