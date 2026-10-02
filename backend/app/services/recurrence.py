"""Monthly "nth weekday" recurrence (ported from kiowa-gun lib/recurrence.ts).

A series such as "2nd Saturday of every month" is expanded into individual,
editable event rows that share a series id.
"""

from __future__ import annotations

import calendar
from datetime import date

# 0 = Sunday .. 6 = Saturday (matches kiowa-gun and JavaScript's getDay()).
WEEKDAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
ORDINALS = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "last"}
LAST = 5


def _python_weekday(weekday: int) -> int:
    # Python: Monday = 0 .. Sunday = 6
    return (weekday - 1) % 7


def nth_weekday_of_month(year: int, month: int, weekday: int, nth: int) -> date | None:
    """Date of the nth ``weekday`` in ``month`` (1-12); nth = 5 means the last one.
    Returns None if the month has no such day."""
    if not 0 <= weekday <= 6 or not 1 <= nth <= 5:
        raise ValueError("weekday must be 0-6 and nth 1-5")
    target = _python_weekday(weekday)
    days_in_month = calendar.monthrange(year, month)[1]
    matches = [d for d in range(1, days_in_month + 1) if date(year, month, d).weekday() == target]
    if nth == LAST:
        return date(year, month, matches[-1])
    return date(year, month, matches[nth - 1]) if nth <= len(matches) else None


def describe_recurrence(nth: int, weekday: int) -> str:
    return f"Every {ORDINALS[nth]} {WEEKDAY_NAMES[weekday]} of the month"


def series_dates(*, weekday: int, nth: int, start_year: int, start_month: int, month_count: int) -> list[date]:
    if not 1 <= month_count <= 36:
        raise ValueError("A series can cover 1 to 36 months.")
    dates: list[date] = []
    year, month = start_year, start_month
    for _ in range(month_count):
        day = nth_weekday_of_month(year, month, weekday, nth)
        if day is not None:
            dates.append(day)
        month += 1
        if month > 12:
            month, year = 1, year + 1
    return dates
