"""
Backtest of the pilot policy in every 60-day window of the history.

The main backtest (run_validation) uses one window: the 60 days up to the
as-of date. This script runs As-Is and To-Be the same way (evaluation per
demand pattern, the service levels of SERVICE_LEVEL_BY_ABC) in consecutive,
non-overlapping windows that go back from the as-of date, as long as a
window has the full 52 weeks of history before it that the demand
classification needs. It shows whether the result of the main window holds
in other periods of the year.

    python scripts/run_pilot_windows.py --out reports/pilot/pilot_windows.csv --jobs 2

Windows that contain a date of --exclude-dates (default: the environment
variable PILOT_WINDOWS_EXCLUDE, set in data/pilot/dataset.env) are run and
written but left out of the summary: e.g. a one-off mass posting that is
not an ordering decision and would count as thousands of As-Is orders.

Output:
  <out>             one row per window: As-Is and To-Be totals, savings, and
                    how many materials needed an estimated opening stock;
  <out>_summary     mean, median, min and max of the savings over the
                    included windows, in how many of them the To-Be is
                    cheaper, the exact sign test and the t and bootstrap 95 %
                    intervals of the mean (src/utils/bootstrap.py). With a
                    handful of windows the intervals are wide.

The master data (lead time, MOQ, lot sizing) are the ones of the as-of date,
as in every backtest; in the older windows they also contain later history.

Run time on the pilot data: about 20 minutes per window and job; each job
needs about 3.5 GB of memory.
"""
from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.run_validation import kpis_from_state, simulate_asis, simulate_tobe  # noqa: E402
from src.config import config  # noqa: E402
from src.data_layer.repository import Repository  # noqa: E402
from src.mrp.demand_pattern import HISTORY_DAYS  # noqa: E402
from src.utils.as_of_date import get_effective_today  # noqa: E402
from src.utils.bootstrap import BootstrapSample, aggregate_samples  # noqa: E402
from src.utils.cost_estimator import get_scenario  # noqa: E402
from src.utils.logger import log  # noqa: E402

_FIELDS = {
    "total_cost_of_ownership": "tco_eur",
    "holding_cost_eur":        "holding_eur",
    "stockout_cost_eur":       "stockout_eur",
    "lost_sales_eur":          "lost_sales_eur",
    "ordering_cost_eur":       "ordering_eur",
    "n_orders":                "n_orders",
    "avg_inventory_eur":       "avg_inventory_eur",
    "cycle_service_level_pct": "cycle_service_pct",
    "fill_rate_pct":           "fill_rate_pct",
}


def windows_back(end: date, window_days: int, earliest_start: date) -> list[tuple[date, date]]:
    """Consecutive non-overlapping windows of `window_days`, the first one
    ending on `end`, going back while the start is not before
    `earliest_start`. Latest window first."""
    out = []
    while True:
        start = end - timedelta(days=window_days - 1)
        if start < earliest_start:
            return out
        out.append((start, end))
        end = start - timedelta(days=1)


def parse_dates(spec: str | None) -> list[date]:
    """'2024-12-30,2025-12-31' → dates; empty or None → []."""
    return [date.fromisoformat(s.strip()) for s in (spec or "").split(",") if s.strip()]


def excluded_by(start: date, end: date, dates: list[date]) -> list[date]:
    """The dates of `dates` that fall inside the window."""
    return [d for d in dates if start <= d <= end]


def opening_estimates(repo: Repository, start: date) -> int:
    """Materials whose opening stock cannot be rolled back from the snapshot
    (no value or a negative one), so that the backtest starts them from a
    multiple of the safety stock (run_validation._initial_stock)."""
    n = 0
    for m in repo.get_all_materials():
        qty, _ = repo.get_stock_at(m.material_id, start - timedelta(days=1))
        if qty is None or qty < 0:
            n += 1
    return n


def run_window(start: date, end: date, scenario_name: str) -> dict:
    """As-Is and To-Be in one window, as run_validation does."""
    log.info(f"Window {start} → {end}: As-Is and To-Be")
    repo = Repository()
    materials_df = pd.read_sql("SELECT * FROM materials", repo.engine)
    scenario = get_scenario(scenario_name)
    asis = kpis_from_state(simulate_asis(repo, start, end, by_pattern=True),
                           materials_df, scenario, start, end)
    tobe = kpis_from_state(simulate_tobe(repo, start, end, 60, by_pattern=True),
                           materials_df, scenario, start, end)
    row = {"window_start": start, "window_end": end,
           "opening_stock_estimated": opening_estimates(repo, start)}
    repo.close()
    for attr, col in _FIELDS.items():
        row[f"asis_{col}"] = getattr(asis, attr)
        row[f"tobe_{col}"] = getattr(tobe, attr)
    row["savings_eur"] = row["asis_tco_eur"] - row["tobe_tco_eur"]
    row["savings_pct"] = (row["savings_eur"] / row["asis_tco_eur"] * 100
                          if row["asis_tco_eur"] else None)
    return row


