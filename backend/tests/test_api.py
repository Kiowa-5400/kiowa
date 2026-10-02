import os
import uuid
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

TEST_DB_PATH = Path(__file__).resolve().parent / 'test_kiowa.db'
if TEST_DB_PATH.exists():
    TEST_DB_PATH.unlink()
os.environ['DATABASE_URL'] = f'sqlite:///{TEST_DB_PATH}'
os.environ.setdefault('APP_SECRET', 'test-secret')
os.environ.setdefault('CORS_ORIGINS', 'http://localhost:5173')
os.environ.setdefault('STRIPE_WEBHOOK_SECRET', 'whsec_test_secret')
os.environ.setdefault('SMTP_HOST', 'smtp.example.com')
os.environ.setdefault('EMAIL_FROM', 'noreply@example.com')

from app.main import app
import app.services.communication as communication
import app.main as main_module

client = TestClient(app)


def _register(email: str, password: str = 'Password123!', role: str = 'visitor') -> dict:
    payload = {
        'first_name': 'Test',
        'last_name': 'User',
        'email': email,
        'password': password,
        'phone': '5551234567',
        'address': '123 Example St',
        'city': 'Great Bend',
        'state': 'KS',
        'zip_code': '67530',
        'role': role,
    }
    response = client.post('/api/auth/register', json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _login(email: str, password: str = 'Password123!') -> str:
    response = client.post('/api/auth/login', json={'email': email, 'password': password})
    assert response.status_code == 200, response.text
    return response.json()['token']


def test_health_check() -> None:
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json()['status'] == 'ok'


def test_application_form_includes_required_rules_and_document_logic() -> None:
    response = client.get('/api/application/form')
    assert response.status_code == 200
    payload = response.json()

    assert 'I have read, understand, and agree to follow the Kiowa Gun Club Range Rules.' in payload['rules_text']
    assert any(rule['label'] == 'NRA Membership Proof' for rule in payload['document_requirements']['renew_membership'])
    assert any(rule['label'] == 'Background Check OR Concealed Carry License' for rule in payload['document_requirements']['waiting_list'])


def test_register_login_and_auth_me() -> None:
    email = f'user-{uuid.uuid4().hex[:8]}@example.com'
    _register(email)
    token = _login(email)

    me = client.get('/api/auth/me', headers={'Authorization': f'Bearer {token}'})
    assert me.status_code == 200
    assert me.json()['email'] == email

    locked = client.get('/api/auth/me')
    assert locked.status_code == 401


def test_user_cannot_access_other_users_application_or_documents() -> None:
    user_a = f'userA-{uuid.uuid4().hex[:8]}@example.com'
    user_b = f'userB-{uuid.uuid4().hex[:8]}@example.com'

    _register(user_a)
    _register(user_b)
    token_a = _login(user_a)
    token_b = _login(user_b)

    app_payload = {
        'application_type': 'renew_membership',
        'signature': 'User B',
        'accept_rules': True,
        'notes': 'test',
        'payment_status': 'pending',
        'amount_due': 150.00,
        'rules_version': '2026-10-01',
        'rules_acknowledged': True,
    }
    created = client.post('/api/application/submit', json=app_payload, headers={'Authorization': f'Bearer {token_b}'})
    assert created.status_code == 200
    app_id = created.json()['application']['id']

    bad_app = client.get(f'/api/applications/{app_id}', headers={'Authorization': f'Bearer {token_a}'})
    assert bad_app.status_code == 403

    upload = client.post(
        '/api/documents/upload',
        files={'file': ('proof.pdf', b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF', 'application/pdf')},
        data={'application_id': str(app_id), 'document_type': 'NRA Membership Proof'},
        headers={'Authorization': f'Bearer {token_b}'},
    )
    assert upload.status_code == 200
    doc_id = upload.json()['document']['id']

    bad_doc = client.get(f'/api/documents/{doc_id}/download', headers={'Authorization': f'Bearer {token_a}'})
    assert bad_doc.status_code == 403


def test_board_routes_require_board_role() -> None:
    applicant = f'applicant-{uuid.uuid4().hex[:8]}@example.com'
    board = f'board-{uuid.uuid4().hex[:8]}@example.com'
    _register(applicant)
    _register(board, role='board')

    applicant_token = _login(applicant)
    board_token = _login(board)

    unauthorized = client.get('/api/board/applications', headers={'Authorization': f'Bearer {applicant_token}'})
    assert unauthorized.status_code == 403

    allowed = client.get('/api/board/applications', headers={'Authorization': f'Bearer {board_token}'})
    assert allowed.status_code == 200


def test_document_upload_requires_auth_and_valid_files() -> None:
    email = f'upload-{uuid.uuid4().hex[:8]}@example.com'
    _register(email)
    token = _login(email)

    submit = client.post(
        '/api/application/submit',
        json={
            'first_name': 'Upload',
            'last_name': 'Tester',
            'email': email,
            'phone': '5551234567',
            'address': '1 Main',
            'city': 'Great Bend',
            'state': 'KS',
            'zip_code': '67530',
            'application_type': 'renew_membership',
            'signature': 'Upload Tester',
            'accept_rules': True,
            'rules_version': '2026-10-01',
            'rules_acknowledged': True,
        },
        headers={'Authorization': f'Bearer {token}'},
    )
    assert submit.status_code == 200
    application_id = submit.json()['application']['id']

    good = client.post(
        '/api/documents/upload',
        files={'file': ('proof.pdf', b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF', 'application/pdf')},
        data={'application_id': str(application_id), 'document_type': 'NRA Membership Proof'},
        headers={'Authorization': f'Bearer {token}'},
    )
    assert good.status_code == 200

    bad_type = client.post(
        '/api/documents/upload',
        files={'file': ('bad.txt', b'not a pdf', 'text/plain')},
        data={'application_id': str(application_id), 'document_type': 'NRA Membership Proof'},
        headers={'Authorization': f'Bearer {token}'},
    )
    assert bad_type.status_code == 400


def test_checkout_and_webhook_are_verified_and_idempotent() -> None:
    email = f'pay-{uuid.uuid4().hex[:8]}@example.com'
    _register(email)
    token = _login(email)
    app_response = client.post(
        '/api/application/submit',
        json={
            'first_name': 'Pay',
            'last_name': 'Tester',
            'email': email,
            'phone': '5551234567',
            'address': '1 Main',
            'city': 'Great Bend',
            'state': 'KS',
            'zip_code': '67530',
            'application_type': 'renew_membership',
            'signature': 'Pay Tester',
            'accept_rules': True,
            'rules_version': '2026-10-01',
            'rules_acknowledged': True,
        },
        headers={'Authorization': f'Bearer {token}'},
    )
    app_id = app_response.json()['application']['id']

    checkout = client.post('/api/payments/checkout', json={'application_id': app_id}, headers={'Authorization': f'Bearer {token}'})
    assert checkout.status_code == 200
    payload = checkout.json()
    assert payload['application_id'] == app_id
    assert payload['expected_amount'] == 150.0

    event = {
        'id': 'evt_test_123',
        'type': 'checkout.session.completed',
        'data': {'object': {'id': 'cs_test_123', 'amount_total': 15000, 'currency': 'usd', 'metadata': {'application_id': str(app_id), 'person_id': '1'}}},
    }
    body = b'{"id":"evt_test_123","type":"checkout.session.completed","data":{"object":{"id":"cs_test_123","amount_total":15000,"currency":"usd","metadata":{"application_id":"' + str(app_id).encode() + b'","person_id":"1"}}}}'
    signed = httpx.Client().build_request('POST', 'http://localhost', content=body).headers
    sig = 't=' + str(int(__import__('time').time())) + ',v1=' + __import__('hashlib').sha256(b'whsec_test_secret' + b'evt_test_123').hexdigest()

    webhook = client.post(
        '/api/payments/webhook',
        content=body,
        headers={'Stripe-Signature': sig, 'Content-Type': 'application/json'},
    )
    assert webhook.status_code == 200
    assert webhook.json()['status'] == 'succeeded'

    replay = client.post(
        '/api/payments/webhook',
        content=body,
        headers={'Stripe-Signature': sig, 'Content-Type': 'application/json'},
    )
    assert replay.status_code == 200
    assert replay.json()['status'] == 'duplicate'

def test_application_submission_sends_notification(monkeypatch) -> None:
    email = f'notify-{uuid.uuid4().hex[:8]}@example.com'
    _register(email)
    token = _login(email)
    sent = []
    monkeypatch.setattr(main_module, 'send_application_notification', lambda **kwargs: sent.append(kwargs) or 'email')
    response = client.post(
        '/api/application/submit',
        json={
            'phone': '5551234567', 'address': '1 Main', 'city': 'Great Bend',
            'state': 'KS', 'zip_code': '67530', 'application_type': 'renew_membership',
            'signature': 'Notify Tester', 'accept_rules': True, 'rules_acknowledged': True,
        },
        headers={'Authorization': f'Bearer {token}'},
    )
    assert response.status_code == 200
    assert sent and sent[0]['email'] == email
    assert sent[0]['phone'] == '5551234567'
def test_notification_falls_back_to_email_when_sms_lookup_or_gateway_fails(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(communication, '_verify_phone_with_veriphone', lambda phone: (_ for _ in ()).throw(RuntimeError('lookup unavailable')))
    monkeypatch.setattr(communication, '_send_email', lambda recipient, subject, body: calls.append(recipient))
    result = communication.send_application_notification(
        email='member@example.com', applicant_name='Test Member', phone='5551234567', message='Test notification'
    )
    assert result == 'email'
    assert calls == ['member@example.com']