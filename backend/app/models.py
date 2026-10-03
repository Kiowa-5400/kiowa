"""SQLAlchemy models for the Kiowa Gun Club database (PostgreSQL).

Schema changes are made through Alembic migrations in ``backend/alembic``;
the application never calls ``create_all`` at runtime.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

JsonType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


def _in(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=utcnow, onupdate=utcnow
    )


# ---------------------------------------------------------------------------
# People, accounts and board roles
# ---------------------------------------------------------------------------

MEMBERSHIP_STATUSES = ("member", "waiting_list", "non_member", "expired", "terminated")
BOARD_ROLES = ("tech_admin", "president", "vice_president", "treasurer", "board_member")


class Person(TimestampMixin, Base):
    """The canonical contact record: members, applicants, board, and other contacts.

    A person can also hold a login (password_hash) for the member portal and,
    with an active ``BoardUser`` row, the board application.
    """

    __tablename__ = "people"
    __table_args__ = (
        CheckConstraint(_in("membership_status", MEMBERSHIP_STATUSES), name="membership_status"),
        Index("uq_people_email_lower", func.lower(text("email")), unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str] = mapped_column(String(120))
    last_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(40))
    address_line1: Mapped[str | None] = mapped_column(String(255))
    address_line2: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str | None] = mapped_column(String(40))
    zip_code: Mapped[str | None] = mapped_column(String(20))

    membership_status: Mapped[str] = mapped_column(String(30), default="non_member", server_default="non_member", index=True)
    # Groups that sit on top of status (a board member is also a Member).
    on_board: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    on_shooting_committee: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    member_since: Mapped[date | None] = mapped_column(Date)
    # The shared annual dues cutoff this person has paid through (see services/renewal.py).
    renewal_date: Mapped[date | None] = mapped_column(Date, index=True)
    terminated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    nra_number: Mapped[str | None] = mapped_column(String(20), unique=True)
    nra_expiration_date: Mapped[date | None] = mapped_column(Date)
    # Flipped off by the nightly NRA check once the expiration passes; only a
    # board review of new proof turns it back on.
    nra_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    background_check_cleared: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    background_check_cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    sms_opt_in: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    sms_opt_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sms_opt_in_source: Mapped[str | None] = mapped_column(String(60))
    # Carrier from the Veriphone lookup, cached so repeat texts skip the lookup.
    # Cleared whenever the phone number changes (services/membership.update_profile).
    sms_carrier: Mapped[str | None] = mapped_column(String(120))
    sms_opt_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_opt_out: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    email_opt_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unsubscribe_token: Mapped[str] = mapped_column(String(64), unique=True, default=lambda: uuid.uuid4().hex)

    notes: Mapped[str | None] = mapped_column(Text)

    password_hash: Mapped[str | None] = mapped_column(String(255))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    board_user: Mapped[BoardUser | None] = relationship(
        back_populates="person", uselist=False, foreign_keys="BoardUser.person_id"
    )
    applications: Mapped[list[Application]] = relationship(
        back_populates="person", foreign_keys="Application.person_id", order_by="Application.created_at.desc()"
    )
    documents: Mapped[list[Document]] = relationship(back_populates="person", foreign_keys="Document.person_id")
    payments: Mapped[list[Payment]] = relationship(back_populates="person", foreign_keys="Payment.person_id")

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class BoardUser(TimestampMixin, Base):
    __tablename__ = "board_users"
    __table_args__ = (CheckConstraint(_in("role", BOARD_ROLES), name="role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), unique=True)
    role: Mapped[str] = mapped_column(String(30), default="board_member")
    # Display title only (e.g. "Secretary"); grants no permissions.
    position: Mapped[str | None] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    invited_by_id: Mapped[int | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    person: Mapped[Person] = relationship(back_populates="board_user", foreign_keys=[person_id])


class PositionOption(Base):
    __tablename__ = "position_options"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(120), unique=True)


SESSION_REALMS = ("member", "board")


class AuthSession(Base):
    __tablename__ = "sessions"
    __table_args__ = (CheckConstraint(_in("realm", SESSION_REALMS), name="realm"),)

    # sha256 of the cookie value; the raw token never touches the database.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    realm: Mapped[str] = mapped_column(String(10))
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))

    person: Mapped[Person] = relationship()


TOKEN_PURPOSES = ("password_reset", "email_verification", "board_invite")


class AuthToken(Base):
    """One-time emailed links: password setup/reset, email verification, board invites."""

    __tablename__ = "auth_tokens"
    __table_args__ = (CheckConstraint(_in("purpose", TOKEN_PURPOSES), name="purpose"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(30))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------------------
# Membership applications, documents, payments
# ---------------------------------------------------------------------------

APPLICATION_TYPES = ("renewal", "waiting_list")
APPLICATION_STATUSES = ("draft", "submitted", "needs_info", "approved", "declined", "completed", "withdrawn")
DOCUMENTATION_METHODS = ("background_check", "concealed_carry")
PAYMENT_STATES = ("unpaid", "pending", "paid", "refunded")


class Application(TimestampMixin, Base):
    __tablename__ = "applications"
    __table_args__ = (
        CheckConstraint(_in("application_type", APPLICATION_TYPES), name="application_type"),
        CheckConstraint(_in("status", APPLICATION_STATUSES), name="status"),
        CheckConstraint(_in("payment_status", PAYMENT_STATES), name="payment_status"),
        CheckConstraint(
            "documentation_method IS NULL OR " + _in("documentation_method", DOCUMENTATION_METHODS),
            name="documentation_method",
        ),
        Index("ix_applications_status_type", "status", "application_type"),
        # At most one open application per person, enforced by the database.
        Index(
            "uq_applications_one_open",
            "person_id",
            unique=True,
            postgresql_where=text("status IN ('draft', 'submitted', 'needs_info', 'approved')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="RESTRICT"), index=True)
    application_type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="draft", server_default="draft")

    # Waiting list: which proof the applicant is providing.
    documentation_method: Mapped[str | None] = mapped_column(String(30))
    claims_cleanup_discount: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    applicant_notes: Mapped[str | None] = mapped_column(Text)

    # Snapshot of the personal info as submitted (the live record is on Person).
    submitted_profile: Mapped[dict[str, Any] | None] = mapped_column(JsonType)

    rules_version: Mapped[str | None] = mapped_column(String(40))
    rules_acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    printed_name: Mapped[str | None] = mapped_column(String(200))
    signature_name: Mapped[str | None] = mapped_column(String(200))
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signature_ip: Mapped[str | None] = mapped_column(String(64))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Board review
    nra_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discount_approved: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    info_request_message: Mapped[str | None] = mapped_column(Text)

    # Payment gating: the board decides when payment opens; eligibility is
    # derived by services/membership.evaluate_payment_eligibility and cached
    # here (with the reason) so the board can see why someone can't pay.
    payment_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payment_status: Mapped[str] = mapped_column(String(20), default="unpaid", server_default="unpaid")
    payment_eligible: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    payment_block_reason: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    person: Mapped[Person] = relationship(back_populates="applications", foreign_keys=[person_id])
    reviewed_by: Mapped[Person | None] = relationship(foreign_keys=[reviewed_by_id])
    documents: Mapped[list[Document]] = relationship(back_populates="application")
    payments: Mapped[list[Payment]] = relationship(back_populates="application")
    notes: Mapped[list[ApplicationNote]] = relationship(
        back_populates="application", order_by="ApplicationNote.created_at", cascade="all, delete-orphan"
    )


class ApplicationNote(Base):
    __tablename__ = "application_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())

    application: Mapped[Application] = relationship(back_populates="notes")
    author: Mapped[Person | None] = relationship()


DOCUMENT_TYPES = ("nra_proof", "background_check", "concealed_carry", "cleanup_discount", "other")
REVIEW_STATUSES = ("pending", "approved", "rejected")


class Document(Base):
    """A private membership document. Never served without authorization."""

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(_in("document_type", DOCUMENT_TYPES), name="document_type"),
        CheckConstraint(_in("review_status", REVIEW_STATUSES), name="review_status"),
        CheckConstraint("size_bytes > 0", name="size_positive"),
        Index("ix_documents_review_status", "review_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="RESTRICT"), index=True)
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id", ondelete="SET NULL"), index=True)
    document_type: Mapped[str] = mapped_column(String(30))
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    review_status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_notes: Mapped[str | None] = mapped_column(Text)
    # Set when the stored file is deleted (e.g. after membership termination);
    # the metadata row stays for the audit trail.
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    person: Mapped[Person] = relationship(back_populates="documents", foreign_keys=[person_id])
    application: Mapped[Application | None] = relationship(back_populates="documents")
    reviewed_by: Mapped[Person | None] = relationship(foreign_keys=[reviewed_by_id])


PAYMENT_STATUSES = ("pending", "paid", "failed", "cancelled", "refunded", "partially_refunded")
PAYMENT_METHODS = ("card", "cash", "check", "other")


class Payment(TimestampMixin, Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint(_in("status", PAYMENT_STATUSES), name="status"),
        CheckConstraint(_in("method", PAYMENT_METHODS), name="method"),
        CheckConstraint("amount >= 0", name="amount_non_negative"),
        CheckConstraint("refunded_amount >= 0", name="refunded_non_negative"),
        Index("ix_payments_status_paid_at", "status", "paid_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="RESTRICT"), index=True)
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id", ondelete="SET NULL"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="usd", server_default="usd")
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    method: Mapped[str] = mapped_column(String(10), default="card", server_default="card")
    description: Mapped[str | None] = mapped_column(String(255))
    stripe_checkout_session_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(255), index=True)
    refunded_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"), server_default="0")
    # The renewal cutoff this payment advanced the member's renewal_date to.
    covers_through: Mapped[date | None] = mapped_column(Date)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    recorded_by_id: Mapped[int | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"))
    notes: Mapped[str | None] = mapped_column(Text)

    person: Mapped[Person] = relationship(back_populates="payments", foreign_keys=[person_id])
    application: Mapped[Application | None] = relationship(back_populates="payments")


class StripeEvent(Base):
    """Every processed Stripe webhook event id, so redelivered events are no-ops."""

    __tablename__ = "stripe_events"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())


# ---------------------------------------------------------------------------
# Public website content
# ---------------------------------------------------------------------------


class PageSection(Base):
    __tablename__ = "page_sections"
    __table_args__ = (UniqueConstraint("page_slug", "section_key", name="uq_page_sections_slug_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    page_slug: Mapped[str] = mapped_column(String(60), index=True)
    section_key: Mapped[str] = mapped_column(String(80))
    label: Mapped[str | None] = mapped_column(String(120))
    heading: Mapped[str | None] = mapped_column(String(255))
    # Always sanitized on write (services/html.py).
    body_html: Mapped[str] = mapped_column(Text, default="", server_default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now())
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"))


class SiteSettings(Base):
    """Singleton (id = 1) of board-editable site and membership settings."""

    __tablename__ = "site_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint("dues_amount > 0", name="dues_positive"),
        CheckConstraint("cleanup_discount_amount >= 0", name="discount_non_negative"),
        CheckConstraint("renewal_cutoff_month BETWEEN 1 AND 12", name="cutoff_month"),
        CheckConstraint("renewal_cutoff_day BETWEEN 1 AND 31", name="cutoff_day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    site_title: Mapped[str] = mapped_column(String(120), default="Kiowa Gun Club")
    site_subtitle: Mapped[str] = mapped_column(String(200), default="Great Bend, Kansas")
    contact_email: Mapped[str | None] = mapped_column(String(255))
    contact_phone: Mapped[str | None] = mapped_column(String(40))
    mailing_address: Mapped[str | None] = mapped_column(Text)
    physical_address: Mapped[str | None] = mapped_column(Text)
    map_url: Mapped[str | None] = mapped_column(String(500))
    social_facebook: Mapped[str | None] = mapped_column(String(500))
    social_instagram: Mapped[str | None] = mapped_column(String(500))
    social_youtube: Mapped[str | None] = mapped_column(String(500))
    # [{"label": "...", "url": "https://..."}] shown in the footer.
    footer_links: Mapped[list[dict[str, str]]] = mapped_column(JsonType, default=list)

    dues_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("150.00"))
    cleanup_discount_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    renewal_cutoff_month: Mapped[int] = mapped_column(Integer, default=9)
    renewal_cutoff_day: Mapped[int] = mapped_column(Integer, default=10)
    accepting_waiting_list: Mapped[bool] = mapped_column(Boolean, default=True)
    background_check_url: Mapped[str | None] = mapped_column(String(500))

    # Range rules are versioned: every application records which version it acknowledged.
    rules_version: Mapped[str] = mapped_column(String(40))
    range_rules: Mapped[list[str]] = mapped_column(JsonType, default=list)
    rules_agreement_clause: Mapped[str] = mapped_column(Text, default="")
    rules_reporting_clause: Mapped[str] = mapped_column(Text, default="")

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now())
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"))


SITE_IMAGE_KEYS = ("logo", "hero", "about", "rules", "matches_flyer")


class SiteImage(Base):
    __tablename__ = "site_images"
    __table_args__ = (CheckConstraint(_in("key", SITE_IMAGE_KEYS), name="key"),)

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    storage_key: Mapped[str] = mapped_column(String(500))
    original_filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    alt_text: Mapped[str | None] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now())
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"))


class PublicDocument(Base):
    """Board-published downloads (forms, rules PDF). Public by design."""

    __tablename__ = "public_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(60), default="general")
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"))


# ---------------------------------------------------------------------------
# Calendar and matches
# ---------------------------------------------------------------------------

EVENT_CATEGORIES = ("match", "member", "meeting", "event", "closure")


class CalendarSeries(Base):
    """A recurrence rule that generated a set of individually editable events."""

    __tablename__ = "calendar_series"
    __table_args__ = (
        CheckConstraint("nth BETWEEN 1 AND 5", name="nth"),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200))
    # nth weekday of the month; nth = 5 means "last".
    nth: Mapped[int] = mapped_column(Integer)
    weekday: Mapped[int] = mapped_column(Integer)  # 0 = Sunday .. 6 = Saturday
    start_time: Mapped[time] = mapped_column(Time)
    label: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"))

    events: Mapped[list[CalendarEvent]] = relationship(back_populates="series")


class CalendarEvent(TimestampMixin, Base):
    __tablename__ = "calendar_events"
    __table_args__ = (
        CheckConstraint(_in("category", EVENT_CATEGORIES), name="category"),
        CheckConstraint("ends_at IS NULL OR ends_at >= starts_at", name="ends_after_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    all_day: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    category: Mapped[str] = mapped_column(String(20), default="event", server_default="event")
    description_html: Mapped[str | None] = mapped_column(Text)
    link_url: Mapped[str | None] = mapped_column(String(500))
    link_label: Mapped[str | None] = mapped_column(String(120))
    image_key: Mapped[str | None] = mapped_column(String(500))
    image_filename: Mapped[str | None] = mapped_column(String(255))
    image_mime: Mapped[str | None] = mapped_column(String(100))
    document_key: Mapped[str | None] = mapped_column(String(500))
    document_filename: Mapped[str | None] = mapped_column(String(255))
    series_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("calendar_series.id", ondelete="SET NULL"), index=True)
    recurrence_label: Mapped[str | None] = mapped_column(String(200))

    series: Mapped[CalendarSeries | None] = relationship(back_populates="events")


class Match(TimestampMixin, Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Free text so the board can add a discipline without a code change.
    discipline: Mapped[str] = mapped_column(String(120), default="Defensive Pistol", index=True)
    event_date: Mapped[date] = mapped_column(Date, index=True)
    start_time: Mapped[time | None] = mapped_column(Time)
    notes: Mapped[str | None] = mapped_column(Text)
    results_url: Mapped[str | None] = mapped_column(String(500))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    photos: Mapped[list[MatchPhoto]] = relationship(
        back_populates="match", order_by="MatchPhoto.sort_order", cascade="all, delete-orphan"
    )


class MatchPhoto(Base):
    __tablename__ = "match_photos"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), index=True)
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    caption: Mapped[str | None] = mapped_column(String(255))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())

    match: Mapped[Match] = relationship(back_populates="photos")


# ---------------------------------------------------------------------------
# Communications
# ---------------------------------------------------------------------------

CAMPAIGN_KINDS = ("manual", "renewal_reminder", "system")
EMAIL_RECIPIENT_STATUSES = ("queued", "sent", "failed", "delivered", "bounced", "complained")
SMS_RECIPIENT_STATUSES = ("queued", "sent", "delivered", "undelivered", "failed", "skipped")


class EmailCampaign(Base):
    __tablename__ = "email_campaigns"
    __table_args__ = (CheckConstraint(_in("kind", CAMPAIGN_KINDS), name="kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), default="manual", server_default="manual")
    subject: Mapped[str] = mapped_column(String(255))
    body_html: Mapped[str] = mapped_column(Text)
    recipient_summary: Mapped[str | None] = mapped_column(Text)
    attachment_names: Mapped[list[str]] = mapped_column(JsonType, default=list)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    sent_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    recipients: Mapped[list[EmailRecipient]] = relationship(back_populates="campaign", cascade="all, delete-orphan")
    created_by: Mapped[Person | None] = relationship()


class EmailRecipient(Base):
    __tablename__ = "email_recipients"
    __table_args__ = (CheckConstraint(_in("status", EMAIL_RECIPIENT_STATUSES), name="status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("email_campaigns.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[int | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"), index=True)
    email: Mapped[str] = mapped_column(String(255))
    provider_message_id: Mapped[str | None] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", server_default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    clicked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bounced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bounce_type: Mapped[str | None] = mapped_column(String(100))
    complained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    campaign: Mapped[EmailCampaign] = relationship(back_populates="recipients")


class EmailAsset(Base):
    """Images embedded in, and files attached to, board emails."""

    __tablename__ = "email_assets"
    __table_args__ = (CheckConstraint(_in("kind", ("image", "attachment")), name="kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    public_token: Mapped[str] = mapped_column(String(64), unique=True, default=lambda: uuid.uuid4().hex)
    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())


class SmsCampaign(Base):
    __tablename__ = "sms_campaigns"
    __table_args__ = (CheckConstraint(_in("kind", CAMPAIGN_KINDS), name="kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), default="manual", server_default="manual")
    body: Mapped[str] = mapped_column(Text)
    recipient_summary: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    sent_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    fallback_email_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    media_asset_id: Mapped[int | None] = mapped_column(ForeignKey("email_assets.id", ondelete="SET NULL"))

    recipients: Mapped[list[SmsRecipient]] = relationship(back_populates="campaign", cascade="all, delete-orphan")
    created_by: Mapped[Person | None] = relationship()


class SmsRecipient(Base):
    __tablename__ = "sms_recipients"
    __table_args__ = (CheckConstraint(_in("status", SMS_RECIPIENT_STATUSES), name="status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("sms_campaigns.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[int | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"), index=True)
    phone: Mapped[str] = mapped_column(String(40))
    # Retained for historical gateway deliveries; Telnyx deliveries leave this null.
    gateway_address: Mapped[str | None] = mapped_column(String(255))
    provider_message_id: Mapped[str | None] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", server_default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
    # When the text failed, the same message was emailed to the person instead.
    fallback_email_sent: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))

    campaign: Mapped[SmsCampaign] = relationship(back_populates="recipients")


class SmsProviderEvent(Base):
    __tablename__ = "sms_provider_events"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())


# ---------------------------------------------------------------------------
# Renewal automation, scheduled jobs, audit
# ---------------------------------------------------------------------------


class RenewalReminder(Base):
    """One row per (person, renewal cycle, threshold, channel) so reminders never repeat."""

    __tablename__ = "renewal_reminders"
    __table_args__ = (
        UniqueConstraint("person_id", "cycle_date", "threshold_days", "channel", name="uq_renewal_reminders_once"),
        CheckConstraint(_in("channel", ("email", "sms")), name="channel"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    cycle_date: Mapped[date] = mapped_column(Date)
    threshold_days: Mapped[int] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(String(10))
    succeeded: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())


class JobRun(Base):
    __tablename__ = "job_runs"
    __table_args__ = (UniqueConstraint("job_name", "period_key", name="uq_job_runs_job_period"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_name: Mapped[str] = mapped_column(String(80))
    period_key: Mapped[str] = mapped_column(String(40))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="running")
    result: Mapped[dict[str, Any] | None] = mapped_column(JsonType)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_entity", "entity_type", "entity_id"),)

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now(), index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"), index=True)
    actor_label: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(60))
    summary: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    request_id: Mapped[str | None] = mapped_column(String(64))
