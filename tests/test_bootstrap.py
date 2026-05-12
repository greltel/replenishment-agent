"""Tests for the bootstrap module."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from src.utils.bootstrap import (
    BootstrapSample,
    BootstrapResult,
    percentile_ci,
    bootstrap_p_value,
    random_windows,
    run_bootstrap_analysis,
    aggregate_samples,
    samples_to_dataframe,
)


# ============================================================
# Statistical primitives
# ============================================================
class TestPercentileCI:
    def test_uniform_distribution(self):
        """For a uniform [0, 100] sample, 95% CI should be ~[2.5, 97.5]."""
        rng = np.random.default_rng(0)
        values = rng.uniform(0, 100, 10000)
        lower, upper = percentile_ci(values, confidence=0.95)
        assert 1 < lower < 5
        assert 95 < upper < 99

    def test_constant_distribution(self):
        """All-same values → CI collapses to that value."""
        values = np.array([42.0] * 100)
        lower, upper = percentile_ci(values)
        assert lower == 42.0
        assert upper == 42.0

    def test_different_confidence_levels(self):
        """Higher confidence → wider CI."""
        rng = np.random.default_rng(0)
        values = rng.normal(0, 1, 5000)
        lower_90, upper_90 = percentile_ci(values, confidence=0.90)
        lower_99, upper_99 = percentile_ci(values, confidence=0.99)
        assert lower_99 < lower_90
        assert upper_99 > upper_90


class TestBootstrapPValue:
    def test_clearly_positive_distribution(self):
        """All positive values → p-value ≈ 0 (rejects H0: mean = 0)."""
        values = np.array([10.0] * 100)
        p = bootstrap_p_value(values, null=0.0)
        assert p < 0.05

    def test_distribution_centered_on_zero(self):
        """Symmetric around 0 → p-value high."""
        rng = np.random.default_rng(0)
        values = rng.normal(0, 1, 1000)
        p = bootstrap_p_value(values, null=0.0)
        assert p > 0.5    # Should be near 1.0

    def test_empty_array_returns_one(self):
        assert bootstrap_p_value(np.array([]), null=0.0) == 1.0

    def test_all_negative_distribution(self):
        """All-negative → very low p-value."""
        values = np.array([-5.0] * 100)
        p = bootstrap_p_value(values, null=0.0)
        assert p < 0.05


class TestRandomWindows:
    def test_correct_window_count(self):
        windows = random_windows(
            date(2025, 1, 1), date(2025, 12, 31),
            window_size_days=30, n_windows=10, seed=42,
        )
        assert len(windows) == 10

    def test_all_windows_correct_size(self):
        windows = random_windows(
            date(2025, 1, 1), date(2025, 12, 31),
            window_size_days=21, n_windows=5, seed=42,
        )
        for start, end in windows:
            assert (end - start).days == 21

    def test_all_windows_within_history(self):
        h_start = date(2025, 1, 1)
        h_end = date(2025, 12, 31)
        windows = random_windows(h_start, h_end, 14, 10, seed=42)
        for start, end in windows:
            assert start >= h_start
            assert end <= h_end

    def test_reproducible_with_seed(self):
        """Same seed → same windows."""
        w1 = random_windows(date(2025, 1, 1), date(2025, 12, 31), 14, 5, seed=42)
        w2 = random_windows(date(2025, 1, 1), date(2025, 12, 31), 14, 5, seed=42)
        assert w1 == w2

    def test_different_seeds_different_windows(self):
        w1 = random_windows(date(2025, 1, 1), date(2025, 12, 31), 14, 5, seed=1)
        w2 = random_windows(date(2025, 1, 1), date(2025, 12, 31), 14, 5, seed=2)
        assert w1 != w2

    def test_history_too_short_returns_single_window(self):
        """When window > available history, return [original range]."""
        windows = random_windows(date(2025, 1, 1), date(2025, 1, 10),
                                   window_size_days=30, n_windows=5)
        assert len(windows) == 1


# ============================================================
# Bootstrap aggregation
# ============================================================
class TestAggregateSamples:
    def _make_sample(self, savings: float, asis_svc: float = 95,
                     tobe_svc: float = 96) -> BootstrapSample:
        return BootstrapSample(
            window_start=date(2025, 1, 1),
            window_end=date(2025, 1, 21),
            asis_tco=1000.0,
            tobe_tco=1000.0 - savings,
            savings=savings,
            asis_service=asis_svc,
            tobe_service=tobe_svc,
        )

    def test_empty_samples_returns_zeros(self):
        result = aggregate_samples([], metric="savings")
        assert result.n_samples == 0
        assert result.point_estimate == 0.0
        assert result.is_significant is False

    def test_consistent_positive_savings_significant(self):
        """All samples show positive savings → significant."""
        samples = [self._make_sample(100 + i) for i in range(30)]
        result = aggregate_samples(samples, metric="savings")
        assert result.n_samples == 30
        assert result.point_estimate > 0
        assert result.ci_lower > 0          # CI excludes 0
        assert result.is_significant is True

    def test_mixed_savings_not_significant(self):
        """Half positive, half negative → not significant."""
        samples = [self._make_sample((-1) ** i * 100) for i in range(30)]
        result = aggregate_samples(samples, metric="savings")
        assert result.is_significant is False

    def test_failed_samples_excluded(self):
        """Samples with .error are excluded from aggregation."""
        good = [self._make_sample(100) for _ in range(20)]
        bad = [
            BootstrapSample(
                window_start=date(2025, 1, 1), window_end=date(2025, 1, 21),
                asis_tco=0, tobe_tco=0, savings=999999,
                asis_service=0, tobe_service=0,
                error="something broke",
            )
            for _ in range(5)
        ]
        result = aggregate_samples(good + bad, metric="savings")
        assert result.n_samples == 20    # Only valid samples
        # The 'broken' samples with huge savings should NOT skew the mean
        assert result.point_estimate == 100.0

    def test_service_lift_metric(self):
        samples = [self._make_sample(0, asis_svc=90, tobe_svc=95)
                   for _ in range(20)]
        result = aggregate_samples(samples, metric="service_lift")
        # Each sample has lift = 5pp
        assert result.point_estimate == 5.0

    def test_unknown_metric_raises(self):
        samples = [self._make_sample(100)]
        with pytest.raises(ValueError):
            aggregate_samples(samples, metric="bogus_metric")


# ============================================================
# End-to-end with mock backtest
# ============================================================
class TestRunBootstrapAnalysis:
    def test_uses_provided_backtest_fn(self):
        """The callable is invoked once per window."""
        call_count = [0]

        def fake_backtest(start: date, end: date):
            call_count[0] += 1
            return 1000.0, 800.0, 95.0, 97.0   # consistent €200 savings

        result = run_bootstrap_analysis(
            backtest_fn=fake_backtest,
            history_start=date(2025, 1, 1),
            history_end=date(2025, 12, 31),
            window_size_days=21,
            n_samples=15,
            seed=42,
        )
        assert call_count[0] == 15
        assert result.n_samples == 15
        assert result.point_estimate == 200.0    # All samples identical
        assert result.is_significant is True     # Constant positive savings

    def test_handles_backtest_errors_gracefully(self):
        """When backtest_fn raises, the sample gets an error string."""
        def flaky_backtest(start, end):
            if start.day % 2 == 0:
                raise RuntimeError("boom")
            return 1000.0, 800.0, 95.0, 97.0

        result = run_bootstrap_analysis(
            backtest_fn=flaky_backtest,
            history_start=date(2025, 1, 1),
            history_end=date(2025, 12, 31),
            window_size_days=14,
            n_samples=20,
            seed=42,
        )
        # Some samples have errors, but aggregation still works
        errored = sum(1 for s in result.samples if s.error)
        ok = sum(1 for s in result.samples if not s.error)
        assert errored + ok == 20
        assert result.n_samples == ok    # Only valid samples in n_samples


# ============================================================
# DataFrame conversion
# ============================================================
class TestSamplesToDataFrame:
    def test_basic_conversion(self):
        samples = [
            BootstrapSample(
                window_start=date(2025, 1, 1), window_end=date(2025, 1, 21),
                asis_tco=1000, tobe_tco=800, savings=200,
                asis_service=90, tobe_service=95,
            )
        ]
        df = samples_to_dataframe(samples)
        assert len(df) == 1
        assert df.iloc[0]["savings"] == 200
        assert df.iloc[0]["service_lift"] == 5

    def test_includes_error_column(self):
        samples = [
            BootstrapSample(
                window_start=date(2025, 1, 1), window_end=date(2025, 1, 10),
                asis_tco=0, tobe_tco=0, savings=0,
                asis_service=0, tobe_service=0,
                error="failed",
            )
        ]
        df = samples_to_dataframe(samples)
        assert df.iloc[0]["error"] == "failed"
