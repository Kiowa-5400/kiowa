"""Club-local (Kansas, America/Chicago) date and time handling.

Board members enter calendar times as Kansas wall-clock times. They are stored
as timezone-aware UTC instants and always converted back through the club
zone, so neither the server's nor the browser's timezone can shift them.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from functools import lru_cache
from zoneinfo import ZoneInfo

from app.core.config import get_settings


@lru_cache(maxsize=1)
def club_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().club_timezone)


def now_utc() -> datetime:
    return datetime.now(UTC)


def club_today() -> date:
    return now_utc().astimezone(club_tz()).date()


def club_local_to_utc(day: date, at: time) -> datetime:
    return datetime.combine(day, at, tzinfo=club_tz()).astimezone(UTC)


def to_club_local(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(club_tz())


def format_long_date(day: date) -> str:
    return f"{day.strftime('%B')} {day.day}, {day.year}"


def format_time(at: time) -> str:
    hour = at.hour % 12 or 12
    suffix = "AM" if at.hour < 12 else "PM"
    return f"{hour}:{at.minute:02d} {suffix}"
