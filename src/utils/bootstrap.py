"""
Bootstrap analysis for statistical significance of backtest results.

Why bootstrap?
  A single backtest run gives a point estimate (e.g., "savings = €66K") but
  no measure of uncertainty. The committee will ask: "How do we know this
  isn't a lucky window?". Bootstrap answers that.

Methodology:
  1. Sample N random backtest windows from the available history
  2. Run As-Is and To-Be on each window → record TCO savings
  3. Use the empirical distribution of savings to compute:
       • Mean & median savings
       • 95% confidence interval (percentile method)
       • p-value via two-sided bootstrap test (H0: savings = 0)

References:
  • Efron, B. & Tibshirani, R. (1993). An Introduction to the Bootstrap. CRC.
  • Bergmeir, C., Hyndman, R.J., Koo, B. (2018). "A note on the validity of
    cross-validation for evaluating autoregressive time series prediction."
    Computational Statistics & Data Analysis, 120, 70-83.
  • Künsch, H.R. (1989). "The jackknife and the bootstrap for general
    stationary observations." Annals of Statistics, 17(3), 1217-1241.

Design notes:
  • We use simple random window sampling (not block bootstrap). For our
    use case — comparing two policies on the same windows — paired
    comparisons within each window largely handle autocorrelation, and the
    bootstrap variation comes from window selection, not within-window
    resampling.
  • We keep windows small (default 21 days) to allow many independent
    samples from the available history.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from typing import Callable, Optional

import numpy as np
import pandas as pd


# ============================================================
# Result containers
# ============================================================
@dataclass
class BootstrapSample:
    """One sample from the bootstrap distribution."""
    window_start: date
    window_end:   date
    asis_tco:     float
    tobe_tco:     float
    savings:      float           # asis_tco - tobe_tco
    asis_service: float           # cycle service %
    tobe_service: float
    error:        Optional[str] = None


@dataclass
class BootstrapResult:
    """Aggregate statistics across all bootstrap samples."""
    n_samples:        int
    metric:           str         # which KPI we bootstrapped
    point_estimate:   float       # mean
    median:           float
    std_error:        float       # std of bootstrap samples
    ci_lower:         float       # 95% CI lower
    ci_upper:         float       # 95% CI upper
    p_value:          float       # two-sided test: H0 = 0
    is_significant:   bool        # p < 0.05 AND CI excludes 0
    samples:          list[BootstrapSample] = field(default_factory=list)

    def summary_dict(self) -> dict:
        d = asdict(self)
        d.pop("samples", None)
        return d

    def __str__(self) -> str:
        sign = "" if self.point_estimate >= 0 else "-"
        return (
            f"{self.metric}: {self.point_estimate:+,.2f} "
            f"[95% CI: {self.ci_lower:+,.2f} to {self.ci_upper:+,.2f}], "
            f"p = {self.p_value:.4f} "
            f"({'significant' if self.is_significant else 'not significant'})"
        )


# ============================================================
# Bootstrap engine
# ============================================================
def percentile_ci(values: np.ndarray, confidence: float = 0.95) -> tuple[float, float]:
    """Standard percentile bootstrap CI.

    For 95% CI we use the 2.5th and 97.5th percentiles.
    """
    alpha = 1.0 - confidence
    lower = float(np.percentile(values, alpha / 2 * 100))
    upper = float(np.percentile(values, (1 - alpha / 2) * 100))
    return lower, upper


def bootstrap_p_value(values: np.ndarray, null: float = 0.0) -> float:
    """Two-sided p-value: proportion of bootstrap samples that
    don't cross the null hypothesis line.

    For "savings > 0" testing: p = 2 × min(P(<=null), P(>=null)) / N.
    Tighter for unimodal symmetric distributions, conservative otherwise.
    """
    if len(values) == 0:
        return 1.0

    n = len(values)
    p_below = float(np.mean(values <= null))
    p_above = float(np.mean(values >= null))
    # Standard two-sided bootstrap p-value
    return min(1.0, 2 * min(p_below, p_above))


def random_windows(
    start: date,
    end: date,
    window_size_days: int,
    n_windows: int,
    seed: Optional[int] = None,
) -> list[tuple[date, date]]:
    """Generate n random (start, end) windows sampled from [start, end]."""
    rng = np.random.default_rng(seed)
    total_days = (end - start).days
    max_offset = total_days - window_size_days
    if max_offset <= 0:
        # Not enough room — return one window of available size
        return [(start, end)]

    offsets = rng.integers(0, max_offset + 1, size=n_windows)
    return [
        (start + timedelta(days=int(o)),
         start + timedelta(days=int(o) + window_size_days))
        for o in offsets
    ]


def run_bootstrap_analysis(
    backtest_fn: Callable[[date, date], tuple[float, float, float, float]],
    history_start: date,
    history_end:   date,
    window_size_days: int = 21,
    n_samples: int = 30,
    metric: str = "savings",
    seed: Optional[int] = 42,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> BootstrapResult:
    """Run the bootstrap analysis.

    Args:
        backtest_fn: Callable(start, end) → (asis_tco, tobe_tco, asis_svc, tobe_svc).
            This is the function that runs As-Is and To-Be for one window.
        history_start: First date in the available history.
        history_end:   Last date in the available history.
        window_size_days: Size of each backtest window.
        n_samples: Number of bootstrap iterations.
        metric: Which metric to track ("savings" or "service_lift").
        seed: Random seed for reproducibility.
        progress_cb: Optional callback (i, total) for UI progress reporting.

    Returns:
        BootstrapResult with all samples and aggregate statistics.
    """
    windows = random_windows(
        history_start, history_end, window_size_days, n_samples, seed,
    )

    samples: list[BootstrapSample] = []

    for i, (w_start, w_end) in enumerate(windows):
        if progress_cb is not None:
            progress_cb(i + 1, len(windows))

        try:
            asis_tco, tobe_tco, asis_svc, tobe_svc = backtest_fn(w_start, w_end)
            samples.append(BootstrapSample(
                window_start=w_start,
                window_end=w_end,
                asis_tco=asis_tco,
                tobe_tco=tobe_tco,
                savings=asis_tco - tobe_tco,
                asis_service=asis_svc,
                tobe_service=tobe_svc,
            ))
        except Exception as e:
            samples.append(BootstrapSample(
                window_start=w_start, window_end=w_end,
                asis_tco=0, tobe_tco=0,
                savings=0, asis_service=0, tobe_service=0,
                error=str(e),
            ))

    return aggregate_samples(samples, metric=metric)


def aggregate_samples(
    samples: list[BootstrapSample],
    metric: str = "savings",
    confidence: float = 0.95,
) -> BootstrapResult:
    """Compute aggregate statistics from a list of bootstrap samples."""
    # Filter out failed samples
    valid = [s for s in samples if s.error is None]

    if not valid:
        return BootstrapResult(
            n_samples=0, metric=metric, point_estimate=0.0, median=0.0,
            std_error=0.0, ci_lower=0.0, ci_upper=0.0,
            p_value=1.0, is_significant=False, samples=samples,
        )

    # Extract the metric values
    if metric == "savings":
        values = np.array([s.savings for s in valid])
    elif metric == "service_lift":
        values = np.array([s.tobe_service - s.asis_service for s in valid])
    else:
        raise ValueError(f"Unknown metric: {metric}")

    ci_lower, ci_upper = percentile_ci(values, confidence)
    p_value = bootstrap_p_value(values, null=0.0)

    # Significance: 95% CI excludes zero AND p < 0.05
    ci_excludes_zero = (ci_lower > 0) or (ci_upper < 0)
    is_significant = ci_excludes_zero and (p_value < 0.05)

    return BootstrapResult(
        n_samples=len(valid),
        metric=metric,
        point_estimate=float(np.mean(values)),
        median=float(np.median(values)),
        std_error=float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        p_value=p_value,
        is_significant=is_significant,
        samples=samples,
    )


def samples_to_dataframe(samples: list[BootstrapSample]) -> pd.DataFrame:
    """Convert samples to a DataFrame for analysis/plotting."""
    return pd.DataFrame([
        {
            "window_start":  s.window_start,
            "window_end":    s.window_end,
            "asis_tco":      s.asis_tco,
            "tobe_tco":      s.tobe_tco,
            "savings":       s.savings,
            "asis_service":  s.asis_service,
            "tobe_service":  s.tobe_service,
            "service_lift":  s.tobe_service - s.asis_service,
            "error":         s.error or "",
        }
        for s in samples
    ])
