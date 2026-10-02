"""Email delivery behind a provider interface.

Business logic builds ``EmailMessage`` objects and calls ``get_email_provider()``;
nothing outside this module knows which vendor is in use. Resend is the
production provider (same vendor kiowa-gun used); "console" logs messages
and keeps them in memory for local development and tests.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import logging
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Protocol

import httpx

from app.core.config import get_settings
from app.services.html import html_to_text

logger = logging.getLogger("kiowa.email")


@dataclass
class EmailAttachment:
    filename: str
    content: bytes
    content_type: str


@dataclass
class EmailMessage:
    to: str
    subject: str
    html: str
    text: str | None = None
    attachments: list[EmailAttachment] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    tags: dict[str, str] = field(default_factory=dict)
    # Different sender identity (used for texts sent through carrier gateways).
    from_override: str | None = None


@dataclass
class SendResult:
    message_id: str | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class EmailProvider(Protocol):
    name: str

    def send(self, message: EmailMessage) -> SendResult: ...

    def send_batch(self, messages: list[EmailMessage]) -> list[SendResult]: ...


def _sender() -> str:
    settings = get_settings()
    return f"{settings.email_from_name} <{settings.email_from_address}>"


class ResendProvider:
    name = "resend"
    batch_size = 100  # Resend's per-request cap for /emails/batch

    def __init__(self, api_key: str) -> None:
        self._client = httpx.Client(
            base_url="https://api.resend.com",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(20.0),
        )

    def _payload(self, message: EmailMessage) -> dict[str, object]:
        settings = get_settings()
        payload: dict[str, object] = {
            "from": message.from_override or _sender(),
            "to": [message.to],
            "subject": message.subject,
            "text": message.text or html_to_text(message.html),
        }
        # Carrier email-to-SMS gateways relay plain text only.
        if message.html:
            payload["html"] = message.html
        if settings.email_reply_to:
            payload["reply_to"] = settings.email_reply_to
        if message.headers:
            payload["headers"] = message.headers
        if message.tags:
            payload["tags"] = [{"name": k, "value": v} for k, v in message.tags.items()]
        if message.attachments:
            payload["attachments"] = [
                {
                    "filename": a.filename,
                    "content": base64.b64encode(a.content).decode("ascii"),
                    "content_type": a.content_type,
                }
                for a in message.attachments
            ]
        return payload

    def send(self, message: EmailMessage) -> SendResult:
        try:
            response = self._client.post("/emails", json=self._payload(message))
        except httpx.HTTPError as exc:
            logger.warning("email_send_transport_error", extra={"error": str(exc)})
            return SendResult(None, f"Email provider unreachable: {exc}")
        if response.status_code >= 400:
            return SendResult(None, f"Email provider error {response.status_code}: {response.text[:300]}")
        return SendResult(response.json().get("id"))

    def send_batch(self, messages: list[EmailMessage]) -> list[SendResult]:
        # The batch endpoint doesn't support attachments; fall back to single sends.
        if any(m.attachments for m in messages):
            return [self.send(m) for m in messages]
        results: list[SendResult] = []
        for start in range(0, len(messages), self.batch_size):
            chunk = messages[start : start + self.batch_size]
            try:
                response = self._client.post("/emails/batch", json=[self._payload(m) for m in chunk])
            except httpx.HTTPError as exc:
                results.extend(SendResult(None, f"Email provider unreachable: {exc}") for _ in chunk)
                continue
            if response.status_code >= 400:
                error = f"Email provider error {response.status_code}: {response.text[:300]}"
                results.extend(SendResult(None, error) for _ in chunk)
                continue
            data = response.json().get("data", [])
            results.extend(SendResult(item.get("id")) for item in data)
            results.extend(SendResult(None, "Provider returned no message id") for _ in range(len(chunk) - len(data)))
        return results


class ConsoleProvider:
    """Development/test provider: logs each message and keeps it in ``outbox``."""

    name = "console"

    def __init__(self) -> None:
        self.outbox: list[EmailMessage] = []
        self._counter = 0

    def send(self, message: EmailMessage) -> SendResult:
        self._counter += 1
        self.outbox.append(message)
        # Development only (refused in production): print the text so links in
        # verification/reset emails can be followed locally.
        logger.info("email_console_send", extra={"to": message.to, "subject": message.subject,
                                                 "text": message.text or html_to_text(message.html)})
        return SendResult(f"console-{self._counter}")

    def send_batch(self, messages: list[EmailMessage]) -> list[SendResult]:
        return [self.send(m) for m in messages]


class DisabledProvider:
    name = "disabled"

    def send(self, message: EmailMessage) -> SendResult:
        return SendResult(None, "Email sending is not configured.")

    def send_batch(self, messages: list[EmailMessage]) -> list[SendResult]:
        return [self.send(m) for m in messages]


@lru_cache(maxsize=1)
def get_email_provider() -> EmailProvider:
    settings = get_settings()
    if settings.email_provider == "resend":
        if not settings.resend_api_key:
            logger.error("email_provider_misconfigured", extra={"detail": "RESEND_API_KEY missing"})
            return DisabledProvider()
        return ResendProvider(settings.resend_api_key)
    if settings.email_provider == "console":
        return ConsoleProvider()
    return DisabledProvider()


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_layout(body_html: str, *, footer_html: str = "") -> str:
    """Wraps (already sanitized) body HTML in a simple, email-client-safe layout
    using the club palette."""
    settings = get_settings()
    title = html.escape(settings.email_from_name)
    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#f2f0ea;font-family:Arial,Helvetica,sans-serif;color:#0d0f0a;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f2f0ea;padding:24px 0;">
<tr><td align="center">
<table role="presentation" width="600" cellspacing="0" cellpadding="0" style="max-width:600px;width:100%;background:#ffffff;border:1px solid #cbc6b8;">
<tr><td style="background:#17250f;color:#f2f0ea;padding:18px 24px;font-size:20px;font-weight:bold;">{title}</td></tr>
<tr><td style="padding:24px;font-size:16px;line-height:1.55;">{body_html}</td></tr>
<tr><td style="padding:16px 24px;border-top:1px solid #cbc6b8;font-size:12px;color:#4c5e3a;">{footer_html}</td></tr>
</table></td></tr></table></body></html>"""


