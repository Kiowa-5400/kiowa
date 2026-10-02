from __future__ import annotations

import json
import logging
import re
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger("kiowa.communication")


@dataclass(frozen=True)
class NotificationResult:
    channel: str
    delivered: bool
    fallback_used: bool
    carrier: str | None = None
    gateway: str | None = None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "delivered": self.delivered,
            "fallback_used": self.fallback_used,
            "carrier": self.carrier,
            "gateway": self.gateway,
            "reason": self.reason,
        }


def _digits_only(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def _to_e164(phone: str) -> str | None:
    raw = (phone or "").strip()
    digits = _digits_only(raw)

    if raw.startswith("+") and len(digits) >= 8:
        return f"+{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if len(digits) == 10:
        return f"+1{digits}"
    return None


def _gateway_map() -> dict[str, str]:
    settings = get_settings()
    try:
        value = json.loads(settings.sms_gateway_map or "{}")
    except json.JSONDecodeError:
        logger.error("invalid_sms_gateway_map")
        return {}

    if not isinstance(value, dict):
        return {}

    return {
        str(key).strip().lower(): str(value).strip()
        for key, value in value.items()
        if str(key).strip() and str(value).strip()
    }


def _carrier_gateway(carrier: str | None) -> str | None:
    """Resolve a Veriphone carrier name to the configured SMS gateway.

    Veriphone returns carrier names as free text, so mappings are matched by
    longest substring first. Gateway values may be either a domain
    (example.com) or a template containing {number}/{phone}.
    """
    if not carrier:
        return None

    carrier_key = carrier.strip().lower()
    mappings = _gateway_map()

    for key in sorted(mappings, key=len, reverse=True):
        if key in carrier_key:
            return mappings[key]
    return None


def _gateway_address(phone_digits: str, gateway: str) -> str:
    if "@" in gateway:
        return gateway.format(number=phone_digits, phone=phone_digits)
    return f"{phone_digits}@{gateway.format(number=phone_digits, phone=phone_digits)}"


def _verify_phone_with_veriphone(phone: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.veriphone_api_key:
        raise RuntimeError("VERIPHONE_API_KEY is not configured.")

    response = httpx.get(
        settings.veriphone_api_url,
        params={
            "phone": phone,
            "mode": "current",
            "default_country": settings.veriphone_default_country,
        },
        headers={"Authorization": f"Bearer {settings.veriphone_api_key}"},
        timeout=settings.veriphone_timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()

    if payload.get("status") != "success":
        raise RuntimeError(
            str(payload.get("message") or payload.get("error") or "Veriphone rejected the phone lookup.")
        )
    if not payload.get("phone_valid"):
        raise RuntimeError(str(payload.get("reason") or "Phone number is not valid."))

    return payload


def _send_email(recipient: str, subject: str, body: str) -> None:
    settings = get_settings()
    if not settings.smtp_host or not settings.email_from:
        raise RuntimeError("SMTP_HOST and EMAIL_FROM must be configured.")

    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(
        settings.smtp_host,
        settings.smtp_port,
        timeout=settings.smtp_timeout_seconds,
    ) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password or "")
        smtp.send_message(message)


def _send_sms_gateway(phone_digits: str, gateway: str, subject: str, body: str) -> str:
    settings = get_settings()
    if not settings.smtp_host or not settings.email_from:
        raise RuntimeError("SMTP_HOST and EMAIL_FROM must be configured.")

    gateway_address = _gateway_address(phone_digits, gateway)

    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = gateway_address
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(
        settings.smtp_host,
        settings.smtp_port,
        timeout=settings.smtp_timeout_seconds,
    ) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password or "")
        smtp.send_message(message)

    return gateway_address


def send_application_notification(
    email: str,
    applicant_name: str,
    phone: str | None = None,
    message: str | None = None,
) -> str:
    """Send an application notification by SMS gateway, falling back to email.

    The routing sequence intentionally mirrors the legacy kiowa-gun behavior:

    1. When the applicant clicks Send/Submit, normalize the phone number.
    2. Ask Veriphone for the CURRENT serving carrier.
    3. Use that carrier result to select the configured email-to-SMS gateway.
    4. Send the notification through SMTP to the carrier gateway.
    5. If validation, carrier routing, gateway delivery, or SMS SMTP fails,
       send the same notification to the applicant's email address.

    Veriphone Current mode is used because a number can be ported while keeping
    the same phone number. The current carrier is therefore the useful routing
    result, not only the originally assigned carrier.

    SMTP success means the gateway accepted the email; it does not guarantee
    that the downstream carrier ultimately delivered an SMS.
    """
    settings = get_settings()
    subject = settings.notification_subject
    body = message or (
        f"Hello {applicant_name},\n\n"
        "Your Kiowa Gun Club application has been received and is pending review.\n\n"
        "Thank you,\nKiowa Gun Club"
    )

    if not phone:
        try:
            _send_email(email, subject, body)
            return "email"
        except Exception:
            logger.exception("application_notification_email_failed", extra={"email": email})
            return "failed"

    e164 = _to_e164(phone)
    if not e164:
        logger.info("application_notification_invalid_phone", extra={"phone_length": len(_digits_only(phone))})
        try:
            _send_email(email, subject, body)
            return "email"
        except Exception:
            logger.exception("application_notification_email_failed", extra={"email": email})
            return "failed"

    try:
        verification = _verify_phone_with_veriphone(e164)

        carrier = str(
            verification.get("current_carrier")
            or verification.get("carrier")
            or ""
        ).strip()
        country_code = str(verification.get("country_code") or "").upper()
        line_type = str(
            verification.get("current_line_type")
            or verification.get("phone_type")
            or ""
        ).lower()

        gateway = _carrier_gateway(carrier)

        if (
            country_code == "US"
            and line_type in {"mobile", "fixed_line_or_mobile"}
            and gateway
        ):
            phone_digits = _digits_only(e164)
            gateway_address = _send_sms_gateway(phone_digits[1:] if phone_digits.startswith("1") else phone_digits, gateway, subject, body)
            logger.info(
                "application_notification_sms_sent",
                extra={
                    "carrier": carrier,
                    "line_type": line_type,
                    "gateway": gateway_address,
                    "ported": verification.get("ported"),
                },
            )
            return "sms"

        reason = (
            f"SMS unavailable for carrier '{carrier}', country '{country_code}', "
            f"line type '{line_type}', gateway '{gateway}'."
        )
        logger.info("application_notification_sms_unavailable", extra={"reason": reason})
    except Exception as exc:
        logger.warning(
            "application_notification_sms_failed",
            extra={"error": str(exc)},
        )

    try:
        _send_email(email, subject, body)
        logger.info("application_notification_email_sent", extra={"email": email})
        return "email"
    except Exception:
        logger.exception("application_notification_email_failed", extra={"email": email})
        return "failed"
