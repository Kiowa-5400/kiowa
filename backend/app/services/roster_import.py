"""Reading contact spreadsheets for the board's CSV import.

Accepts both the app's own template (first_name, last_name, email, ...) and
the club's roster workbook saved as CSV ("Last Name", "FirstName", "Mailing
Address", "Dues Due", "NRA Exp.", ...), which has a title above the header
row and blank rows after the last member.
"""

from __future__ import annotations

import calendar
import csv
import io
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime

from app.models import SiteSettings
from app.services import renewal

# Header text is compared with case, spaces and punctuation removed.
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "first_name": ("firstname", "first"),
    "last_name": ("lastname", "last"),
    "name": ("name", "fullname"),
    "email": ("email", "emailaddress"),
    "phone": ("phone", "phonenumber", "mobile", "mobilephone", "cell", "cellphone"),
    "address_line1": ("address", "addressline1", "mailingaddress", "street", "streetaddress"),
    "address_line2": ("addressline2",),
    "city": ("city", "town"),
    "state": ("state",),
    "zip_code": ("zip", "zipcode", "postalcode"),
    "member_number": ("memberno", "membernumber", "member"),
    "renewal_date": ("renewaldate", "paidthrough", "duespaidthrough"),
    "dues_due": ("duesdue",),
    "dues_paid": ("currentduespaid", "duespaid"),
    "nra_number": ("nrano", "nranumber", "nra"),
    "nra_expiration": ("nraexp", "nraexpiration", "nraexpirationdate", "nraexpires"),
    "rules": ("rulesyn", "rules"),
    "card": ("cardyn", "card"),
    "notes": ("notes", "note", "comments", "remarks"),
}
_FIELD_BY_HEADER = {alias: name for name, aliases in COLUMN_ALIASES.items() for alias in aliases}
_HEADER_SEARCH_ROWS = 25
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_MONTHS = {name.lower(): number for names in (calendar.month_abbr, calendar.month_name)
           for number, name in enumerate(names) if name}
_MONTHS["sept"] = 9


def _key(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", header.lower())


def _has_text(value: str) -> bool:
    return any(ch.isalnum() for ch in value)


@dataclass
class RosterRow:
    line: int
    values: dict[str, str]
    # Text from columns with no heading; the roster keeps remarks there.
    remarks: list[str] = field(default_factory=list)

    def get(self, name: str) -> str:
        return self.values.get(name, "")


def read_rows(text: str) -> Iterator[RosterRow]:
    """Yields one row per person, skipping the title and blank rows.
    Raises ValueError when no usable header row is found."""
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    columns: list[str | None] | None = None
    for cells in reader:
        if columns is None:
            found = [_FIELD_BY_HEADER.get(_key(c)) if _key(c) else "" for c in cells]
            if "email" in found and ("name" in found or {"first_name", "last_name"} <= set(found)):
                columns = found
            elif reader.line_num >= _HEADER_SEARCH_ROWS:
                break
            continue
        if not any(_has_text(c) for c in cells):
            continue
        row = RosterRow(line=reader.line_num, values={})
        for column, cell in zip(columns, cells, strict=False):
            cell = cell.strip()
            if column == "" and _has_text(cell):
                row.remarks.append(cell)
            elif column and cell:
                row.values.setdefault(column, cell)
        yield row
    if columns is None:
        raise ValueError('The header row needs "email" plus "first_name" and "last_name" (or "name").')


def is_email(value: str) -> bool:
    return _EMAIL.fullmatch(value) is not None


def _parse_date(value: str) -> date | tuple[int, int] | None:
    """A full date, or (year, month) for the roster's month-and-year cells.

    Excel shows "Aug-27" as "27-Aug" once it has read it as a date, so both
    orders mean August 2027: the number is always the year."""
    value = value.strip()
    for pattern in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            pass
    match = re.fullmatch(r"([A-Za-z]{3,9})\.?[-/ ]+(\d{2}|\d{4})", value) or re.fullmatch(r"(\d{2}|\d{4})[-/ ]+([A-Za-z]{3,9})\.?", value)
    if match:
        word, number = sorted(match.groups(), key=str.isdigit)
        month = _MONTHS.get(word.lower())
        if month:
            return (int(number) + (2000 if len(number) == 2 else 0), month)
    match = re.fullmatch(r"(\d{1,2})/(\d{4})", value)
    if match and 1 <= int(match.group(1)) <= 12:
        return (int(match.group(2)), int(match.group(1)))
    return None


def nra_expiration(value: str) -> tuple[date | None, bool]:
    """(expiration date, life member). A month and year means the end of that month.
    Raises ValueError for text that is neither a date nor "Life"."""
    if not value:
        return None, False
    if value.strip().lower() in ("life", "lifetime", "life member"):
        return None, True
    parsed = _parse_date(value)
    if parsed is None:
        raise ValueError(f'NRA expiration "{value}" is not a date')
    if isinstance(parsed, date):
        return parsed, False
    year, month = parsed
    return date(year, month, calendar.monthrange(year, month)[1]), False


def paid_through(settings_row: SiteSettings, row: RosterRow) -> date | None:
    """The dues cutoff this row has paid through (see services/renewal.py).

    "Dues Due" names when the next dues are owed, so the member has paid
    through the cutoff before that one. Raises ValueError for unreadable dates."""
    if row.get("renewal_date"):
        parsed = _parse_date(row.get("renewal_date"))
        if not isinstance(parsed, date):
            raise ValueError(f'paid-through date "{row.get("renewal_date")}" is not a date')
        return parsed
    if row.get("dues_due"):
        parsed = _parse_date(row.get("dues_due"))
        if parsed is None:
            raise ValueError(f'dues due "{row.get("dues_due")}" is not a date')
        due = parsed if isinstance(parsed, date) else date(parsed[0], parsed[1], 1)
        return renewal.cutoff_date(settings_row, renewal.current_cycle_cutoff(settings_row, due).year - 1)
    if row.get("dues_paid"):
        parsed = _parse_date(row.get("dues_paid"))
        if not isinstance(parsed, date):
            raise ValueError(f'dues paid date "{row.get("dues_paid")}" is not a date')
        return renewal.next_cutoff_after_payment(settings_row, None, parsed)
    return None
