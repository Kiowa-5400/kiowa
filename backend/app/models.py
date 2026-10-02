from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class PersonStatus(str, Enum):
    ACTIVE_MEMBER = "active_member"
    BOARD = "board"
    SHOOTING_COMMITTEE = "shooting_committee"
    WAITING_LIST = "waiting_list"
    VISITOR = "visitor"
    FORMER_MEMBER = "former_member"
    EXPIRED = "expired"


class ApplicationType(str, Enum):
    RENEWAL = "renewal"
    WAITING_LIST = "waiting_list"
    UPDATE = "update"


class ApplicationStatus(str, Enum):
    STARTED = "started"
    SUBMITTED = "submitted"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    ACTIVE_MEMBER = "active_member"
    EXPIRED = "expired"
    DECLINED = "declined"


class PaymentStatus(str, Enum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class Person(Base):
    __tablename__ = "people"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    first_name: Mapped[str] = mapped_column(String(120), nullable=False)
    last_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    state: Mapped[str | None] = mapped_column(String(80), nullable=True)
    zip_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(40), default="visitor", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default=PersonStatus.VISITOR.value, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    applications: Mapped[list["Application"]] = relationship(back_populates="person")
    documents: Mapped[list["Document"]] = relationship(back_populates="person")
    payments: Mapped[list["Payment"]] = relationship(back_populates="person")


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"), nullable=False, index=True)
    application_type: Mapped[str] = mapped_column(String(40), default=ApplicationType.RENEWAL.value, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default=ApplicationStatus.SUBMITTED.value, nullable=False)
    payment_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    amount_due: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    rules_version: Mapped[str] = mapped_column(String(40), default="2026-10-01", nullable=False)
    rules_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rules_acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    signature: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    person: Mapped[Person] = relationship(back_populates="applications")
    documents: Mapped[list["Document"]] = relationship(back_populates="application")
    payments: Mapped[list["Payment"]] = relationship(back_populates="application")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"), nullable=False, index=True)
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id"), nullable=True, index=True)
    document_type: Mapped[str] = mapped_column(String(80), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    original_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_size: Mapped[int | None] = mapped_column(nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    review_status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    person: Mapped[Person] = relationship(back_populates="documents")
    application: Mapped[Application | None] = relationship(back_populates="documents")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"), nullable=False, index=True)
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id"), nullable=True, index=True)
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    expected_amount: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default=PaymentStatus.PENDING.value, nullable=False)
    stripe_reference: Mapped[str | None] = mapped_column(String(150), nullable=True)
    stripe_session_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    stripe_event_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    payment_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    person: Mapped[Person] = relationship(back_populates="payments")
    application: Mapped[Application | None] = relationship(back_populates="payments")
