"""Wipe specific records (test accounts, bogus payments, junk events, ...) from the database.

Fill in the WIPE lists below with the exact records to remove, then:

    python clean_data.py            # dry run: prints every row that would be deleted
    python clean_data.py --apply    # deletes them and their stored files

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

PEOPLE_EMAILS: list[str] = [
    "gavingriffith212@gmail.com"
    "mooredevelopment@sbcglobal.net",
    "gavingriffith1@outlook.com",
    "ggriffith288@gmail.com",
    "gavin.griffith2026@outlook.com",
]
PERSON_IDS: list[int] = []
APPLICATION_IDS: list[int] = []
PAYMENT_IDS: list[int] = []
DOCUMENT_IDS: list[int] = []
CALENDAR_EVENT_IDS: list[int] = []
MATCH_IDS: list[int] = []
EMAIL_CAMPAIGN_IDS: list[int] = []
SMS_CAMPAIGN_IDS: list[int] = []
AUDIT_LOG_IDS: list[int] = []


class Wiper:
    def __init__(self, db: Session) -> None:
        self.db = db
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

    def people(self, emails: list[str], ids: list[int]) -> None:
        people = self.by_ids(Person, ids)
        if emails:
            wanted = {email.strip().lower() for email in emails}
            found = list(self.db.scalars(select(Person).where(func.lower(Person.email).in_(wanted))))
            missing = sorted(wanted - {p.email.lower() for p in found})
            if missing:
                print(f"  ! Person not found: {missing}")
            people += [p for p in found if p not in people]
        for person in people:
            print(f"Person #{person.id} {person.first_name} {person.last_name} <{person.email}>")
            # payments, documents and applications block the delete (ON DELETE RESTRICT).
            for payment in self.db.scalars(select(Payment).where(Payment.person_id == person.id)):
                self.payment(payment)
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

    def payment(self, payment: Payment) -> None:
        self.remove(payment, f"payment #{payment.id} ${payment.amount} {payment.status} {payment.description or ''}".rstrip())

    def document(self, document: Document) -> None:
        self.remove(document, f"document #{document.id} {document.document_type} {document.original_filename}", document.storage_key)

    def calendar_event(self, event: CalendarEvent) -> None:
        self.remove(event, f"calendar event #{event.id} {event.title}", event.image_key, event.document_key)

    def match(self, match: Match) -> None:
        self.remove(match, f"match #{match.id} {match.discipline} on {match.event_date}", *(p.storage_key for p in match.photos))

    def run(self) -> None:
        self.people(PEOPLE_EMAILS, PERSON_IDS)
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
    args = parser.parse_args(argv[1:])

    with get_sessionmaker()() as db:
        wiper = Wiper(db)
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
