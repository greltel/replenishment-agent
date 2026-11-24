"""
Time phasing utilities — applies lead-time offsets and calendar adjustments
to planned orders. Most of the logic is integrated directly in MRPEngine,
but isolating it here allows future expansion (multi-stage BOMs, etc.).
"""
from __future__ import annotations

from datetime import date, timedelta

from src.utils.calendar_utils import previous_workday


def offset_release_date(
    receipt_date: date,
    lead_time_days: int,
    today: date | None = None,
    workday_only: bool = True,
) -> date:
    """
    Compute the planned-release date given a target receipt date and lead time.

    If `workday_only=True`, the result is shifted backward to the previous
    working day if it falls on a weekend / public holiday.
    """
    today = today or date.today()
    release = receipt_date - timedelta(days=lead_time_days)

    if release < today:
        release = today

    if workday_only:
        release = previous_workday(release)

    return release
