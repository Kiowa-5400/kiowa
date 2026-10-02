"""Import production data from the old kiowa-gun site (Cloudflare D1) into PostgreSQL.

1. Export D1 and load it into a local SQLite file:
       npx wrangler d1 export kiowa-gun-club --remote --output=kiowa-gun.sql
       sqlite3 kiowa-gun.db < kiowa-gun.sql
2. Optionally copy the R2 bucket (kiowa-gun-club-docs) to a local folder, e.g.
       rclone copy r2:kiowa-gun-club-docs ./r2-export
   Without it, file-backed rows (member documents, match photos, event
   images/PDFs, downloadable forms, site images) are skipped and reported.
3. Run against the new database (DATABASE_URL and storage settings from the environment):
       python -m scripts.import_kiowa_gun kiowa-gun.db --r2-dir ./r2-export --matches-year 2026 --dry-run
       python -m scripts.import_kiowa_gun kiowa-gun.db --r2-dir ./r2-export --matches-year 2026

The import is idempotent: people are matched by email, payments by Stripe
session id, and everything else is skipped if an equivalent row exists.
Passwords are NOT imported (the old PBKDF2 hashes are a different format);
members and board users set a new password with "Set up your account" /
"Forgot password", which emails them a link.
"""

from __future__ import annotations

import argparse
import mimetypes
import re
import sqlite3
import sys
from collections import Counter
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.timeutil import club_local_to_utc
from app.db.session import get_sessionmaker
from app.models import (
    BoardUser,
    CalendarEvent,
    Document,
    Match,
    MatchPhoto,
    PageSection,
    Payment,
    Person,
    PublicDocument,
    SiteImage,
)
from app.services.html import sanitize_html
from app.services.storage import get_storage, new_key
from app.services.uploads import EXTENSIONS, detect_type

STATUS_MAP = {"Member": "member", "Waiting List": "waiting_list", "Pending Review": "waiting_list",
              "Non-Member": "non_member", "Terminated": "terminated"}
ROLE_MAP = {"tech_admin", "president", "vice_president", "treasurer", "board_member"}
DOC_TYPES = {"nra_membership": "nra_proof", "background_check": "background_check", "discount_card": "cleanup_discount"}
IMAGE_KEYS = {"nav-logo": "logo", "nav-hero": "hero", "rules-photo": "rules", "matches-flyer": "matches_flyer"}
MONTHS = {m.lower(): i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).replace(" ", "T").rstrip("Z")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def parse_match_date(text: str, year: int) -> date | None:
    """"March 14th", "Sept 12th" -> date."""
    match = re.match(r"([A-Za-z]+)\.?\s+(\d{1,2})", text.strip())
    if not match:
        return parse_date(text)
    month = MONTHS.get(match.group(1)[:3].lower())
    return date(year, month, int(match.group(2))) if month else None


def parse_clock(text: str | None) -> time | None:
    match = re.match(r"(\d{1,2}):(\d{2})\s*([ap])m?", (text or "").strip().lower())
    if not match:
        return None
    hour = int(match.group(1)) % 12 + (12 if match.group(3) == "p" else 0)
    return time(hour, int(match.group(2)))


def split_name(name: str) -> tuple[str, str]:
    parts = name.strip().split()
    if not parts:
        return "Unknown", ""
    return parts[0], " ".join(parts[1:])


