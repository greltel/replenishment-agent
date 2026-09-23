"""
Demand forecasting utilities.

Three methods provided:
  1. simple_average — flat average over history (baseline)
  2. moving_average — N-period moving average
  3. exponential_smoothing — single exponential smoothing (Holt's level)

plus "auto": the method with the lowest walk-forward WMAPE per material
(see select_method). The agent's default stays the moving average: on the
importer dataset the automatic choice was marginally worse on the main
window and clearly worse on winter windows with a short, pre-season history
(thesis §4.9) — a reactive method is the robust choice until seasonal
models (Croston/SBA, seasonal smoothing) are added.

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
    as_of: date | None = None,
) -> pd.Series:
    """
    Convert a list of Movement objects (with .posting_date and .quantity)
    into a daily-indexed Series of consumption quantities (positive numbers).
    Missing days get zero.

    Parameters
    ----------
    as_of : optional anchor for the END of the series ("today"). When given,
        the series always ends on `as_of`, so a material whose last movement
        was 100 days ago correctly shows 100 trailing days of zero demand
        (and a 30-day moving average of ~0). When omitted, the series ends on
        the last movement date (legacy behaviour, used by exploratory views).
    """
    if not movements:
        return pd.Series(dtype=float)

    df = pd.DataFrame([
        {"date": m.posting_date, "qty": abs(m.quantity)}
        for m in movements
    ])

    daily = df.groupby("date")["qty"].sum()
    daily.index = pd.to_datetime(daily.index)

    # Reindex to a continuous daily range ending at the anchor date
    end = pd.Timestamp(as_of) if as_of is not None else daily.index.max()
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


AUTO_MIN_WEEKS = 12          # weeks of history needed before "auto" trusts the validation


def select_method(history: pd.Series) -> str:
    """Pick the forecasting method for ONE material by walk-forward validation.

    The daily history is aggregated to weekly buckets (the level at which the
    weekly review uses the forecast) and the three methods are compared with
    rolling-origin validation — 5 folds, train 8 weeks → test 2 weeks, the
    same setting as the dashboard's "Πρόβλεψη ζήτησης" tab — on WMAPE
    (Syntetos & Boylan 2005). Only the history handed in is used, so a
    backtest that passes movements ≤ t stays free of look-ahead bias.

    Falls back to the moving average when the history is too short
    (< AUTO_MIN_WEEKS weeks) or carries no demand.
    """
    if history is None or len(history) == 0:
        return "moving_average"
    nonzero = history[history > 0]
    if nonzero.empty:
        return "moving_average"
    weekly = history[history.index >= nonzero.index[0]].resample("W").sum()
    if len(weekly) < AUTO_MIN_WEEKS or float(weekly.sum()) <= 0:
        return "moving_average"
    # As many 2-week folds as the history allows (up to 20 = 40 weeks), so
    # that the choice reflects the whole year — a selection made on the last
    # ten weeks alone is fooled by seasonality.
    n_folds = max(3, min(20, (len(weekly) - 8) // 2))
    comparison = compare_methods(
        weekly, train_window=8, test_window=2, n_folds=n_folds,
        method_kwargs={"moving_average": {"window": 4}},
    )
    return best_method(comparison, metric="wmape")


def forecast(
    movements: Sequence,
    horizon_days: int,
    method: str = "moving_average",
    as_of: date | None = None,
    **kwargs,
) -> list[float]:
    """
    Convenience dispatcher.

    Parameters
    ----------
    movements : list of Movement objects (from DB)
    horizon_days : how many days ahead to forecast
    method : 'simple_average' | 'moving_average' | 'exponential_smoothing'
             | 'auto' (best of the three per material by walk-forward WMAPE,
             see select_method)
    as_of : anchor date for the history (see consumption_to_daily_series)
    """
    history = consumption_to_daily_series(movements, as_of=as_of)

    if method == "auto":
        method = select_method(history)

    if method == "simple_average":
        return simple_average(history, horizon_days)
    elif method == "moving_average":
        return moving_average(history, horizon_days, **kwargs)
    elif method == "exponential_smoothing":
        return exponential_smoothing(history, horizon_days, **kwargs)
    else:
        raise ValueError(f"Unknown forecasting method: {method}")


def annual_demand(movements: Sequence, as_of: date | None = None) -> float:
    """Estimated annual consumption (used by EOQ)."""
    history = consumption_to_daily_series(movements, horizon_back_days=365, as_of=as_of)
    if len(history) == 0:
        return 0.0
    daily_avg = float(history.mean())
    return daily_avg * 365.0


# ============================================================
# Accuracy metrics
# ============================================================
def mean_absolute_error(actual: Sequence[float], predicted: Sequence[float]) -> float:
    """MAE — average absolute deviation. Same units as the data."""
    if len(actual) == 0 or len(actual) != len(predicted):
        return 0.0
    return float(np.mean(np.abs(np.array(actual) - np.array(predicted))))


def root_mean_squared_error(actual: Sequence[float], predicted: Sequence[float]) -> float:
    """RMSE — penalizes large errors more than MAE."""
    if len(actual) == 0 or len(actual) != len(predicted):
        return 0.0
    return float(np.sqrt(np.mean((np.array(actual) - np.array(predicted)) ** 2)))


def mean_absolute_percentage_error(
    actual: Sequence[float], predicted: Sequence[float]
) -> float:
    """MAPE — percentage error. Returns 0 for zero-demand days to avoid div-by-zero."""
    if len(actual) == 0 or len(actual) != len(predicted):
        return 0.0
    a = np.array(actual, dtype=float)
    p = np.array(predicted, dtype=float)
    nonzero = a != 0
    if nonzero.sum() == 0:
        return 0.0
    return float(np.mean(np.abs((a[nonzero] - p[nonzero]) / a[nonzero])) * 100)


def bias(actual: Sequence[float], predicted: Sequence[float]) -> float:
    """Mean signed error. Positive = over-forecasting; negative = under-forecasting."""
    if len(actual) == 0 or len(actual) != len(predicted):
        return 0.0
    return float(np.mean(np.array(predicted) - np.array(actual)))


# ============================================================
# Walk-forward validation
# ============================================================
def walk_forward_evaluate(
    history: pd.Series,
    method: str,
    train_window: int = 60,
    test_window: int = 14,
    n_folds: int = 5,
    **kwargs,
) -> dict:
    """
    Walk-forward validation: train on past N days, predict next M, measure error.
    Repeat for n_folds shifted by `test_window`.

    Reference: Bergmeir & Benítez (2012) "On the use of cross-validation for
    time series predictor evaluation".

    Returns
    -------
    dict with MAE, RMSE, MAPE, Bias averaged across folds plus per-fold detail.
    """
    if len(history) < train_window + test_window:
        return {"mae": 0.0, "rmse": 0.0, "mape": 0.0, "wmape": 0.0, "bias": 0.0,
                "n_folds": 0, "error": "Not enough history"}

    method_fn = {
        "simple_average": simple_average,
        "moving_average": moving_average,
        "exponential_smoothing": exponential_smoothing,
    }.get(method)
    if method_fn is None:
        return {"error": f"Unknown method: {method}"}

    fold_results = []
    n = len(history)

    for fold in range(n_folds):
        # Slide backwards from the end
        test_end = n - fold * test_window
        test_start = test_end - test_window
        train_end = test_start
        train_start = max(train_end - train_window, 0)

        if train_start >= train_end or test_start >= test_end:
            break

        train = history.iloc[train_start:train_end]
        test = history.iloc[test_start:test_end]

        if len(train) == 0 or len(test) == 0:
            continue

        predicted = method_fn(train, len(test), **kwargs)
        actual = test.values.tolist()

        fold_results.append({
            "fold":   fold,
            "n_train": len(train),
            "n_test":  len(test),
            "mae":     mean_absolute_error(actual, predicted),
            "rmse":    root_mean_squared_error(actual, predicted),
            "mape":    mean_absolute_percentage_error(actual, predicted),
            "wmape":   weighted_mape(actual, predicted),
            "bias":    bias(actual, predicted),
        })

    if not fold_results:
        return {"mae": 0.0, "rmse": 0.0, "mape": 0.0, "wmape": 0.0, "bias": 0.0, "n_folds": 0}

    return {
        "mae":     float(np.mean([f["mae"] for f in fold_results])),
        "rmse":    float(np.mean([f["rmse"] for f in fold_results])),
        "mape":    float(np.mean([f["mape"] for f in fold_results])),
        "wmape":   float(np.mean([f["wmape"] for f in fold_results])),
        "bias":    float(np.mean([f["bias"] for f in fold_results])),
        "n_folds": len(fold_results),
        "folds":   fold_results,
    }


def weighted_mape(actual: Sequence[float], predicted: Sequence[float]) -> float:
    """WMAPE = Σ|a − p| / Σ|a| × 100 — the recommended accuracy measure for
    intermittent demand (Syntetos & Boylan 2005), because plain MAPE explodes
    on near-zero actuals. Returns 0 when there is no actual demand."""
    if len(actual) == 0 or len(actual) != len(predicted):
        return 0.0
    a = np.array(actual, dtype=float)
    p = np.array(predicted, dtype=float)
    denom = float(np.abs(a).sum())
    return float(np.abs(a - p).sum() / denom * 100) if denom > 0 else 0.0


def compare_methods(
    history: pd.Series,
    methods: list[str] | None = None,
    train_window: int = 60,
    test_window: int = 14,
    n_folds: int = 5,
    method_kwargs: dict[str, dict] | None = None,
) -> pd.DataFrame:
    """
    Run walk-forward validation for multiple methods and return a comparison.

    method_kwargs: optional per-method keyword arguments, e.g.
        {"moving_average": {"window": 4}} when `history` is a weekly series.

    Returns
    -------
    DataFrame indexed by method with columns
    [mae, rmse, mape, wmape, bias, n_folds].
    """
    methods = methods or ["simple_average", "moving_average", "exponential_smoothing"]
    method_kwargs = method_kwargs or {}
    rows = []
    for m in methods:
        result = walk_forward_evaluate(
            history, m, train_window, test_window, n_folds, **method_kwargs.get(m, {}),
        )
        rows.append({
            "method":  m,
            "mae":     round(result.get("mae", 0), 2),
            "rmse":    round(result.get("rmse", 0), 2),
            "mape":    round(result.get("mape", 0), 2),
            "wmape":   round(result.get("wmape", 0), 2),
            "bias":    round(result.get("bias", 0), 2),
            "n_folds": result.get("n_folds", 0),
        })
    return pd.DataFrame(rows)


def best_method(comparison: pd.DataFrame, metric: str = "mape") -> str:
    """Pick the best method by lowest error metric."""
    if comparison.empty:
        return "moving_average"
    valid = comparison[comparison["n_folds"] > 0]
    if valid.empty:
        return "moving_average"
    return valid.loc[valid[metric].idxmin(), "method"]
