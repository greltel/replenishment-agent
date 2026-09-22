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


def _coerce_date(value) -> date | None:
    """SQLite returns DATE columns as 'YYYY-MM-DD' strings via raw SQL."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return _parse_iso(str(value))


@lru_cache(maxsize=1)
def _resolve_auto() -> date:
    """Infer "today" from the dataset once, then cache it.

    The effective date is the LATEST of:
      • the most recent stock snapshot date (MARD extraction date), and
      • the most recent movement posting date (MB51).

    Using only the movement date is wrong whenever the stock snapshot was
    taken after the last posted movement (the normal case: the snapshot is
    taken at extraction time, movements are posted during the day). In that
    situation `get_current_stock(as_of=<movement date>)` finds no snapshot
    and reports zero stock for every material — which in turn makes every
    proposal look critical (R-EXPEDITE fires for all of them).
    """
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(config.database_url)
        candidates: list[date] = []
        with engine.connect() as conn:
            for sql in (
                "SELECT MAX(snapshot_date) FROM stock",
                "SELECT MAX(posting_date) FROM movements",
            ):
                try:
                    row = conn.execute(text(sql)).first()
                except Exception:
                    continue
                parsed = _coerce_date(row[0]) if row else None
                if parsed:
                    candidates.append(parsed)
        if candidates:
            resolved = max(candidates)
            log.info(f"as-of date resolved (auto): {resolved}")
            return resolved
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