class Importer:
    def __init__(self, source: sqlite3.Connection, db: Session, r2_dir: Path | None, dry_run: bool) -> None:
        self.src = source
        self.db = db
        self.r2_dir = r2_dir
        self.dry_run = dry_run
        self.counts: Counter[str] = Counter()
        self.people: dict[int, Person] = {}  # old member id -> person

    def rows(self, table: str) -> list[sqlite3.Row]:
        exists = self.src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        return self.src.execute(f"SELECT * FROM {table}").fetchall() if exists else []

    def store(self, r2_key: str, prefix: str) -> tuple[str, str, int] | None:
        """Copies an exported R2 object into the new storage; returns (key, mime, size)."""
        if not self.r2_dir:
            self.counts["files skipped (no --r2-dir)"] += 1
            return None
        path = self.r2_dir / r2_key
        if not path.is_file():
            self.counts["files missing from R2 export"] += 1
            return None
        data = path.read_bytes()
        mime = detect_type(data[:16]) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        key = new_key(prefix, EXTENSIONS.get(mime, (path.suffix or ".bin",))[0])
        if not self.dry_run:
            get_storage().put(key, data, mime)
        return key, mime, len(data)

    def find_person(self, email: str) -> Person | None:
        return self.db.scalar(select(Person).where(func.lower(Person.email) == email.strip().lower()))

    def import_members(self) -> None:
        for row in self.rows("members"):
            keys = row.keys()
            email = (row["email"] or "").strip().lower()
            if not email or email.endswith("@removed.invalid"):
                self.counts["members skipped (no usable email)"] += 1
                continue
            person = self.find_person(email)
            if person is None:
                first, last = split_name(row["name"] or "")
                opted_in = bool(row["sms_opt_in"]) if "sms_opt_in" in keys else False
                person = Person(
                    first_name=first[:120], last_name=last[:120], email=email, phone=row["phone"],
                    address_line1=row["address"], membership_status=STATUS_MAP.get(row["status"], "non_member"),
                    on_board=bool(row["on_board"]) if "on_board" in keys else False,
                    on_shooting_committee=bool(row["on_shooting_committee"]) if "on_shooting_committee" in keys else False,
                    nra_number=row["nra_number"] if "nra_number" in keys else None,
                    nra_expiration_date=parse_date(row["nra_expiration_date"]) if "nra_expiration_date" in keys else None,
                    nra_active=bool(row["nra_active"]) if "nra_active" in keys else True,
                    background_check_cleared=bool(row["background_check_cleared"]) if "background_check_cleared" in keys else False,
                    renewal_date=parse_date(row["renewal_date"]) if "renewal_date" in keys else None,
                    terminated_at=parse_timestamp(row["terminated_at"]) if "terminated_at" in keys else None,
                    sms_opt_in=opted_in,
                    sms_opt_in_at=(parse_timestamp(row["sms_opt_in_at"]) or datetime.now(UTC)) if opted_in else None,
                    sms_opt_in_source="kiowa-gun import" if opted_in else None,
                    created_at=parse_timestamp(row["created_at"]) or datetime.now(UTC),
                )
                self.db.add(person)
                self.db.flush()
                self.counts["people created"] += 1
            else:
                self.counts["people already present"] += 1
            self.people[row["id"]] = person

    def import_board(self) -> None:
        for row in self.rows("admin_users"):
            email = row["email"].strip().lower()
            person = self.find_person(email)
            if person is None:
                first, last = split_name(row["name"])
                person = Person(first_name=first, last_name=last, email=email, phone=row["phone"] if "phone" in row.keys() else None,
                                membership_status="member", on_board=True)
                self.db.add(person)
                self.db.flush()
                self.counts["people created (board)"] += 1
            if person.board_user is None:
                role = row["role"] if row["role"] in ROLE_MAP else "board_member"
                self.db.add(BoardUser(person_id=person.id, role=role, position=row["position"] if "position" in row.keys() else None))
                person.on_board = True
                self.counts["board users created"] += 1

    def import_payments(self) -> None:
        for row in self.rows("payments"):
            person = self.people.get(row["member_id"])
            session_id = row["stripe_checkout_session_id"]
            if person is None:
                self.counts["payments skipped (unknown member)"] += 1
                continue
            if session_id and self.db.scalar(select(Payment).where(Payment.stripe_checkout_session_id == session_id)):
                continue
            method = (row["payment_method_type"] or "card").lower()
            self.db.add(Payment(
                person_id=person.id, amount=Decimal(row["amount_cents"]) / 100, currency=row["currency"] or "usd",
                status="paid", method=method if method in ("card", "cash", "check") else "other",
                description="Membership dues (imported from the previous website)",
                stripe_checkout_session_id=session_id, paid_at=parse_timestamp(row["paid_at"]),
                notes="Imported from kiowa-gun",
            ))
            self.counts["payments imported"] += 1

    def import_documents(self) -> None:
        for row in self.rows("documents"):
            member_id = row["member_id"] if "member_id" in row.keys() else None
            if member_id is not None:
                person = self.people.get(member_id)
                doc_type = DOC_TYPES.get(row["category"], "other")
                if person is None:
                    self.counts["documents skipped (unknown member)"] += 1
                    continue
                stored = self.store(row["r2_key"], f"private/documents/{person.id}")
                if stored is None:
                    continue
                key, mime, size = stored
                self.db.add(Document(
                    person_id=person.id, document_type=doc_type, original_filename=row["file_name"][:255], storage_key=key,
                    mime_type=mime, size_bytes=size, sha256="imported",
                    review_status="approved" if row["reviewed"] else "pending", uploaded_at=parse_timestamp(row["uploaded_at"]) or datetime.now(UTC),
                ))
                self.counts["member documents imported"] += 1
            else:
                if self.db.scalar(select(PublicDocument).where(PublicDocument.title == row["title"])):
                    continue
                stored = self.store(row["r2_key"], "public/documents")
                if stored is None:
                    continue
                key, mime, size = stored
                self.db.add(PublicDocument(title=row["title"], description=row["description"], category=row["category"] or "general",
                                           storage_key=key, original_filename=row["file_name"], mime_type=mime, size_bytes=size))
                self.counts["public documents imported"] += 1

    def import_matches(self, year: int) -> None:
        old_photos: dict[int, list[sqlite3.Row]] = {}
        for photo in self.rows("match_photos"):
            old_photos.setdefault(photo["match_id"], []).append(photo)
        for row in self.rows("matches"):
            event_date = parse_match_date(row["event_date"], year)
            if event_date is None:
                self.counts["matches skipped (unreadable date)"] += 1
                continue
            discipline = row["discipline"] if "discipline" in row.keys() else "Defensive Pistol"
            match = self.db.scalar(select(Match).where(Match.event_date == event_date, Match.discipline == discipline))
            if match is None:
                match = Match(discipline=discipline, event_date=event_date, start_time=parse_clock(row["event_time"]),
                              notes=row["notes"], results_url=row["results_url"], sort_order=row["sort_order"] * 10)
                self.db.add(match)
                self.db.flush()
                self.counts["matches imported"] += 1
            elif row["results_url"] and not match.results_url:
                match.results_url = row["results_url"]
                self.counts["match results links added"] += 1
            for photo in old_photos.get(row["id"], []):
                stored = self.store(photo["r2_key"], f"public/match-photos/{match.id}")
                if stored:
                    match.photos.append(MatchPhoto(storage_key=stored[0], original_filename=photo["file_name"],
                                                   mime_type=stored[1], sort_order=photo["sort_order"] * 10))
                    self.counts["match photos imported"] += 1

    def import_calendar(self) -> None:
        for row in self.rows("calendar_events"):
            start = parse_timestamp(row["start"])
            if start is None:
                continue
            starts_at = club_local_to_utc(start.date(), start.time())
            # Same title on the same Kansas day = the same event, even if the time was corrected since.
            day_start, day_end = club_local_to_utc(start.date(), time.min), club_local_to_utc(start.date(), time.max)
            if self.db.scalar(select(CalendarEvent).where(CalendarEvent.title == row["title"],
                                                          CalendarEvent.starts_at.between(day_start, day_end))):
                continue
            color = (row["color"] or "").lower()
            event = CalendarEvent(
                title=row["title"], starts_at=starts_at, category="match" if color in ("#8a1f11", "#a8291a") else "member" if color == "#2c3e1f" else "event",
                description_html=sanitize_html(row["description"]) if row["description"] else None,
                link_url=row["link_url"] if "link_url" in row.keys() else None, link_label=row["link_label"] if "link_label" in row.keys() else None,
                recurrence_label=row["recurrence_label"] if "recurrence_label" in row.keys() else None,
            )
            if "image_r2_key" in row.keys() and row["image_r2_key"] and (stored := self.store(row["image_r2_key"], "public/calendar")):
                event.image_key, event.image_mime, event.image_filename = stored[0], stored[1], row["image_file_name"]
            if "document_r2_key" in row.keys() and row["document_r2_key"] and (stored := self.store(row["document_r2_key"], "public/calendar")):
                event.document_key, event.document_filename = stored[0], row["document_file_name"]
            self.db.add(event)
            self.counts["calendar events imported"] += 1

    def import_content(self) -> None:
        for row in self.rows("page_sections"):
            slug = "membership" if row["page_slug"] == "agreement" else row["page_slug"]
            section = self.db.scalar(select(PageSection).where(PageSection.page_slug == slug, PageSection.section_key == row["section_key"]))
            if section is None:
                if not row["section_key"].startswith("custom-"):
                    continue
                section = PageSection(page_slug=slug, section_key=row["section_key"], label="Imported section", is_custom=True, sort_order=900)
                self.db.add(section)
            section.heading = row["heading"]
            section.body_html = sanitize_html(row["body_html"])
            self.counts["page sections updated"] += 1
        for row in self.rows("site_images"):
            key = IMAGE_KEYS.get(row["key"])
            if key and self.db.get(SiteImage, key) is None and (stored := self.store(row["r2_key"], f"public/site-images/{key}")):
                self.db.add(SiteImage(key=key, storage_key=stored[0], original_filename=row["file_name"], mime_type=stored[1]))
                self.counts["site images imported"] += 1


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sqlite_file", type=Path)
    parser.add_argument("--r2-dir", type=Path, help="Local copy of the kiowa-gun R2 bucket")
    parser.add_argument("--matches-year", type=int, default=date.today().year, help='Year for match dates stored as "March 14th"')
    parser.add_argument("--include-content", action="store_true", help="Overwrite page text with the old site's page sections")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be imported, then roll back")
    args = parser.parse_args(argv[1:])

    source = sqlite3.connect(args.sqlite_file)
    source.row_factory = sqlite3.Row
    with get_sessionmaker()() as db:
        importer = Importer(source, db, args.r2_dir, args.dry_run)
        importer.import_members()
        importer.import_board()
        importer.import_payments()
        importer.import_documents()
        importer.import_matches(args.matches_year)
        importer.import_calendar()
        if args.include_content:
            importer.import_content()
        if args.dry_run:
            db.rollback()
        else:
            db.commit()
    for label, count in sorted(importer.counts.items()):
        print(f"{label}: {count}")
    print("DRY RUN - nothing was saved." if args.dry_run else "Import complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