def button(url: str, label: str) -> str:
    return (
        f'<p><a href="{html.escape(url, quote=True)}" style="display:inline-block;background:#a8291a;color:#ffffff;'
        f'padding:12px 20px;text-decoration:none;font-weight:bold;">{html.escape(label)}</a></p>'
    )


def send_transactional(to: str, subject: str, body_html: str) -> SendResult:
    """Account/payment/application notices. Not subject to newsletter opt-out."""
    message = EmailMessage(
        to=to,
        subject=subject,
        html=render_layout(body_html, footer_html="You received this message about your Kiowa Gun Club account."),
        tags={"category": "transactional"},
    )
    result = get_email_provider().send(message)
    if not result.ok:
        logger.error("transactional_email_failed", extra={"subject": subject, "error": result.error})
    return result


# ---------------------------------------------------------------------------
# Webhook verification (Resend signs webhooks with Svix)
# ---------------------------------------------------------------------------


def verify_svix_signature(secret: str, headers: dict[str, str], body: bytes, tolerance_seconds: int = 300) -> bool:
    msg_id = headers.get("svix-id")
    timestamp = headers.get("svix-timestamp")
    signatures = headers.get("svix-signature")
    if not (secret and msg_id and timestamp and signatures):
        return False
    try:
        if abs(time.time() - int(timestamp)) > tolerance_seconds:
            return False
        key = base64.b64decode(secret.removeprefix("whsec_"))
    except (ValueError, TypeError):
        return False
    signed = f"{msg_id}.{timestamp}.".encode() + body
    expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    for part in signatures.split():
        version, _, sig = part.partition(",")
        if version == "v1" and hmac.compare_digest(sig, expected):
            return True
    return False
