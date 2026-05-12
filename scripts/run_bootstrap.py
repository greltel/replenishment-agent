"""
Bootstrap Confidence Intervals — statistical significance of agent savings.

Runs N random backtest windows from the historical period, then aggregates
the TCO savings (As-Is − To-Be) into a bootstrap distribution. Reports:
  • Mean savings & 95% confidence interval
  • Bootstrap p-value (H0: savings = 0)
  • Per-sample detail (CSV)

Usage:
    python scripts/run_bootstrap.py
    python scripts/run_bootstrap.py --n-samples 50 --window-size 30
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
from src.utils.bootstrap import (
    run_bootstrap_analysis, samples_to_dataframe, BootstrapResult,
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


def print_report(savings: BootstrapResult, service: BootstrapResult) -> None:
    """Print a clean console report of both bootstrap results."""
    print()
    print("═" * 70)
    print("  BOOTSTRAP CONFIDENCE INTERVALS")
    print("═" * 70)
    print()
    print(f"  Bootstrap samples: {savings.n_samples}")
    print()

    # ─── TCO Savings ───
    print("  ── Total Cost of Ownership Savings ──")
    print(f"    Mean savings:     {_format_currency(savings.point_estimate)}")
    print(f"    Median savings:   {_format_currency(savings.median)}")
    print(f"    Std error:        €{savings.std_error:,.0f}")
    print(f"    95% CI:           [{_format_currency(savings.ci_lower)}, "
          f"{_format_currency(savings.ci_upper)}]")
    print(f"    p-value:          {savings.p_value:.4f}")
    print(f"    Significant?      "
          f"{'✅ YES (CI excludes 0, p < 0.05)' if savings.is_significant else '❌ no'}")
    print()

    # ─── Service Level Lift ───
    print("  ── Service Level Lift (percentage points) ──")
    print(f"    Mean lift:        {service.point_estimate:+.2f} pp")
    print(f"    Median lift:      {service.median:+.2f} pp")
    print(f"    Std error:        {service.std_error:.2f} pp")
    print(f"    95% CI:           [{service.ci_lower:+.2f}, {service.ci_upper:+.2f}] pp")
    print(f"    p-value:          {service.p_value:.4f}")
    print(f"    Significant?      "
          f"{'✅ YES' if service.is_significant else '❌ no'}")
    print()

    # ─── Thesis-ready narrative ───
    print("═" * 70)
    print("  THESIS-READY STATEMENT")
    print("═" * 70)
    print()
    sig_text = "statistically significant" if savings.is_significant else "not statistically significant"
    print(f"  Across {savings.n_samples} randomly-sampled backtest windows from the")
    print(f"  historical period, the agent achieved a mean TCO reduction of")
    print(f"  {_format_currency(savings.point_estimate)} (95% CI: [{_format_currency(savings.ci_lower)},")
    print(f"  {_format_currency(savings.ci_upper)}], bootstrap p = {savings.p_value:.4f}).")
    print(f"  This result is {sig_text} at the α = 0.05 level.")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Bootstrap confidence intervals for agent backtest savings.",
    )
    parser.add_argument("--n-samples", type=int, default=30,
                        help="Number of bootstrap iterations (default 30; "
                             "use 100+ for tighter CIs)")
    parser.add_argument("--window-size", type=int, default=21,
                        help="Backtest window size in days (default 21)")
    parser.add_argument("--scenario", type=str, default="realistic",
                        choices=list(SCENARIOS.keys()),
                        help="Cost scenario (default: realistic)")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed for reproducibility")
    parser.add_argument("--out", type=str, default="bootstrap_report.csv",
                        help="Output filename for per-sample CSV")
    parser.add_argument("--history-start", type=str, default=None,
                        help="History start date YYYY-MM-DD (default: today-365)")
    parser.add_argument("--history-end", type=str, default=None,
                        help="History end date YYYY-MM-DD (default: today-1)")
    args = parser.parse_args()

    end = (date.fromisoformat(args.history_end)
           if args.history_end else date.today() - timedelta(days=1))
    start = (date.fromisoformat(args.history_start)
             if args.history_start else end - timedelta(days=365))

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
    log.info(f"Estimated time: {args.n_samples * 20}-{args.n_samples * 60} seconds")

    repo = Repository()
    materials_df = pd.read_sql("SELECT * FROM materials", repo.engine)
    scenario = get_scenario(args.scenario)

    backtest_fn = _build_backtest_fn(repo, materials_df, scenario)

    def _progress(i: int, total: int):
        if i == 1 or i % 5 == 0 or i == total:
            log.info(f"  Bootstrap progress: {i}/{total}")

    # ─── Run for savings ───
    savings_result = run_bootstrap_analysis(
        backtest_fn=backtest_fn,
        history_start=start,
        history_end=end,
        window_size_days=args.window_size,
        n_samples=args.n_samples,
        metric="savings",
        seed=args.seed,
        progress_cb=_progress,
    )

    # ─── Recompute service level lift from same samples ───
    from src.utils.bootstrap import aggregate_samples
    service_result = aggregate_samples(savings_result.samples,
                                          metric="service_lift")

    # ─── Print + Save ───
    print_report(savings_result, service_result)

    df = samples_to_dataframe(savings_result.samples)
    out_path = Path(args.out)
    df.to_csv(out_path, index=False)
    log.success(f"Per-sample CSV written to {out_path.absolute()}")

    # Also save summary stats as a separate row CSV
    summary_path = out_path.with_name(out_path.stem + "_summary.csv")
    summary_df = pd.DataFrame([
        {"metric": "tco_savings_eur", **savings_result.summary_dict()},
        {"metric": "service_lift_pp", **service_result.summary_dict()},
    ])
    summary_df.to_csv(summary_path, index=False)
    log.success(f"Summary CSV written to {summary_path.absolute()}")

    repo.close()


if __name__ == "__main__":
    main()
