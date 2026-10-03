"""Text messages through each carrier's email-to-SMS gateway, plus consent enforcement.

Ported from kiowa-gun (lib/sms.ts, lib/veriphone.ts): the member's carrier is
looked up once with Veriphone (https://veriphone.io) and cached on their
record, then the text is emailed as plain text to
<10-digit number>@<carrier gateway domain> through the email provider
(Resend). This avoids A2P 10DLC registration, at the cost of no delivery
receipts and no picture messages.

The carrier lookup and gateway transport sit behind ``SmsProvider`` so a
dedicated SMS API could replace them without touching business logic.

Consent rule: nothing in this module sends to a person who hasn't opted in.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import httpx

from app.core.config import get_settings
from app.models import Person
from app.services import email as email_service

logger = logging.getLogger("kiowa.sms")


def to_e164(phone: str | None) -> str | None:
    """US/Canada numbers (the club's membership) to E.164."""
    digits = ten_digits(phone)
    return f"+1{digits}" if digits else None


def ten_digits(phone: str | None) -> str | None:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) == 10 else None


# Veriphone's carrier is a free-text network name ("Verizon Wireless",
# "AT&T Mobility"), so carriers are matched by pattern. Order matters where
# one name contains another: Metro by T-Mobile before T-Mobile.
CARRIER_GATEWAYS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(p, re.IGNORECASE), domain)
    for p, domain in [
        (r"metro\s*pcs|metro\s*by\s*t-?mobile", "mymetropcs.com"),
        (r"t-?mobile", "tmomail.net"),
        (r"verizon", "vtext.com"),
        (r"at&?t", "txt.att.net"),
        (r"sprint", "messaging.sprintpcs.com"),
        (r"boost", "sms.myboostmobile.com"),
        (r"cricket", "sms.cricketwireless.net"),
        (r"u\.?s\.?\s*cellular", "email.uscc.net"),
        (r"google\s*fi", "msg.fi.google.com"),
        (r"virgin\s*mobile", "vmobl.com"),
        (r"republic\s*wireless", "text.republicwireless.com"),
        (r"straight\s*talk", "vtext.com"),
        (r"xfinity", "vtext.com"),
    ]
]


def gateway_domain_for_carrier(carrier: str) -> str | None:
    return next((domain for pattern, domain in CARRIER_GATEWAYS if pattern.search(carrier)), None)


@dataclass
class SmsResult:
    status: str  # "sent" or "failed"
    error: str | None = None
    gateway_address: str | None = None
    message_id: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class CarrierLookup(Protocol):
    def lookup(self, phone_e164: str) -> tuple[str | None, str | None]:
        """Returns (carrier, error)."""
        ...


class VeriphoneLookup:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def lookup(self, phone_e164: str) -> tuple[str | None, str | None]:
        try:
            response = httpx.get("https://api.veriphone.io/v2/verify", params={"phone": phone_e164, "key": self.api_key}, timeout=15)
        except httpx.HTTPError as exc:
            return None, f"Carrier lookup unavailable: {exc}"
        if response.status_code >= 400:
            return None, f"Carrier lookup failed ({response.status_code})"
        data = response.json()
        if data.get("status") == "error":
            return None, data.get("error") or "Carrier lookup failed"
        if not data.get("phone_valid"):
            return None, "Phone number is not valid"
        if data.get("phone_type") not in (None, "", "mobile"):
            return None, "Not a mobile number"
        if not data.get("carrier"):
            return None, "No carrier found for this number"
        return data["carrier"], None


class SmsProvider(Protocol):
    name: str
    def send(self, person: Person, body: str, media_url: str | None = None) -> SmsResult: ...


