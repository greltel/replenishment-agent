"""
Demand forecasting utilities.

Three methods provided:
  1. simple_average — flat average over history (baseline)
  2. moving_average — N-period moving average
  3. exponential_smoothing — single exponential smoothing (Holt's level)

For PoC we keep these simple and explainable. ML-based forecasting can be
added later as a drop-in replacement.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Sequence

import numpy as np
import pandas as pd


# ============================================================
# Helpers
# ============================================================
def consumption_to_daily_series(
    movements: Sequence,
    horizon_back_days: int = 365,
) -> pd.Series:
    """
    Convert a list of Movement objects (with .posting_date and .quantity)
    into a daily-indexed Series of consumption quantities (positive numbers).
    Missing days get zero.
    """
    if not movements:
        return pd.Series(dtype=float)

    df = pd.DataFrame([
        {"date": m.posting_date, "qty": abs(m.quantity)}
        for m in movements
    ])

    daily = df.groupby("date")["qty"].sum()
    daily.index = pd.to_datetime(daily.index)

    # Reindex to a continuous daily range
    end = daily.index.max()
    start = end - pd.Timedelta(days=horizon_back_days)
    full_range = pd.date_range(start=start, end=end, freq="D")
    daily = daily.reindex(full_range, fill_value=0.0)

    return daily


# ============================================================
# Forecasting methods
# ============================================================
def simple_average(history: pd.Series, horizon_days: int) -> list[float]:
    """Flat-line forecast at the historical average."""
    if len(history) == 0:
        return [0.0] * horizon_days
    avg = float(history.mean())
    return [avg] * horizon_days


def moving_average(
    history: pd.Series,
    horizon_days: int,
    window: int = 30,
) -> list[float]:
    """N-day moving average — uses the last `window` days to project forward."""
    if len(history) == 0:
        return [0.0] * horizon_days
    window = min(window, len(history))
    recent_avg = float(history.tail(window).mean())
    return [recent_avg] * horizon_days


def exponential_smoothing(
    history: pd.Series,
    horizon_days: int,
    alpha: float = 0.3,
) -> list[float]:
    """
    Single exponential smoothing.
    alpha in (0, 1) — higher = more weight on recent observations.
    """
    if len(history) == 0:
        return [0.0] * horizon_days

    values = history.values
    level = float(values[0])
    for v in values[1:]:
        level = alpha * float(v) + (1 - alpha) * level

    return [level] * horizon_days


def forecast(
    movements: Sequence,
    horizon_days: int,
    method: str = "moving_average",
    **kwargs,
) -> list[float]:
    """
    Convenience dispatcher.

    Parameters
    ----------
    movements : list of Movement objects (from DB)
    horizon_days : how many days ahead to forecast
    method : 'simple_average' | 'moving_average' | 'exponential_smoothing'
    """
    history = consumption_to_daily_series(movements)

    if method == "simple_average":
        return simple_average(history, horizon_days)
    elif method == "moving_average":
        return moving_average(history, horizon_days, **kwargs)
    elif method == "exponential_smoothing":
        return exponential_smoothing(history, horizon_days, **kwargs)
    else:
        raise ValueError(f"Unknown forecasting method: {method}")


def annual_demand(movements: Sequence) -> float:
    """Estimated annual consumption (used by EOQ)."""
    history = consumption_to_daily_series(movements, horizon_back_days=365)
    if len(history) == 0:
        return 0.0
    daily_avg = float(history.mean())
    return daily_avg * 365.0
