"""Email delivery behind a provider interface.

Business logic builds ``EmailMessage`` objects and calls ``get_email_provider()``;
nothing outside this module knows which vendor is in use. SMTP is the
production provider using the club mailbox; "console" logs messages
and keeps them in memory for local development and tests.
"""

from __future__ import annotations

import base64
import html
import logging
import smtplib
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


class SmtpProvider:
    """SMTP provider using the club's own mailbox credentials."""

    name = "smtp"

    def _message(self, message: EmailMessage):
        from email.message import EmailMessage as MimeEmailMessage
        settings = get_settings()
        msg = MimeEmailMessage()
        msg["From"] = message.from_override or _sender()
        msg["To"] = message.to
        msg["Subject"] = message.subject
        if settings.email_reply_to:
            msg["Reply-To"] = settings.email_reply_to
        for key, value in message.headers.items():
            msg[key] = value
        text = message.text or html_to_text(message.html)
        if message.html:
            msg.set_content(text)
            msg.add_alternative(message.html, subtype="html")
        else:
            msg.set_content(text)
        for attachment in message.attachments:
            maintype, subtype = attachment.content_type.split("/", 1)
            msg.add_attachment(attachment.content, maintype=maintype, subtype=subtype, filename=attachment.filename)
        return msg

    def send(self, message: EmailMessage) -> SendResult:
        settings = get_settings()
        try:
            mime = self._message(message)
            if settings.smtp_use_ssl:
                with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20) as server:
                    server.login(settings.smtp_username, settings.smtp_password)
                    server.send_message(mime)
            else:
                with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
                    if settings.smtp_use_tls:
                        server.starttls()
                    server.login(settings.smtp_username, settings.smtp_password)
                    server.send_message(mime)
        except (OSError, smtplib.SMTPException) as exc:
            logger.warning("smtp_send_failed", extra={"to": message.to, "error": str(exc)})
            return SendResult(None, f"SMTP delivery failed: {exc}")
        return SendResult(mime.get("Message-ID"))

    def send_batch(self, messages: list[EmailMessage]) -> list[SendResult]:
        return [self.send(message) for message in messages]


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
    if settings.email_provider == "smtp":
        if not (settings.smtp_host and settings.smtp_username and settings.smtp_password):
            logger.error("email_provider_misconfigured", extra={"detail": "SMTP_HOST/SMTP_USERNAME/SMTP_PASSWORD missing"})
            return DisabledProvider()
        return SmtpProvider()
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


