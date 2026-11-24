"""Tests for the forecasting accuracy module and walk-forward validation."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.utils.forecasting import (
    mean_absolute_error, root_mean_squared_error,
    mean_absolute_percentage_error, bias,
    walk_forward_evaluate, compare_methods, best_method,
    simple_average, moving_average, exponential_smoothing,
)


# ============================================================
# Accuracy metrics
# ============================================================
class TestAccuracyMetrics:
    def test_mae_perfect_prediction(self):
        actual = [10, 20, 30]
        predicted = [10, 20, 30]
        assert mean_absolute_error(actual, predicted) == 0.0

    def test_mae_known_error(self):
        actual = [10, 20, 30]
        predicted = [12, 18, 33]
        # |10-12| + |20-18| + |30-33| = 2 + 2 + 3 = 7, divided by 3 = 2.33
        assert abs(mean_absolute_error(actual, predicted) - 7/3) < 0.001

    def test_mae_empty_returns_zero(self):
        assert mean_absolute_error([], []) == 0.0

    def test_mae_mismatched_lengths_returns_zero(self):
        """Mismatched array sizes return 0 (defensive)."""
        assert mean_absolute_error([1, 2, 3], [1, 2]) == 0.0

    def test_rmse_perfect(self):
        assert root_mean_squared_error([5, 5, 5], [5, 5, 5]) == 0.0

    def test_rmse_penalizes_large_errors(self):
        """RMSE > MAE when errors are uneven (penalizes outliers)."""
        actual = [10, 10, 10]
        predicted = [10, 10, 20]   # One big error
        mae = mean_absolute_error(actual, predicted)
        rmse = root_mean_squared_error(actual, predicted)
        assert rmse > mae

    def test_mape_perfect(self):
        assert mean_absolute_percentage_error([10, 20], [10, 20]) == 0.0

    def test_mape_known_value(self):
        actual = [100, 100]
        predicted = [90, 110]
        # |100-90|/100 + |100-110|/100 = 0.1 + 0.1 = 0.2 / 2 = 0.1 → 10%
        assert abs(mean_absolute_percentage_error(actual, predicted) - 10.0) < 0.001

    def test_mape_handles_zero_actual(self):
        """Zero-demand days are skipped (no div-by-zero)."""
        actual = [0, 100, 0]
        predicted = [10, 90, 5]
        # Only the middle entry is counted: |100-90|/100 = 0.1 → 10%
        assert abs(mean_absolute_percentage_error(actual, predicted) - 10.0) < 0.001

    def test_mape_all_zeros_returns_zero(self):
        """All-zero actuals don't crash."""
        assert mean_absolute_percentage_error([0, 0, 0], [1, 1, 1]) == 0.0

    def test_bias_positive_when_overforecasting(self):
        """Positive bias = predictions > actuals."""
        result = bias([10, 10, 10], [12, 12, 12])
        assert result == 2.0

    def test_bias_negative_when_underforecasting(self):
        result = bias([10, 10, 10], [8, 8, 8])
        assert result == -2.0

    def test_bias_zero_for_balanced(self):
        """Equal over- and under-forecasts cancel."""
        result = bias([10, 10], [12, 8])
        assert result == 0.0


# ============================================================
# Walk-forward validation
# ============================================================
class TestWalkForwardEvaluation:
    def _make_history(self, n_days: int = 100, mean: float = 50.0) -> pd.Series:
        """Helper: synthetic daily history."""
        idx = pd.date_range("2024-01-01", periods=n_days, freq="D")
        # Mild noise around mean
        rng = np.random.default_rng(42)
        return pd.Series(mean + rng.normal(0, 5, n_days), index=idx).clip(lower=0)

    def test_too_short_history_returns_error(self):
        short = pd.Series([1, 2, 3])
        result = walk_forward_evaluate(short, "simple_average",
                                          train_window=60, test_window=14)
        assert result["n_folds"] == 0

    def test_unknown_method_returns_error(self):
        history = self._make_history()
        result = walk_forward_evaluate(history, "lstm_neural_net")
        assert "error" in result

    def test_simple_average_walkforward(self):
        history = self._make_history(n_days=100)
        result = walk_forward_evaluate(
            history, "simple_average",
            train_window=60, test_window=14, n_folds=3,
        )
        assert result["n_folds"] > 0
        assert result["mae"] > 0   # Some error expected on random data
        assert "folds" in result
        assert len(result["folds"]) == result["n_folds"]

    def test_moving_average_walkforward(self):
        history = self._make_history()
        result = walk_forward_evaluate(history, "moving_average",
                                          train_window=60, test_window=14)
        assert result["n_folds"] > 0

    def test_exponential_smoothing_walkforward(self):
        history = self._make_history()
        result = walk_forward_evaluate(history, "exponential_smoothing",
                                          train_window=60, test_window=14)
        assert result["n_folds"] > 0


# ============================================================
# Multi-method comparison
# ============================================================
class TestCompareMethods:
    def _make_history(self, n_days: int = 120) -> pd.Series:
        idx = pd.date_range("2024-01-01", periods=n_days, freq="D")
        rng = np.random.default_rng(7)
        return pd.Series(50 + rng.normal(0, 3, n_days), index=idx).clip(lower=0)

    def test_compare_returns_dataframe(self):
        df = compare_methods(self._make_history())
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 3  # 3 methods
        for col in ["method", "mae", "rmse", "mape", "bias", "n_folds"]:
            assert col in df.columns

    def test_compare_custom_methods(self):
        df = compare_methods(
            self._make_history(),
            methods=["simple_average", "moving_average"],
        )
        assert len(df) == 2

    def test_best_method_returns_string(self):
        df = compare_methods(self._make_history())
        best = best_method(df, metric="mape")
        assert isinstance(best, str)
        assert best in [
            "simple_average", "moving_average", "exponential_smoothing"
        ]

    def test_best_method_empty_falls_back(self):
        empty_df = pd.DataFrame(columns=["method", "mape", "n_folds"])
        result = best_method(empty_df)
        assert result == "moving_average"



class TestAutoMethodSelection:
    def test_select_method_returns_known_method(self):
        import numpy as np, pandas as pd
        from src.utils.forecasting import select_method
        idx = pd.date_range("2025-09-22", periods=365, freq="D")
        rng = np.random.default_rng(1)
        hist = pd.Series(rng.poisson(3.0, size=365).astype(float), index=idx)
        assert select_method(hist) in ("simple_average", "moving_average", "exponential_smoothing")

    def test_short_or_empty_history_falls_back(self):
        import pandas as pd
        from src.utils.forecasting import select_method
        assert select_method(pd.Series(dtype=float)) == "moving_average"
        idx = pd.date_range("2026-08-01", periods=30, freq="D")
        assert select_method(pd.Series([2.0] * 30, index=idx)) == "moving_average"

    def test_forecast_auto_dispatches(self):
        from datetime import date, timedelta
        from types import SimpleNamespace
        from src.utils.forecasting import forecast
        as_of = date(2026, 9, 21)
        moves = [SimpleNamespace(posting_date=as_of - timedelta(days=k), quantity=-3.0)
                 for k in range(0, 300, 2)]
        fc = forecast(moves, horizon_days=10, method="auto", as_of=as_of)
        assert len(fc) == 10 and all(v >= 0 for v in fc)
