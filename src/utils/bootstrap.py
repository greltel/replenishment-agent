"""
Bootstrap analysis for statistical significance of backtest results.

Why bootstrap?
  A single backtest run gives a point estimate (e.g., "savings = €66K") but
  no measure of uncertainty. The committee will ask: "How do we know this
  isn't a lucky window?". Bootstrap answers that.

Methodology (two stages):
  Stage 1 — block subsampling of windows
    1. Sample N random backtest windows from the available history
    2. Run As-Is and To-Be on each window → record TCO savings s_i
  Stage 2 — inference on the sample {s_1..s_N}
    3. Non-parametric bootstrap of the MEAN (Efron 1979): B resamples with
       replacement → 95% percentile CI of the mean and bootstrap p-value
       (share of resampled means ≤ 0)          → PRIMARY result
    4. Complementary checks:
       • t-based 95% CI of the mean (df = N-1) and one-sided t-test p-value
       • exact sign test on the N values (distribution-free)
    5. Also reported: the percentile interval of the INDIVIDUAL window values
       (2.5th–97.5th) — i.e. the spread of what a single window may give,
       NOT the uncertainty of the mean. Do not confuse the two.

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
    """Aggregate statistics across all bootstrap samples.

    Field guide (all on the metric's own unit — € for savings, pp for lift):
      • point_estimate / median / std_dev — descriptive stats of the N window values
      • std_error                          — std_dev / √N
      • mean_ci_lower / mean_ci_upper      — 95% percentile-bootstrap CI of the MEAN
                                             (B resamples)          ← PRIMARY
      • p_value                            — bootstrap p-value of the mean
                                             (share of resampled means ≤ 0; one-sided)
      • t_ci_lower / t_ci_upper            — 95% t-based CI of the mean (df = N-1)
      • t_p_value                          — one-sided t-test, H0: mean ≤ 0
      • sign_test_p_value                  — exact sign test, H0: P(s_i > 0) = 0.5
      • n_positive                         — how many windows had a value > 0
      • ci_lower / ci_upper                — 2.5th–97.5th percentile of the raw
                                             window values (spread of ONE window)
      • is_significant                     — bootstrap CI of the mean excludes 0
                                             AND p_value < 0.05
    """
    n_samples:        int
    metric:           str         # which KPI we bootstrapped
    point_estimate:   float       # mean of the window values
    median:           float
    std_error:        float       # std_dev / sqrt(n)
    ci_lower:         float       # percentile interval of the window values
    ci_upper:         float
    p_value:          float       # bootstrap p-value of the mean (one-sided)
    is_significant:   bool
    std_dev:          float = 0.0
    mean_ci_lower:    float = 0.0 # bootstrap-of-the-mean CI
    mean_ci_upper:    float = 0.0
    t_ci_lower:       float = 0.0 # t-based CI of the mean
    t_ci_upper:       float = 0.0
    t_statistic:      float = 0.0
    t_p_value:        float = 1.0 # one-sided t-test
    sign_test_p_value: float = 1.0
    n_positive:       int = 0
    n_bootstrap:      int = 0     # B (resamples of the mean)
    samples:          list[BootstrapSample] = field(default_factory=list)

    def summary_dict(self) -> dict:
        d = asdict(self)
        d.pop("samples", None)
        return d

    def __str__(self) -> str:
        return (
            f"{self.metric}: mean {self.point_estimate:+,.2f} "
            f"[95% bootstrap CI of the mean: {self.mean_ci_lower:+,.2f} to "
            f"{self.mean_ci_upper:+,.2f}], p = {self.p_value:.4f} "
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
    """Two-sided p-value on the RAW window values: proportion of values on
    either side of the null line (kept for backward compatibility; the
    primary inference is `bootstrap_mean`)."""
    if len(values) == 0:
        return 1.0

    p_below = float(np.mean(values <= null))
    p_above = float(np.mean(values >= null))
    return min(1.0, 2 * min(p_below, p_above))


def bootstrap_mean(
    values: np.ndarray,
    n_bootstrap: int = 2000,
    confidence: float = 0.95,
    seed: Optional[int] = 42,
) -> dict:
    """Stage 2 — non-parametric bootstrap of the sample mean (Efron 1979).

    Resample the N window values with replacement B times, compute the mean
    of each resample, and read off:
      • the percentile CI of the mean (2.5th / 97.5th percentile of the B means)
      • the one-sided bootstrap p-value = share of resampled means ≤ 0
        (with the +1 continuity correction of Davison & Hinkley 1997 so the
        p-value is never exactly 0)
    """
    values = np.asarray(values, dtype=float)
    n = len(values)
    if n == 0:
        return {"ci_lower": 0.0, "ci_upper": 0.0, "p_value": 1.0, "means": np.array([])}
    if n == 1:
        v = float(values[0])
        return {"ci_lower": v, "ci_upper": v, "p_value": 1.0 if v <= 0 else 0.0,
                "means": np.array([v])}

    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_bootstrap, n))
    means = values[idx].mean(axis=1)

    alpha = 1.0 - confidence
    ci_lower = float(np.percentile(means, alpha / 2 * 100))
    ci_upper = float(np.percentile(means, (1 - alpha / 2) * 100))
    p_value = float((np.sum(means <= 0.0) + 1) / (n_bootstrap + 1))
    return {"ci_lower": ci_lower, "ci_upper": ci_upper,
            "p_value": p_value, "means": means}


def t_interval(values: np.ndarray, confidence: float = 0.95) -> dict:
    """t-based CI of the mean (df = n-1) and one-sided t-test (H0: mean ≤ 0)."""
    from scipy import stats

    values = np.asarray(values, dtype=float)
    n = len(values)
    if n < 2:
        m = float(values[0]) if n == 1 else 0.0
        return {"ci_lower": m, "ci_upper": m, "t": 0.0, "p_value": 1.0}

    mean = float(values.mean())
    sd = float(values.std(ddof=1))
    se = sd / np.sqrt(n)
    if se == 0:
        return {"ci_lower": mean, "ci_upper": mean, "t": float("inf") if mean > 0 else 0.0,
                "p_value": 0.0 if mean > 0 else 1.0}
    t_crit = float(stats.t.ppf(1 - (1 - confidence) / 2, df=n - 1))
    t_stat = mean / se
    p_one_sided = float(stats.t.sf(t_stat, df=n - 1))
    return {"ci_lower": mean - t_crit * se, "ci_upper": mean + t_crit * se,
            "t": float(t_stat), "p_value": p_one_sided}


def sign_test_p_value(values: np.ndarray) -> float:
    """Exact one-sided sign test: P(X ≥ n_positive) under H0: P(s>0) = 0.5.
    Zero values are dropped (standard practice)."""
    from scipy import stats

    values = np.asarray(values, dtype=float)
    nonzero = values[values != 0]
    n = len(nonzero)
    if n == 0:
        return 1.0
    n_pos = int(np.sum(nonzero > 0))
    return float(stats.binom.sf(n_pos - 1, n, 0.5))


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
    n_bootstrap: int = 2000,
) -> BootstrapResult:
    """Run the two-stage analysis.

    Args:
        backtest_fn: Callable(start, end) → (asis_tco, tobe_tco, asis_svc, tobe_svc).
            This is the function that runs As-Is and To-Be for one window.
        history_start: First date in the available history.
        history_end:   Last date in the available history.
        window_size_days: Size of each backtest window.
        n_samples: Number of random windows (Stage 1).
        metric: Which metric to track ("savings" or "service_lift").
        seed: Random seed for reproducibility (windows AND resampling).
        progress_cb: Optional callback (i, total) for UI progress reporting.
        n_bootstrap: Number of resamples B for the bootstrap of the mean (Stage 2).

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

    return aggregate_samples(samples, metric=metric, n_bootstrap=n_bootstrap,
                             seed=seed)


def aggregate_samples(
    samples: list[BootstrapSample],
    metric: str = "savings",
    confidence: float = 0.95,
    n_bootstrap: int = 2000,
    seed: Optional[int] = 42,
) -> BootstrapResult:
    """Stage 2: compute aggregate statistics from the window samples."""
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

    n = len(values)
    # Spread of the individual window values (NOT the CI of the mean)
    ci_lower, ci_upper = percentile_ci(values, confidence)

    # Primary inference: bootstrap of the mean
    boot = bootstrap_mean(values, n_bootstrap=n_bootstrap,
                          confidence=confidence, seed=seed)
    # Complementary checks
    tt = t_interval(values, confidence)
    sign_p = sign_test_p_value(values)

    # Significance: bootstrap CI of the mean excludes zero AND p < 0.05
    ci_excludes_zero = (boot["ci_lower"] > 0) or (boot["ci_upper"] < 0)
    is_significant = ci_excludes_zero and (boot["p_value"] < 0.05)

    std_dev = float(np.std(values, ddof=1)) if n > 1 else 0.0

    return BootstrapResult(
        n_samples=n,
        metric=metric,
        point_estimate=float(np.mean(values)),
        median=float(np.median(values)),
        std_error=std_dev / np.sqrt(n) if n > 0 else 0.0,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        p_value=boot["p_value"],
        is_significant=is_significant,
        std_dev=std_dev,
        mean_ci_lower=boot["ci_lower"],
        mean_ci_upper=boot["ci_upper"],
        t_ci_lower=tt["ci_lower"],
        t_ci_upper=tt["ci_upper"],
        t_statistic=tt["t"],
        t_p_value=tt["p_value"],
        sign_test_p_value=sign_p,
        n_positive=int(np.sum(values > 0)),
        n_bootstrap=n_bootstrap if n > 1 else 0,
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
