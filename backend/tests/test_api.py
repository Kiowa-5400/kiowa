from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


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


def test_submit_application_persists_and_returns_record() -> None:
    payload = {
        'first_name': 'Ada',
        'last_name': 'Lovelace',
        'email': 'ada@example.com',
        'phone': '5551234567',
        'address': '123 Main St',
        'city': 'Great Bend',
        'state': 'KS',
        'zip': '67530',
        'application_type': 'waiting_list',
        'signature': 'Ada Lovelace',
        'accept_rules': True,
        'documents': {'Background Check OR Concealed Carry License': 'license.jpg'},
    }

    response = client.post('/api/application/submit', json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body['message'].startswith('Thank you, Ada Lovelace.')
    assert body['application']['status'] == 'submitted'
    assert body['application']['person']['first_name'] == 'Ada'


def test_board_dashboard_returns_summary() -> None:
    response = client.get('/api/board/dashboard')
    assert response.status_code == 200
    body = response.json()
    assert body['summary']['pending'] >= 0
    assert 'recent_applications' in body
