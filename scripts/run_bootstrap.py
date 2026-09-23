"""
Bootstrap Confidence Intervals — statistical significance of agent savings.

Runs N random backtest windows from the historical period, then aggregates
the TCO savings (As-Is − To-Be) into a bootstrap distribution. Reports:
  • Mean savings & 95% confidence interval
  • Bootstrap p-value (H0: savings = 0)
  • Per-sample detail (CSV)

Usage:
    python scripts/run_bootstrap.py
    python scripts/run_bootstrap.py --n-samples 50 --window-size 30   # shorter windows
    python scripts/run_bootstrap.py --scenario aggressive --n-samples 100

References:
  • Efron & Tibshirani (1993): An Introduction to the Bootstrap
  • Bergmeir et al. (2018): cross-validation for time series

Why this matters for the thesis:
  Without statistical analysis, our "31% savings" claim is just a number.
  Bootstrap CI says: "We're 95%% confident the true savings are between
  €X and €Y." That's a defensible, publication-grade statement.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from src.data_layer.repository import Repository
from src.utils.as_of_date import get_effective_today
from src.utils.bootstrap import (
    run_bootstrap_analysis, samples_to_dataframe, BootstrapResult,
    aggregate_samples,
)
from src.utils.cost_estimator import SCENARIOS, get_scenario, CostScenario
from src.utils.logger import log

# Reuse existing backtest infrastructure
from scripts.run_validation import run_scenario


def _build_backtest_fn(repo: Repository, materials_df: pd.DataFrame,
                        scenario: CostScenario):
    """Return a callable(start, end) → (asis_tco, tobe_tco, asis_svc, tobe_svc)."""

    def backtest(w_start: date, w_end: date):
        asis_kpi, tobe_kpi = run_scenario(
            repo, materials_df, w_start, w_end, scenario,
        )
        return (
            asis_kpi.total_cost_of_ownership,
            tobe_kpi.total_cost_of_ownership,
            asis_kpi.cycle_service_level_pct,
            tobe_kpi.cycle_service_level_pct,
        )

    return backtest


def _format_currency(v: float) -> str:
    sign = "+" if v >= 0 else "-"
    return f"{sign}€{abs(v):,.0f}"


def _fmt_p(p: float) -> str:
    return "< 0.0001" if p < 0.0001 else f"{p:.4f}"


def print_report(savings: BootstrapResult, service: BootstrapResult,
                 window_size: int) -> None:
    """Print a clean console report of both bootstrap results (thesis Table 4.9)."""
    print()
    print("═" * 70)
    print("  RANDOM-WINDOW BACKTESTS + BOOTSTRAP CONFIDENCE INTERVALS")
    print("═" * 70)
    print()
    print(f"  Stage 1 — windows:        {savings.n_samples} random windows × {window_size} days")
    print(f"  Stage 2 — resamples:      B = {savings.n_bootstrap:,} (bootstrap of the mean)")
    print(f"  Cost basis:               € per {window_size}-day window "
          f"(annualised ≈ × {365 / window_size:.1f})")
    print()

    # ─── TCO Savings ───
    print(f"  ── TCO savings per {window_size}-day window (As-Is − To-Be) ──")
    print(f"    Mean savings:                     {_format_currency(savings.point_estimate)}")
    print(f"    Median savings:                   {_format_currency(savings.median)}")
    print(f"    Min / max window:                 "
          f"{_format_currency(min(s.savings for s in savings.samples if s.error is None))} / "
          f"{_format_currency(max(s.savings for s in savings.samples if s.error is None))}")
    print(f"    Std deviation (SD):               €{savings.std_dev:,.0f}")
    print(f"    Std error of mean (SD/√n):        €{savings.std_error:,.0f}")
    print(f"    95% CI of mean (bootstrap, B={savings.n_bootstrap}): "
          f"[{_format_currency(savings.mean_ci_lower)}, {_format_currency(savings.mean_ci_upper)}]")
    print(f"    95% CI of mean (t, df={savings.n_samples - 1}):        "
          f"[{_format_currency(savings.t_ci_lower)}, {_format_currency(savings.t_ci_upper)}]")
    print(f"    Spread of single windows (2.5–97.5%): "
          f"[{_format_currency(savings.ci_lower)}, {_format_currency(savings.ci_upper)}]")
    print(f"    p-value, bootstrap (H0: mean ≤ 0):  {_fmt_p(savings.p_value)}")
    print(f"    p-value, one-sided t-test:          {_fmt_p(savings.t_p_value)} "
          f"(t = {savings.t_statistic:.2f})")
    print(f"    p-value, exact sign test:           {_fmt_p(savings.sign_test_p_value)} "
          f"({savings.n_positive}/{savings.n_samples} windows positive)")
    print(f"    Annualised mean savings (× 365/{window_size}): "
          f"{_format_currency(savings.point_estimate * 365 / window_size)}")
    print(f"    Significant?      "
          f"{'✅ YES (bootstrap CI of the mean excludes 0, p < 0.05)' if savings.is_significant else '❌ no'}")
    print()

    # ─── Service Level Lift ───
    print("  ── Service Level Lift (percentage points) ──")
    print(f"    Mean lift:        {service.point_estimate:+.2f} pp")
    print(f"    Median lift:      {service.median:+.2f} pp")
    print(f"    Std error:        {service.std_error:.2f} pp")
    print(f"    95% CI of mean:   [{service.mean_ci_lower:+.2f}, {service.mean_ci_upper:+.2f}] pp")
    print(f"    p-value:          {_fmt_p(service.p_value)}")
    print(f"    Significant?      "
          f"{'✅ YES' if service.is_significant else '❌ no'}")
    print()

    # ─── Thesis-ready narrative ───
    print("═" * 70)
    print("  THESIS-READY STATEMENT")
    print("═" * 70)
    print()
    sig_text = "statistically significant" if savings.is_significant else "not statistically significant"
    print(f"  Across {savings.n_samples} randomly-sampled {window_size}-day backtest windows,")
    print(f"  the agent achieved a mean TCO reduction of {_format_currency(savings.point_estimate)}")
    print(f"  per window (95% bootstrap CI of the mean: [{_format_currency(savings.mean_ci_lower)},")
    print(f"  {_format_currency(savings.mean_ci_upper)}], B = {savings.n_bootstrap}, "
          f"p {_fmt_p(savings.p_value)}; t-test p {_fmt_p(savings.t_p_value)};")
    print(f"  sign test p {_fmt_p(savings.sign_test_p_value)}, "
          f"{savings.n_positive}/{savings.n_samples} windows positive).")
    print(f"  This result is {sig_text} at the α = 0.05 level.")
    print(f"  Indicative annualised equivalent: "
          f"{_format_currency(savings.point_estimate * 365 / window_size)} per year.")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Bootstrap confidence intervals for agent backtest savings.",
    )
    parser.add_argument("--n-samples", type=int, default=30,
                        help="Number of bootstrap iterations (default 30; "
                             "use 100+ for tighter CIs)")
    parser.add_argument("--window-size", type=int, default=60,
                        help="Backtest window size in days (default 60: the same length "
                             "as the main backtest and at least as long as the longest "
                             "import lead time, so every window contains the agent's "
                             "decisions AND their consequences)")
    parser.add_argument("--scenario", type=str, default="realistic",
                        choices=list(SCENARIOS.keys()),
                        help="Cost scenario (default: realistic)")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed for reproducibility")
    parser.add_argument("--n-bootstrap", type=int, default=2000,
                        help="Resamples B for the bootstrap of the mean (default 2000)")
    parser.add_argument("--out", type=str, default="bootstrap_report.csv",
                        help="Output filename for per-sample CSV")
    parser.add_argument("--history-start", type=str, default=None,
                        help="History start date YYYY-MM-DD "
                             "(default: earliest movement in the dataset)")
    parser.add_argument("--history-end", type=str, default=None,
                        help="History end date YYYY-MM-DD (default: the dataset's as-of date)")
    args = parser.parse_args()

    repo = Repository()
    summary = repo.get_dataset_summary()

    end = (date.fromisoformat(args.history_end)
           if args.history_end else get_effective_today())
    if args.history_start:
        start = date.fromisoformat(args.history_start)
    else:
        first_mv = summary.get("first_movement")
        # Leave 30 days of history before the first window so the agent has
        # something to forecast from at the first review date.
        start = (first_mv + timedelta(days=30)) if first_mv else end - timedelta(days=365)

    available_days = (end - start).days
    if available_days < args.window_size * 2:
        log.warning(
            f"History span ({available_days} days) is small relative to "
            f"window size ({args.window_size}). Consider --history-start "
            f"or smaller --window-size."
        )

    log.info(f"Bootstrap analysis: {args.n_samples} samples × "
             f"{args.window_size}-day windows from [{start}, {end}]")
    log.info(f"Scenario: {args.scenario}")
    log.info(f"Estimated time: {args.n_samples * 3}-{args.n_samples * 20} seconds")

    materials_df = pd.read_sql("SELECT * FROM materials", repo.engine)
    scenario = get_scenario(args.scenario)

    backtest_fn = _build_backtest_fn(repo, materials_df, scenario)

    def _progress(i: int, total: int):
        if i == 1 or i % 5 == 0 or i == total:
            log.info(f"  Bootstrap progress: {i}/{total}")

    # ─── Stage 1 + 2 for savings ───
    savings_result = run_bootstrap_analysis(
        backtest_fn=backtest_fn,
        history_start=start,
        history_end=end,
        window_size_days=args.window_size,
        n_samples=args.n_samples,
        metric="savings",
        seed=args.seed,
        progress_cb=_progress,
        n_bootstrap=args.n_bootstrap,
    )

    # ─── Stage 2 for the service-level lift on the same windows ───
    service_result = aggregate_samples(savings_result.samples,
                                       metric="service_lift",
                                       n_bootstrap=args.n_bootstrap,
                                       seed=args.seed)

    # ─── Print + Save ───
    print_report(savings_result, service_result, args.window_size)

    df = samples_to_dataframe(savings_result.samples)
    df.insert(0, "window", range(1, len(df) + 1))
    df["window_days"] = args.window_size
    out_path = Path(args.out)
    df.to_csv(out_path, index=False)
    log.success(f"Per-window CSV written to {out_path.absolute()} "
                f"(thesis Appendix Γ, Table Γ.1)")

    # Also save summary stats as a separate row CSV
    summary_path = out_path.with_name(out_path.stem + "_summary.csv")
    summary_df = pd.DataFrame([
        {**savings_result.summary_dict(), "metric": "tco_savings_eur",
         "window_days": args.window_size, "scenario": args.scenario},
        {**service_result.summary_dict(), "metric": "service_lift_pp",
         "window_days": args.window_size, "scenario": args.scenario},
    ])
    summary_df.to_csv(summary_path, index=False)
    log.success(f"Summary CSV written to {summary_path.absolute()} (thesis Table 4.9)")

    repo.close()


if __name__ == "__main__":
    main()
