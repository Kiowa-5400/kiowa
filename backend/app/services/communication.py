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
        str(key).strip().lower(): str(domain).strip()
        for key, domain in value.items()
        if str(key).strip() and str(domain).strip()
    }


def _carrier_gateway(carrier: str | None) -> str | None:
    if not carrier:
        return None

    carrier_key = carrier.strip().lower()
    mappings = _gateway_map()

    # Prefer the longest configured key so entries such as "consumer cellular"
    # win over broad carrier-name fragments.
    for key in sorted(mappings, key=len, reverse=True):
        if key in carrier_key:
            return mappings[key]
    return None


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
        raise RuntimeError(str(payload.get("message") or "Veriphone rejected the phone lookup."))
    if not payload.get("phone_valid"):
        raise RuntimeError(str(payload.get("reason") or "Phone number is not valid."))
    return payload


def _send_email(
    recipient: str,
    subject: str,
    body: str,
) -> None:
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


def _send_sms_gateway(
    phone_digits: str,
    gateway_domain: str,
    subject: str,
    body: str,
) -> None:
    settings = get_settings()
    gateway_address = gateway_domain.format(number=phone_digits, phone=phone_digits)

    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = gateway_address
    message["Subject"] = subject
    message.set_content(body)

    if not settings.smtp_host or not settings.email_from:
        raise RuntimeError("SMTP_HOST and EMAIL_FROM must be configured.")

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


def send_application_notification(
    email: str,
    applicant_name: str,
    phone: str | None = None,
    message: str | None = None,
) -> str:
    """Notify an applicant by carrier email-to-SMS when possible, else email.

    Veriphone is queried for the currently serving carrier. The gateway is
    selected only from the deployment's explicit SMS_GATEWAY_MAP. Any missing
    gateway, Veriphone failure, or SMTP gateway failure falls back to the
    applicant's normal email address.

    Note: SMTP success means the gateway accepted the email; it does not prove
    downstream SMS delivery. Carrier gateways can silently filter or retire.
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

    phone_digits = _digits_only(phone)
    if phone.strip().startswith("+"):\n        lookup_phone = phone\n    elif len(phone_digits) == 11 and phone_digits.startswith("1"):\n        lookup_phone = f"+{phone_digits}"\n    elif len(phone_digits) == 10:\n        lookup_phone = f"+1{phone_digits}"\n    else:\n        lookup_phone = phone

    try:
        verification = _verify_phone_with_veriphone(lookup_phone)
        carrier = str(verification.get("current_carrier") or verification.get("carrier") or "").strip()
        country_code = str(verification.get("country_code") or "").upper()
        line_type = str(verification.get("current_line_type") or verification.get("phone_type") or "").lower()
        gateway_domain = _carrier_gateway(carrier)

        if country_code == "US" and line_type in {"mobile", "fixed_line_or_mobile"} and gateway_domain:
            if len(phone_digits) == 11 and phone_digits.startswith("1"):
                phone_digits = phone_digits[1:]
            if len(phone_digits) == 10:
                gateway_address = gateway_domain.format(number=phone_digits, phone=phone_digits)
                _send_sms_gateway(phone_digits, gateway_domain, subject, body)
                logger.info(
                    "application_notification_sms_sent",
                    extra={"carrier": carrier, "gateway": gateway_address},
                )
                return "sms"

        reason = (
            f"No configured email-to-SMS gateway for carrier '{carrier}', "
            f"country '{country_code}', or unsupported line type '{line_type}'."
        )
        logger.info("application_notification_sms_unavailable", extra={"reason": reason})
    except Exception as exc:
        logger.warning("application_notification_sms_failed", extra={"error": str(exc)})

    try:
        _send_email(email, subject, body)
        logger.info("application_notification_email_sent", extra={"email": email})
        return "email"
    except Exception:
        logger.exception("application_notification_email_failed", extra={"email": email})
        return "failed"
