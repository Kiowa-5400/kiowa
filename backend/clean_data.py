"""Wipe specific records (test accounts, bogus payments, junk events, ...) from the database.

Fill in the WIPE lists below with the exact records to remove, then:

    python clean_data.py            # dry run: prints every row that would be deleted
    python clean_data.py --apply    # deletes them and their stored files
    python clean_data.py --list-payments   # every payment, to find fake cash/check IDs

Run it on the Render "kiowa" shell: it has DATABASE_URL and the disk holding
the stored files. People with a board login are skipped unless --include-board.

A payment deleted on its own (PAYMENT_IDS, STRIPE_TEST_PAYMENTS) puts its
application back to unpaid, but does not undo the membership it granted; the
dry run flags those so the member's status and renewal date can be fixed.

Deleting a person also removes everything that belongs to them: applications
(and their notes), payments, documents, sessions, login links, board access
and renewal reminders. Their name stays on audit log entries and campaign
recipient lists they appear in; those links are set to NULL by the database.

Stored files (documents, event images/PDFs, match photos) are deleted only
after the database commit succeeds, so a failed run never loses a file whose
row is still there.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_sessionmaker
from app.models import (
    Application,
    AuditLog,
    CalendarEvent,
    Document,
    EmailCampaign,
    Match,
    Payment,
    Person,
    SmsCampaign,
)
from app.services.storage import delete_quietly

# ---------------------------------------------------------------------------
# WIPE: what to delete. Leave a list empty to skip it.
# ---------------------------------------------------------------------------

PEOPLE_NAMES: list[str] = [  # "First Last", case-insensitive; every match is removed
    "Sponge Bob",
    "Scooby Doo",
    "Foo Foo",
    "Homer Simpson",
]
PEOPLE_EMAILS: list[str] = [
    "gavingriffith212@gmail.com",
    "mooredevelopment@sbcglobal.net",
    "gavingriffith1@outlook.com",
    "ggriffith288@gmail.com",
    "gavin.griffith2026@outlook.com",
]
PERSON_IDS: list[int] = []
APPLICATION_IDS: list[int] = []
PAYMENT_IDS: list[int] = []  # fake cash/check entries; find them with --list-payments
# Payments made with Stripe test keys (cs_test_ sessions). The live webhook
# never touches them, and pending ones would fail the daily reconciliation.
STRIPE_TEST_PAYMENTS = True
DOCUMENT_IDS: list[int] = []
CALENDAR_EVENT_IDS: list[int] = []
MATCH_IDS: list[int] = []
EMAIL_CAMPAIGN_IDS: list[int] = []
SMS_CAMPAIGN_IDS: list[int] = []
AUDIT_LOG_IDS: list[int] = []


class Wiper:
    def __init__(self, db: Session, *, include_board: bool = False) -> None:
        self.db = db
        self.include_board = include_board
        self.storage_keys: list[str] = []
        self.deleted = 0

    def remove(self, row: object, label: str, *keys: str | None) -> None:
        print(f"  - {label}")
        self.storage_keys.extend(key for key in keys if key)
        self.db.delete(row)
        self.deleted += 1

    def by_ids(self, model: type, ids: list[int]) -> list:
        if not ids:
            return []
        rows = list(self.db.scalars(select(model).where(model.id.in_(ids)).order_by(model.id)))
        missing = sorted(set(ids) - {row.id for row in rows})
        if missing:
            print(f"  ! {model.__name__} not found: {missing}")
        return rows

    def people(self, names: list[str], emails: list[str], ids: list[int]) -> None:
        people = self.by_ids(Person, ids)
        for name in names:
            full_name = func.lower(Person.first_name + " " + Person.last_name)
            found = list(self.db.scalars(select(Person).where(full_name == " ".join(name.lower().split()))))
            if not found:
                print(f"  ! Person not found: {name!r}")
            people += [p for p in found if p not in people]
        if emails:
            wanted = {email.strip().lower() for email in emails}
            found = list(self.db.scalars(select(Person).where(func.lower(Person.email).in_(wanted))))
            missing = sorted(wanted - {p.email.lower() for p in found})
            if missing:
                print(f"  ! Person not found: {missing}")
            people += [p for p in found if p not in people]
        for person in people:
            print(f"Person #{person.id} {person.first_name} {person.last_name} <{person.email}>")
            if person.board_user is not None and not self.include_board:
                print(f"  ! skipped: has a board login ({person.board_user.role}); re-run with --include-board to remove it")
                continue
            # payments, documents and applications block the delete (ON DELETE RESTRICT).
            for payment in self.db.scalars(select(Payment).where(Payment.person_id == person.id)):
                self.remove(payment, self.payment_label(payment))
            for document in self.db.scalars(select(Document).where(Document.person_id == person.id)):
                self.document(document)
            for application in self.db.scalars(select(Application).where(Application.person_id == person.id)):
                self.application(application)
            # Without an ORM cascade, SQLAlchemy would try to NULL board_users.person_id.
            if person.board_user is not None:
                self.remove(person.board_user, f"board login ({person.board_user.role})")
            self.db.flush()
            self.remove(person, f"person #{person.id}")

    def application(self, application: Application) -> None:
        self.remove(application, f"application #{application.id} ({application.application_type}, {application.status})")

    @staticmethod
    def payment_label(payment: Payment) -> str:
        return (f"payment #{payment.id} ${payment.amount} {payment.method} {payment.status} "
                f"{payment.person.first_name} {payment.person.last_name} {payment.stripe_checkout_session_id or ''}").rstrip()

    def payment(self, payment: Payment) -> None:
        """A payment removed on its own; its person stays, so undo what it did to their application."""
        self.remove(payment, self.payment_label(payment))
        self.db.flush()
        if payment.covers_through is not None:
            print(f"    ! it made {payment.person.first_name} {payment.person.last_name} a member through "
                  f"{payment.covers_through}; correct their status and renewal date on the board site if that was fake")
        application = payment.application
        if application is not None and application.payment_status in ("pending", "paid"):
            still_paying = self.db.scalar(select(func.count()).select_from(Payment).where(
                Payment.application_id == application.id, Payment.status.in_(("pending", "paid"))))
            if not still_paying:
                if application.payment_status == "paid":
                    print(f"    ! application #{application.id} was completed by it; review that application")
                application.payment_status = "unpaid"

    def stripe_test_payments(self) -> None:
        rows = list(self.db.scalars(select(Payment).where(
            Payment.stripe_checkout_session_id.like("cs\\_test\\_%")).order_by(Payment.id)))
        if rows:
            print("Stripe test-mode payments:")
        for payment in rows:
            self.payment(payment)

    def document(self, document: Document) -> None:
        self.remove(document, f"document #{document.id} {document.document_type} {document.original_filename}", document.storage_key)

    def calendar_event(self, event: CalendarEvent) -> None:
        self.remove(event, f"calendar event #{event.id} {event.title}", event.image_key, event.document_key)

    def match(self, match: Match) -> None:
        self.remove(match, f"match #{match.id} {match.discipline} on {match.event_date}", *(p.storage_key for p in match.photos))

    def run(self) -> None:
        self.people(PEOPLE_NAMES, PEOPLE_EMAILS, PERSON_IDS)
        self.db.flush()
        if STRIPE_TEST_PAYMENTS:
            self.stripe_test_payments()
        sections = [
            (Application, APPLICATION_IDS, self.application),
            (Payment, PAYMENT_IDS, self.payment),
            (Document, DOCUMENT_IDS, self.document),
            (CalendarEvent, CALENDAR_EVENT_IDS, self.calendar_event),
            (Match, MATCH_IDS, self.match),
            (EmailCampaign, EMAIL_CAMPAIGN_IDS, lambda c: self.remove(c, f"email campaign #{c.id} {c.subject}")),
            (SmsCampaign, SMS_CAMPAIGN_IDS, lambda c: self.remove(c, f"text campaign #{c.id} {c.body[:60]}")),
            (AuditLog, AUDIT_LOG_IDS, lambda a: self.remove(a, f"audit log #{a.id} {a.action} {a.summary or ''}".rstrip())),
        ]
        for model, ids, handler in sections:
            rows = self.by_ids(model, ids)
            if rows:
                print(f"{model.__name__}:")
            for row in rows:  # rows already removed with their person were flushed and won't be found
                handler(row)
        self.db.flush()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Commit the deletes (default is a dry run)")
    parser.add_argument("--include-board", action="store_true", help="Also remove listed people who have a board login")
    parser.add_argument("--list-payments", action="store_true", help="Print every payment (to fill in PAYMENT_IDS) and exit")
    args = parser.parse_args(argv[1:])

    if args.list_payments:
        with get_sessionmaker()() as db:
            for payment in db.scalars(select(Payment).order_by(Payment.id)):
                print(Wiper.payment_label(payment))
        return 0

    with get_sessionmaker()() as db:
        wiper = Wiper(db, include_board=args.include_board)
        wiper.run()
        if args.apply:
            db.commit()
        else:
            db.rollback()

    if args.apply:
        for key in wiper.storage_keys:
            delete_quietly(key)
        print(f"Deleted {wiper.deleted} row(s) and {len(wiper.storage_keys)} stored file(s).")
    else:
        print(f"DRY RUN - {wiper.deleted} row(s) and {len(wiper.storage_keys)} stored file(s) would be deleted. "
              "Re-run with --apply to commit.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