def summarize(df: pd.DataFrame, seed: int = 42) -> pd.DataFrame:
    """Statistics of the savings over the included windows (metric, value)."""
    inc = df[df["included"]]
    samples = [BootstrapSample(window_start=r.window_start, window_end=r.window_end,
                               asis_tco=r.asis_tco_eur, tobe_tco=r.tobe_tco_eur,
                               savings=r.savings_eur, asis_service=r.asis_cycle_service_pct,
                               tobe_service=r.tobe_cycle_service_pct)
               for r in inc.itertuples(index=False)]
    rows = [("windows_run", len(df)), ("windows_included", len(inc))]
    if not samples:
        return pd.DataFrame(rows, columns=["metric", "value"])
    sav = aggregate_samples(samples, metric="savings", seed=seed)
    lift = aggregate_samples(samples, metric="service_lift", seed=seed)
    rows += [
        ("savings_mean_eur", sav.point_estimate),
        ("savings_median_eur", sav.median),
        ("savings_min_eur", float(inc["savings_eur"].min())),
        ("savings_max_eur", float(inc["savings_eur"].max())),
        ("savings_pct_mean", float(inc["savings_pct"].mean())),
        ("savings_pct_min", float(inc["savings_pct"].min())),
        ("savings_pct_max", float(inc["savings_pct"].max())),
        ("windows_tobe_cheaper", sav.n_positive),
        ("sign_test_p", sav.sign_test_p_value),
        ("t_ci95_lower_eur", sav.t_ci_lower),
        ("t_ci95_upper_eur", sav.t_ci_upper),
        ("t_test_p_one_sided", sav.t_p_value),
        ("bootstrap_ci95_lower_eur", sav.mean_ci_lower),
        ("bootstrap_ci95_upper_eur", sav.mean_ci_upper),
        ("service_lift_mean_pp", lift.point_estimate),
        ("service_lift_min_pp", float((inc["tobe_cycle_service_pct"]
                                       - inc["asis_cycle_service_pct"]).min())),
    ]
    return pd.DataFrame(rows, columns=["metric", "value"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--window-days", type=int, default=60)
    parser.add_argument("--end", type=str, default=None,
                        help="End of the latest window, YYYY-MM-DD (default: the as-of date)")
    parser.add_argument("--max-windows", type=int, default=None)
    parser.add_argument("--min-history-days", type=int, default=HISTORY_DAYS,
                        help="Days of history a window needs before its start "
                             f"(default {HISTORY_DAYS}: the 52 weeks of the demand classification)")
    parser.add_argument("--exclude-dates", type=str,
                        default=os.getenv("PILOT_WINDOWS_EXCLUDE", ""),
                        help="Comma-separated dates; windows containing one are left out "
                             "of the summary (default: env PILOT_WINDOWS_EXCLUDE)")
    parser.add_argument("--scenario", type=str, default="realistic")
    parser.add_argument("--jobs", type=int, default=1,
                        help="Windows run in parallel (one process each)")
    parser.add_argument("--out", type=str, default="pilot_windows.csv")
    args = parser.parse_args()

    if config.demand_policy != "pattern":
        log.warning("DEMAND_POLICY is not 'pattern': the windows evaluate another policy "
                    "than the pilot's.")
    exclude = parse_dates(args.exclude_dates)
    end = date.fromisoformat(args.end) if args.end else get_effective_today()

    repo = Repository()
    first = pd.read_sql("SELECT MIN(posting_date) AS d FROM movements", repo.engine)["d"].iloc[0]
    repo.close()
    first = pd.to_datetime(first).date()
    # The classification of a window starting on s uses the 52 weeks s−364 … s−1.
    windows = windows_back(end, args.window_days, first + timedelta(days=args.min_history_days))
    if args.max_windows:
        windows = windows[:args.max_windows]
    if not windows:
        log.error(f"No {args.window_days}-day window with {args.min_history_days} days of history "
                  f"before it (movements from {first}).")
        sys.exit(1)
    log.info(f"{len(windows)} windows of {args.window_days} days, movements from {first}; "
             f"excluded from the summary if they contain: {exclude or 'none'}")

    tasks = [(s, e, args.scenario) for s, e in windows]
    if args.jobs > 1:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            rows = list(pool.map(run_window, *zip(*tasks)))
    else:
        rows = [run_window(*t) for t in tasks]

    df = pd.DataFrame(rows).sort_values("window_start", ascending=False)
    hits = [excluded_by(r.window_start, r.window_end, exclude) for r in df.itertuples()]
    df["included"] = [not h for h in hits]
    df["excluded_because"] = [",".join(d.isoformat() for d in h) for h in hits]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    summary = summarize(df)
    summary_path = out.with_name(out.stem + "_summary" + out.suffix)
    summary.to_csv(summary_path, index=False)

    print(df[["window_start", "window_end", "included", "asis_tco_eur", "tobe_tco_eur",
              "savings_pct", "opening_stock_estimated"]].to_string(index=False))
    print(summary.to_string(index=False))
    log.success(f"Windows written to {out.absolute()} and {summary_path.name}")


if __name__ == "__main__":
    main()
