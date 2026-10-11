"""Bring the people table in line with a cleaned club roster.

    python -m scripts.sync_roster roster.csv            # dry run: prints every change, saves nothing
    python -m scripts.sync_roster roster.csv --apply    # makes the changes

The roster is a CSV in the board import's format (see app/services/roster_import.py),
optionally with an ``original_email`` column holding an address as it was
mistyped on an earlier roster, so a person imported with the typo is still found.

What it does, in order:

1. Tidies every person already on file: stray spaces, state in capitals,
   phone as (620) 555-0100, email in lower case.
2. Matches each roster row to the people on file by email, NRA number, name
   and phone, or (when only one person has it) name alone.
   - No match: the person is added as a member.
   - One match: their record is corrected from the roster. Someone with an
     online account keeps what they entered; only their blanks are filled.
   - Several matches: they are duplicates. Records with nothing attached (no
     account, applications, payments or documents) are folded into the one
     that has, or the oldest; any other duplicate is reported, not touched.
3. Reports, without changing them, possible duplicates the roster didn't
   settle and members on file who are not on the roster.

It is safe to run more than once.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_sessionmaker
from app.models import Application, Document, Payment, Person
from app.schemas.common import _phone as normalize_phone
from app.services import audit, membership, roster_import

ROSTER_FIELDS = ("first_name", "last_name", "email", "phone", "address_line1", "city", "state", "zip_code",
                 "nra_number", "nra_expiration_date", "nra_life_member")


def _letters(*parts: str | None) -> str:
    return re.sub(r"[^a-z]", "", "".join(p or "" for p in parts).lower())


def _name_key(first: str | None, last: str | None) -> tuple[str, str]:
    return _letters(first), _letters(last)


def _digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")[-10:]


def _phone(value: str | None) -> str | None:
    try:
        return normalize_phone(value) if value else None
    except ValueError:
        return value


def _label(person: Person) -> str:
    return f"#{person.id} {person.full_name} <{person.email or 'no email'}>"


class Sync:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings_row = membership.site_settings(db)
        self.people: list[Person] = list(db.scalars(select(Person).order_by(Person.id)))
        self.counts: dict[str, int] = defaultdict(int)
        self.on_roster: set[int] = set()

    # -- 1. formatting of what is already on file ---------------------------------

    def tidy(self, person: Person) -> None:
        changes = []
        for key in ("first_name", "last_name", "address_line1", "address_line2", "city", "state", "zip_code", "email", "phone"):
            old = getattr(person, key)
            if old is None:
                continue
            new: str | None = " ".join(old.split())
            if key == "state":
                new = new.upper()
            elif key == "email":
                new = new.replace(" ", "").lower()
            elif key == "phone":
                new = _phone(new)
            if not new and key not in ("first_name", "last_name"):
                new = None
            if new != old:
                changes.append(f"{key} {old!r} -> {new!r}")
                setattr(person, key, new)
        if changes:
            self.counts["tidied"] += 1
            print(f"Tidy {_label(person)}: " + "; ".join(changes))

    # -- 2. roster rows -------------------------------------------------------------

    def attached(self, person: Person) -> list[str]:
        """What ties this record to real activity; a record with none of it can be folded into another."""
        found = []
        if person.password_hash:
            found.append("online account")
        if person.board_user is not None:
            found.append("board login")
        for model, name in ((Application, "applications"), (Payment, "payments"), (Document, "documents")):
            count = self.db.scalar(select(func.count()).select_from(model).where(model.person_id == person.id))
            if count:
                found.append(f"{count} {name}")
        return found

    def matches(self, row: dict[str, object], name_is_unique: bool) -> list[Person]:
        emails = {e for e in (row["email"], row["original_email"]) if e}
        name, phone = _name_key(row["first_name"], row["last_name"]), _digits(row["phone"])  # type: ignore[arg-type]
        found: list[Person] = []
        same_name = [p for p in self.people if _name_key(p.first_name, p.last_name) == name]
        for person in self.people:
            if ((person.email and person.email.lower() in emails)
                    or (row["nra_number"] and person.nra_number == row["nra_number"])
                    or (person in same_name and phone and _digits(person.phone) == phone)):
                found.append(person)
        if not found and name_is_unique and len(same_name) == 1 and same_name[0].id not in self.on_roster:
            other = same_name[0]
            if not (other.nra_number and row["nra_number"] and other.nra_number != row["nra_number"]):
                found.append(other)
        return found

    def fold(self, keeper: Person, extra: Person) -> None:
        print(f"  merge duplicate {_label(extra)} into {_label(keeper)}")
        filled = {}
        # Roster fields are left out: correct() fills them from the roster, not from the duplicate's copy.
        for key in ("address_line2", "member_since", "notes"):
            if getattr(keeper, key) in (None, "", False) and getattr(extra, key) not in (None, "", False):
                filled[key] = getattr(extra, key)
        if extra.sms_opt_in and not keeper.sms_opt_in:
            filled.update(sms_opt_in=True, sms_opt_in_at=extra.sms_opt_in_at, sms_opt_in_source=extra.sms_opt_in_source)
        self.people.remove(extra)
        self.db.delete(extra)
        self.db.flush()  # frees the duplicate's email and NRA number before the keeper takes them
        for key, value in filled.items():
            setattr(keeper, key, value)
        self.counts["merged"] += 1

    def correct(self, person: Person, row: dict[str, object]) -> None:
        has_account = bool(person.password_hash)
        changes, kept = [], []
        for key in ROSTER_FIELDS:
            old, new = getattr(person, key), row[key]
            if key == "nra_life_member":
                new = bool(new) or bool(old)
            if new in (None, "") or old == new:
                continue
            if key == "nra_expiration_date" and old and old > new:  # type: ignore[operator]
                continue  # the member has renewed with the NRA since the roster was typed
            if has_account and old not in (None, ""):
                kept.append(f"{key} {old!r} (roster has {new!r})")
                continue
            changes.append(f"{key} {old!r} -> {new!r}")
            setattr(person, key, new)
            if key == "phone":
                person.sms_carrier = None
            elif key == "email":
                person.email_verified_at = None
        if person.membership_status != "member":
            changes.append(f"status {person.membership_status} -> member")
            person.membership_status, person.terminated_at = "member", None
        paid_through: date | None = row["renewal_date"]  # type: ignore[assignment]
        if paid_through and (person.renewal_date is None or person.renewal_date < paid_through):
            changes.append(f"paid through {person.renewal_date} -> {paid_through}")
            person.renewal_date = paid_through
        if person.member_number is not None:
            # The roster's "Member No." restarts at 1 on every page: it is a row count, not a member number.
            changes.append(f"member_number {person.member_number} -> None")
            person.member_number = None
        for note in row["notes"]:  # type: ignore[union-attr]
            if note.lower() not in (person.notes or "").lower():
                changes.append(f"note + {note!r}")
                person.notes = f"{person.notes}\n{note}" if person.notes else note
        if changes:
            self.counts["corrected"] += 1
            print(f"Correct {_label(person)}: " + "; ".join(changes))
        if kept:
            print("  ! has an online account, so kept their own: " + "; ".join(kept))

    def roster_row(self, row: dict[str, object], name_is_unique: bool) -> None:
        found = self.matches(row, name_is_unique)
        if not found:
            person = Person(**{k: row[k] for k in ROSTER_FIELDS}, membership_status="member", renewal_date=row["renewal_date"],
                            notes="\n".join(row["notes"]) or None)  # type: ignore[arg-type]
            self.db.add(person)
            self.db.flush()
            self.people.append(person)
            self.on_roster.add(person.id)
            self.counts["added"] += 1
            print(f"Add {_label(person)}")
            return
        keeper = next((p for p in found if self.attached(p)), found[0])
        if len(found) > 1:
            print(f"Duplicates for {row['first_name']} {row['last_name']} ({row['source']}):")
        for extra in [p for p in found if p is not keeper]:
            tied = self.attached(extra)
            if tied:
                self.counts["left for you"] += 1
                print(f"  ! {_label(extra)} also matches but has {', '.join(tied)}; not merged, decide by hand")
            else:
                self.fold(keeper, extra)
        self.on_roster.add(keeper.id)
        self.correct(keeper, row)
        self.db.flush()

    # -- 3. report only -------------------------------------------------------------

    def report_leftovers(self) -> None:
        groups: dict[tuple[str, object], list[Person]] = defaultdict(list)
        for person in self.people:
            groups["name", _name_key(person.first_name, person.last_name)].append(person)
            if _digits(person.phone):
                groups["phone", _digits(person.phone)].append(person)
        seen: set[frozenset[int]] = set()
        for (kind, _), members in groups.items():
            ids = frozenset(p.id for p in members)
            if len(members) < 2 or ids in seen or ids <= self.on_roster:
                continue  # two roster members sharing a name or a phone are different people
            seen.add(ids)
            self.counts["possible duplicates"] += 1
            print(f"Possible duplicate (same {kind}), not changed: " + " | ".join(
                f"{_label(p)} [{p.membership_status}{', ' + ', '.join(self.attached(p)) if self.attached(p) else ''}]" for p in members))
        for person in self.people:
            if person.membership_status == "member" and person.id not in self.on_roster:
                self.counts["members not on roster"] += 1
                print(f"Member not on the roster, not changed: {_label(person)}, paid through {person.renewal_date}")


def load_roster(db: Session, path: str) -> list[dict[str, object]]:
    settings_row = membership.site_settings(db)
    with open(path, newline="", encoding="utf-8-sig") as handle:
        text = handle.read()
    rows = []
    for raw in roster_import.read_rows(text):
        expiration, life = roster_import.nra_expiration(raw.get("nra_expiration"))
        rows.append({
            "source": raw.get("source") or f"line {raw.line}",
            "first_name": raw.get("first_name"), "last_name": raw.get("last_name"),
            "email": raw.get("email").lower() or None, "original_email": raw.get("original_email").lower() or None,
            "phone": _phone(raw.get("phone")), "address_line1": raw.get("address_line1") or None,
            "city": raw.get("city") or None, "state": raw.get("state").upper() or None, "zip_code": raw.get("zip_code") or None,
            "nra_number": raw.get("nra_number") or None, "nra_expiration_date": expiration, "nra_life_member": life,
            "renewal_date": roster_import.paid_through(settings_row, raw),
            "notes": [n.strip() for n in raw.get("notes").split(";") if n.strip()],
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Bring the people table in line with a cleaned club roster.")
    parser.add_argument("roster", help="cleaned roster CSV")
    parser.add_argument("--apply", action="store_true", help="save the changes (default: dry run)")
    args = parser.parse_args()

    with get_sessionmaker()() as db:
        rows = load_roster(db, args.roster)
        sync = Sync(db)
        print(f"{len(rows)} people on the roster, {len(sync.people)} on file.\n")
        for person in sync.people:
            sync.tidy(person)
        db.flush()
        names: dict[tuple[str, str], int] = defaultdict(int)
        for row in rows:
            names[_name_key(row["first_name"], row["last_name"])] += 1  # type: ignore[arg-type]
        for row in rows:
            sync.roster_row(row, names[_name_key(row["first_name"], row["last_name"])] == 1)  # type: ignore[arg-type]
        sync.report_leftovers()

        print("\n" + ", ".join(f"{count} {what}" for what, count in sync.counts.items()) or "\nNothing to do.")
        if not args.apply:
            db.rollback()
            print("Dry run: nothing was saved. Re-run with --apply to make these changes.")
            return 0
        audit.record(db, actor=None, action="person.roster_sync", entity_type="person",
                     summary=f"Roster sync from {len(rows)} roster rows", details=dict(sync.counts))
        db.commit()
        print("Saved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
