"""
Calendar utilities — handles workdays, weekends, and Greek public holidays.
Used by the rules engine to shift order release dates to valid working days.
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache


# Fixed-date Greek public holidays (the year is appended dynamically)
FIXED_HOLIDAYS = [
    (1, 1),   # New Year
    (1, 6),   # Epiphany (Theofania)
    (3, 25),  # Independence Day
    (5, 1),   # Labour Day
    (8, 15),  # Assumption (Dekapentavgoustos)
    (10, 28), # Ohi Day
    (12, 25), # Christmas
    (12, 26), # Boxing Day (Synaxis Theotokou)
]


def _orthodox_easter(year: int) -> date:
    """Compute Orthodox (Julian) Easter date — Meeus algorithm."""
    a = year % 4
    b = year % 7
    c = year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month = (d + e + 114) // 31
    day = ((d + e + 114) % 31) + 1
    # Convert from Julian to Gregorian (add 13 days for 20th-21st century)
    julian_easter = date(year, month, day)
    return julian_easter + timedelta(days=13)


@lru_cache(maxsize=32)
def greek_holidays(year: int) -> set[date]:
    """Return all Greek public holidays for a given year."""
    holidays = {date(year, m, d) for m, d in FIXED_HOLIDAYS}

    # Orthodox movable feasts (anchored on Easter Sunday)
    easter = _orthodox_easter(year)
    holidays.add(easter - timedelta(days=48))   # Clean Monday (Kathara Deftera)
    holidays.add(easter - timedelta(days=2))    # Good Friday (M. Paraskevi)
    holidays.add(easter)                        # Easter Sunday
    holidays.add(easter + timedelta(days=1))    # Easter Monday
    holidays.add(easter + timedelta(days=50))   # Holy Spirit Day (Agiou Pneumatos)

    return holidays


def is_workday(d: date) -> bool:
    """True if d is Mon-Fri AND not a Greek holiday."""
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    if d in greek_holidays(d.year):
        return False
    return True


def next_workday(d: date) -> date:
    """Return the next valid working day on or after d."""
    while not is_workday(d):
        d += timedelta(days=1)
    return d


def previous_workday(d: date) -> date:
    """Return the previous valid working day on or before d."""
    while not is_workday(d):
        d -= timedelta(days=1)
    return d


def workdays_between(start: date, end: date) -> int:
    """Count working days between start and end (both inclusive)."""
    if start > end:
        return 0
    count = 0
    current = start
    while current <= end:
        if is_workday(current):
            count += 1
        current += timedelta(days=1)
    return count


def add_workdays(d: date, n: int) -> date:
    """Add n working days to d (positive or negative)."""
    if n == 0:
        return next_workday(d)
    step = 1 if n > 0 else -1
    remaining = abs(n)
    current = d
    while remaining > 0:
        current += timedelta(days=step)
        if is_workday(current):
            remaining -= 1
    return current
