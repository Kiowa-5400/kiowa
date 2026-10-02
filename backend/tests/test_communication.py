import app.services.communication as communication


def test_notification_uses_veriphone_current_carrier_to_select_gateway(monkeypatch):
    sent = {}

    monkeypatch.setattr(
        communication,
        "_verify_phone_with_veriphone",
        lambda phone: {
            "status": "success",
            "phone_valid": True,
            "current_carrier": "T-Mobile USA",
            "country_code": "US",
            "current_line_type": "mobile",
        },
    )
    monkeypatch.setattr(
        communication,
        "_gateway_map",
        lambda: {"t-mobile": "tmomail.net"},
    )
    monkeypatch.setattr(
        communication,
        "_send_sms_gateway",
        lambda phone_digits, gateway, subject, body: sent.update(
            phone=phone_digits, gateway=gateway
        ) or f"{phone_digits}@{gateway}",
    )
    monkeypatch.setattr(
        communication,
        "_send_email",
        lambda *args: (_ for _ in ()).throw(AssertionError("email fallback should not run")),
    )

    result = communication.send_application_notification(
        email="member@example.com",
        applicant_name="Test Member",
        phone="(555) 123-4567",
        message="Test notification",
    )

    assert result == "sms"
    assert sent == {"phone": "5551234567", "gateway": "tmomail.net"}


def test_notification_falls_back_to_email_when_veriphone_fails(monkeypatch):
    calls = []

    monkeypatch.setattr(
        communication,
        "_verify_phone_with_veriphone",
        lambda phone: (_ for _ in ()).throw(RuntimeError("lookup unavailable")),
    )
    monkeypatch.setattr(
        communication,
        "_send_email",
        lambda recipient, subject, body: calls.append(recipient),
    )

    result = communication.send_application_notification(
        email="member@example.com",
        applicant_name="Test Member",
        phone="5551234567",
        message="Test notification",
    )

    assert result == "email"
    assert calls == ["member@example.com"]


def test_notification_falls_back_to_email_when_gateway_send_fails(monkeypatch):
    calls = []

    monkeypatch.setattr(
        communication,
        "_verify_phone_with_veriphone",
        lambda phone: {
            "status": "success",
            "phone_valid": True,
            "current_carrier": "T-Mobile USA",
            "country_code": "US",
            "current_line_type": "mobile",
        },
    )
    monkeypatch.setattr(
        communication,
        "_gateway_map",
        lambda: {"t-mobile": "tmomail.net"},
    )
    monkeypatch.setattr(
        communication,
        "_send_sms_gateway",
        lambda *args: (_ for _ in ()).throw(RuntimeError("gateway unavailable")),
    )
    monkeypatch.setattr(
        communication,
        "_send_email",
        lambda recipient, subject, body: calls.append(recipient),
    )

    result = communication.send_application_notification(
        email="member@example.com",
        applicant_name="Test Member",
        phone="5551234567",
        message="Test notification",
    )

    assert result == "email"
    assert calls == ["member@example.com"]


def test_notification_falls_back_to_email_for_unsupported_carrier(monkeypatch):
    calls = []

    monkeypatch.setattr(
        communication,
        "_verify_phone_with_veriphone",
        lambda phone: {
            "status": "success",
            "phone_valid": True,
            "current_carrier": "Unknown Mobile Carrier",
            "country_code": "US",
            "current_line_type": "mobile",
        },
    )
    monkeypatch.setattr(communication, "_gateway_map", lambda: {})
    monkeypatch.setattr(
        communication,
        "_send_email",
        lambda recipient, subject, body: calls.append(recipient),
    )

    result = communication.send_application_notification(
        email="member@example.com",
        applicant_name="Test Member",
        phone="5551234567",
        message="Test notification",
    )

    assert result == "email"
    assert calls == ["member@example.com"]