class TelnyxSmsProvider:
    """Telnyx Messaging API provider. Delivery is finalized by the Telnyx webhook."""
    name = "telnyx"

    def send(self, person: Person, body: str, media_url: str | None = None) -> SmsResult:
        number = to_e164(person.phone)
        if not number:
            return SmsResult("failed", "No valid 10-digit mobile number on file.")
        settings = get_settings()
        payload: dict[str, object] = {"from": settings.telnyx_from_number, "to": number, "text": body}
        if settings.telnyx_messaging_profile_id:
            payload["messaging_profile_id"] = settings.telnyx_messaging_profile_id
        if media_url:
            payload["media_urls"] = [media_url]
        try:
            response = httpx.post(
                "https://api.telnyx.com/v2/messages",
                headers={"Authorization": f"Bearer {settings.telnyx_api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=20,
            )
        except httpx.HTTPError as exc:
            return SmsResult("failed", f"Telnyx request failed: {exc}")
        if response.status_code >= 400:
            try:
                detail = response.json().get("errors") or response.text
            except ValueError:
                detail = response.text
            return SmsResult("failed", f"Telnyx rejected message ({response.status_code}): {detail}")
        data = response.json().get("data") or {}
        return SmsResult("sent", None, None, data.get("id"))


class GatewaySmsProvider:
    name = "gateway"
    def __init__(self, lookup: CarrierLookup) -> None:
        self.lookup = lookup
    def send(self, person: Person, body: str, media_url: str | None = None) -> SmsResult:
        digits = ten_digits(person.phone)
        if not digits:
            return SmsResult("failed", "No valid 10-digit mobile number on file.")
        if not person.sms_carrier:
            carrier, error = self.lookup.lookup(f"+1{digits}")
            if not carrier:
                return SmsResult("failed", error)
            person.sms_carrier = carrier[:120]
        domain = gateway_domain_for_carrier(person.sms_carrier)
        if not domain:
            return SmsResult("failed", f"Texts can't be sent to {person.sms_carrier} customers through an email gateway.")
        address = f"{digits}@{domain}"
        settings = get_settings()
        result = email_service.get_email_provider().send(email_service.EmailMessage(
            to=address, subject="", html="", text=body,
            from_override=f"{settings.sms_from_name} <{settings.sms_from_address or settings.email_from_address}>",
            tags={"category": "sms_gateway"},
        ))
        if not result.ok:
            return SmsResult("failed", result.error, address)
        return SmsResult("sent", None, address, result.message_id)


class ConsoleSmsProvider:
    name = "console"
    def __init__(self) -> None:
        self.outbox: list[tuple[str, str]] = []
    def send(self, person: Person, body: str, media_url: str | None = None) -> SmsResult:
        number = to_e164(person.phone)
        if not number:
            return SmsResult("failed", "No valid 10-digit mobile number on file.")
        self.outbox.append((number, body))
        logger.info("sms_console_send", extra={"to": number[-4:], "length": len(body)})
        return SmsResult("sent", None, f"{number[2:]}@console.invalid", f"console-sms-{len(self.outbox)}")


class DisabledSmsProvider:
    name = "disabled"
    def send(self, person: Person, body: str, media_url: str | None = None) -> SmsResult:
        return SmsResult("failed", "Text messaging is not configured.")


@lru_cache(maxsize=1)
def get_sms_provider() -> SmsProvider:
    settings = get_settings()
    if settings.sms_provider == "telnyx":
        if not settings.telnyx_api_key or not settings.telnyx_from_number:
            logger.error("sms_provider_misconfigured", extra={"detail": "TELNYX_API_KEY/TELNYX_FROM_NUMBER missing"})
            return DisabledSmsProvider()
        return TelnyxSmsProvider()
    if settings.sms_provider == "gateway":
        if not settings.veriphone_api_key:
            logger.error("sms_provider_misconfigured", extra={"detail": "VERIPHONE_API_KEY missing"})
            return DisabledSmsProvider()
        return GatewaySmsProvider(VeriphoneLookup(settings.veriphone_api_key))
    if settings.sms_provider == "console":
        return ConsoleSmsProvider()
    return DisabledSmsProvider()


class ConsentError(Exception):
    pass


def send_to_person(person: Person, body: str, media_url: str | None = None) -> SmsResult:
    """The only path to an outgoing text. Refuses anyone without recorded consent."""
    if not person.sms_opt_in or person.sms_opt_in_at is None:
        raise ConsentError("This person has not opted in to text messages.")
    return get_sms_provider().send(person, body, media_url)


# ---------------------------------------------------------------------------
# Carrier content screening (ported from kiowa-gun lib/contentFilter.ts)
#
# Carriers filter A2P traffic in the "SHAFT" categories (Sex, Hate, Alcohol,
# Firearms, Tobacco). A gun club's normal vocabulary trips the firearms
# category, so the board is shown flagged words and a suggested rewrite and
# chooses which version to send.
# ---------------------------------------------------------------------------

_RISK_ENTRIES: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(p, re.IGNORECASE), label, replacement)
    for p, label, replacement in [
        (r"\bporn\w*\b", "porn", ""),
        (r"\bxxx\b", "xxx", ""),
        (r"\bnude\w*\b", "nude", ""),
        (r"\bescort\w*\b", "escort", ""),
        (r"\bsex\w*\b", "sex", ""),
        (r"\bhate speech\b", "hate speech", ""),
        (r"\bracist\w*\b", "racist", ""),
        (r"\bbigot\w*\b", "bigot", ""),
        (r"\balcohol\w*\b", "alcohol", "refreshments"),
        (r"\bbeer\b", "beer", "refreshments"),
        (r"\bwine\b", "wine", "refreshments"),
        (r"\bliquor\b", "liquor", "refreshments"),
        (r"\bwhiskey\b", "whiskey", "refreshments"),
        (r"\bvodka\b", "vodka", "refreshments"),
        (r"\bdrunk\w*\b", "drunk", ""),
        (r"\bopen bar\b", "open bar", "refreshments provided"),
        (r"\bguns? for sale\b", "guns for sale", "items available at the club"),
        (r"\bbuy (a )?guns?\b", "buy gun(s)", "visit the club"),
        (r"\bammo(?: for)? sale\b", "ammo sale", "supplies available"),
        (r"\bfirearms? for sale\b", "firearms for sale", "items available at the club"),
        (r"\bdiscount(?:ed)? ammo\b", "discounted ammo", "member pricing"),
        (r"\bguns?\b", "gun", "equipment"),
        (r"\brifles?\b", "rifle", "equipment"),
        (r"\bpistols?\b", "pistol", "equipment"),
        (r"\bshotguns?\b", "shotgun", "equipment"),
        (r"\bfirearms?\b", "firearm", "equipment"),
        (r"\bweapons?\b", "weapon", "equipment"),
        (r"\bammo\b", "ammo", "supplies"),
        (r"\bammunition\b", "ammunition", "supplies"),
        (r"\bexplosive\w*\b", "explosive", ""),
        (r"\bbomb\w*\b", "bomb", ""),
        (r"\bkill\w*\b", "kill", ""),
        (r"\btobacco\b", "tobacco", ""),
        (r"\bcigarette\w*\b", "cigarette", ""),
        (r"\bvap(?:e|es|ing)\b", "vape", ""),
        (r"\bmarijuana\b", "marijuana", ""),
        (r"\bcannabis\b", "cannabis", ""),
        (r"\bweed\b", "weed", ""),
        (r"\bcocaine\b", "cocaine", ""),
        (r"\bnarcotic\w*\b", "narcotic", ""),
    ]
]

_FALLBACK_MESSAGE = "Message from the board -- please check your email or the member portal for details."


def find_risky_words(text: str) -> list[str]:
    return sorted({label for pattern, label, _ in _RISK_ENTRIES if pattern.search(text)})


def build_safe_message(text: str) -> str:
    safe = text
    for pattern, _, replacement in _RISK_ENTRIES:
        safe = pattern.sub(replacement, safe)
    safe = re.sub(r"\s{2,}", " ", safe)
    safe = re.sub(r"\s+([.,!?])", r"\1", safe).strip()
    return safe or _FALLBACK_MESSAGE
