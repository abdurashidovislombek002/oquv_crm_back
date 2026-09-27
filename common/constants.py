"""Project-wide constants (weekday helpers etc.)."""
from __future__ import annotations

from datetime import date, time, timedelta
from typing import Optional

#: Django ``date.weekday()`` -> human readable (Uzbek)
WEEKDAY_NAMES = {
    0: "Dushanba",
    1: "Seshanba",
    2: "Chorshanba",
    3: "Payshanba",
    4: "Juma",
    5: "Shanba",
    6: "Yakshanba",
}

WEEKDAY_SHORT_NAMES = {
    0: "Du",
    1: "Se",
    2: "Ch",
    3: "Pa",
    4: "Ju",
    5: "Sh",
    6: "Ya",
}

#: 1 = Monday ... 7 = Sunday (used by the schedule API)
WEEKDAY_CHOICES = (
    (1, "Dushanba"),
    (2, "Seshanba"),
    (3, "Chorshanba"),
    (4, "Payshanba"),
    (5, "Juma"),
    (6, "Shanba"),
    (7, "Yakshanba"),
)


def weekday_to_iso(weekday: int) -> int:
    """Convert ``date.weekday()`` (0=Monday) to ISO numbering (1=Monday)."""
    return weekday + 1


def iso_to_weekday(iso_weekday: int) -> int:
    """Convert ISO numbering (1=Monday) to ``date.weekday()`` (0=Monday)."""
    return iso_weekday - 1


def month_start(value: Optional[date] = None) -> date:
    """First day of the month for ``value`` (default: today)."""
    value = value or date.today()
    return value.replace(day=1)


def add_months(value: date, months: int) -> date:
    """Add ``months`` calendar months keeping the day-of-month (clamped)."""
    if months == 0:
        return value
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, _days_in_month(year, month))
    return date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - timedelta(days=1)).day


def month_end(value: date) -> date:
    return date(value.year, value.month, _days_in_month(value.year, value.month))


def next_weekday(value: date, iso_weekday: int) -> date:
    delta = (iso_to_weekday(iso_weekday) - value.weekday()) % 7
    return value + timedelta(days=delta)


def format_phone(raw: str) -> str:
    """Normalise a phone number: keep digits and a leading ``+``."""
    if not raw:
        return ""
    cleaned = "".join(ch for ch in raw if ch.isdigit() or ch == "+")
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    return cleaned


def time_to_minutes(value: Optional[time]) -> Optional[int]:
    if value is None:
        return None
    return value.hour * 60 + value.minute
