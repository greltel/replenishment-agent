"""
Effective "today" helper.

When working with historical or static datasets, the agent needs a notion
of "current date" that anchors to the dataset rather than the wall clock.
For example, if movements were extracted on 2026-01-28 but you run the
agent on 2026-05-09, the agent should treat 2026-01-28 as "today" so:

  • dead-stock thresholds are not triggered by stale data
  • forecast windows align with available history
  • backtest scenarios are reproducible

Configuration (env var AS_OF_DATE or src.config.config.as_of_date):
  • '' or unset    → use real today (wall clock)
  • 'YYYY-MM-DD'   → use this fixed date
  • 'auto'         → infer from latest movement date in DB

The 'auto' mode caches the result on first call.
"""
from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache

from src.config import config
from src.utils.logger import log


def _parse_iso(s: str) -> date | None:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None


@lru_cache(maxsize=1)
def _resolve_auto() -> date:
    """Look up the latest movement date in the DB once, then cache it."""
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(config.database_url)
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT MAX(posting_date) FROM movements"
            )).first()
            if row and row[0]:
                value = row[0]
                if isinstance(value, str):
                    parsed = _parse_iso(value)
                    if parsed:
                        log.info(f"as-of date resolved (auto): {parsed}")
                        return parsed
                if isinstance(value, date):
                    log.info(f"as-of date resolved (auto): {value}")
                    return value
    except Exception as e:
        log.warning(f"Could not auto-resolve as-of date: {e}")

    today = date.today()
    log.info(f"as-of date falls back to wall clock: {today}")
    return today


def get_effective_today() -> date:
    """Returns the effective "today" used by the agent.

    Resolution priority:
      1. config.as_of_date is a valid 'YYYY-MM-DD' string → use it
      2. config.as_of_date is 'auto' → infer from DB
      3. Otherwise → real today
    """
    setting = (config.as_of_date or "").strip().lower()

    if not setting:
        return date.today()

    if setting == "auto":
        return _resolve_auto()

    parsed = _parse_iso(setting)
    if parsed:
        return parsed

    log.warning(
        f"AS_OF_DATE='{config.as_of_date}' is not a valid date or 'auto'. "
        f"Falling back to wall clock."
    )
    return date.today()


def reset_cache() -> None:
    """Clear the auto-resolution cache (useful in tests)."""
    _resolve_auto.cache_clear()
