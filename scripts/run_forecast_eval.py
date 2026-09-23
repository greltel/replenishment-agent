"""
Walk-forward evaluation of the three forecasting methods over ALL materials.

Produces the numbers behind thesis Tables 4.12 / 4.13:
  • per-method accuracy (WMAPE, MAE, RMSE, bias) at the WEEKLY level —
    the level at which the agent's weekly review actually uses the forecast
    and the recommended basis for intermittent demand (Syntetos & Boylan
    2005: plain MAPE explodes on near-zero actuals);
  • the best method per material (lowest WMAPE) and its distribution per
    ABC class.

Rolling-origin validation (Bergmeir, Hyndman & Koo 2018): 5 folds, train
8 weeks → test 2 weeks, identical to the "Πρόβλεψη ζήτησης" tab.

Usage:
    python scripts/run_forecast_eval.py [--min-weeks 20] [--out forecast_report.csv]

Outputs:
    forecast_report.csv          one row per material × method
    forecast_report_summary.csv  one row per method (means / medians) plus the
                                 best-method counts per ABC class
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from src.data_layer.repository import Repository
from src.utils.as_of_date import get_effective_today
from src.utils.forecasting import (
    best_method, compare_methods, consumption_to_daily_series,
)
from src.utils.logger import log

METHODS = ["simple_average", "moving_average", "exponential_smoothing"]
LABELS = {"simple_average": "Simple Average", "moving_average": "Moving Average (4 wk)",
          "exponential_smoothing": "Exponential Smoothing (α=0.3)"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Walk-forward forecast evaluation, all materials")
    parser.add_argument("--min-weeks", type=int, default=20,
                        help="Skip materials with fewer weekly buckets of history (default 20)")
    parser.add_argument("--out", default="forecast_report.csv")
    args = parser.parse_args()

    repo = Repository()
    as_of = get_effective_today()
    materials = repo.get_all_materials()
    log.info(f"Forecast evaluation for {len(materials)} materials (as-of {as_of})")

    rows = []
    skipped = 0
    for m in materials:
        history = repo.get_consumption_history(m.material_id, days=365, as_of=as_of)
        if not history:
            skipped += 1
            continue
        daily = consumption_to_daily_series(history, horizon_back_days=365, as_of=as_of)
        # trim the leading zero period of a new material
        first_nonzero = daily[daily > 0]
        if first_nonzero.empty:
            skipped += 1
            continue
        daily = daily[daily.index >= first_nonzero.index[0]]
        weekly = daily.resample("W").sum()
        if len(weekly) < args.min_weeks or float(weekly.sum()) <= 0:
            skipped += 1
            continue
        # A phased-out part with no demand in the evaluation region would
        # score a meaningless WMAPE of 0 (0 predicted vs 0 actual): skip it.
        if float(weekly.iloc[-(5 * 2):].sum()) <= 0:
            skipped += 1
            continue
        comparison = compare_methods(
            weekly, train_window=min(8, len(weekly) // 2), test_window=2, n_folds=5,
            method_kwargs={"moving_average": {"window": 4}},
        )
        best = best_method(comparison, metric="wmape")
        for _, r in comparison.iterrows():
            rows.append({
                "material_id": m.material_id, "abc_class": m.abc_class,
                "n_weeks": len(weekly), "mean_weekly_demand": round(float(weekly.mean()), 2),
                "method": r["method"], "mae": r["mae"], "rmse": r["rmse"],
                "mape": r["mape"], "wmape": r["wmape"], "bias": r["bias"],
                "n_folds": r["n_folds"], "is_best": r["method"] == best,
            })

    df = pd.DataFrame(rows)
    if df.empty:
        log.error("No material had enough history for the evaluation")
        return
    df.to_csv(args.out, index=False)

    n_mat = df["material_id"].nunique()
    summary = (df.groupby("method")
                 .agg(n_materials=("material_id", "nunique"),
                      wmape_mean=("wmape", "mean"), wmape_median=("wmape", "median"),
                      mae_mean=("mae", "mean"), rmse_mean=("rmse", "mean"),
                      mape_mean=("mape", "mean"), bias_mean=("bias", "mean"),
                      n_best=("is_best", "sum"))
                 .reindex(METHODS).reset_index())
    summary["best_share_pct"] = summary["n_best"] / n_mat * 100

    best_by_abc = (df[df["is_best"]].groupby(["abc_class", "method"]).size()
                     .unstack(fill_value=0).reindex(columns=METHODS, fill_value=0))
    best_by_abc["n_materials"] = best_by_abc.sum(axis=1)

    summary_path = Path(args.out).with_name(Path(args.out).stem + "_summary.csv")
    with open(summary_path, "w", encoding="utf-8") as fh:
        summary.round(2).to_csv(fh, index=False)
        fh.write("\n# best method per ABC class (count of materials)\n")
        best_by_abc.to_csv(fh)

    print("\n" + "=" * 70)
    print(f"  Walk-forward validation — weekly level, 5 folds (8 → 2 weeks)")
    print(f"  Materials evaluated: {n_mat}  (skipped: {skipped}: < {args.min_weeks} weeks of history or no demand in the test weeks)")
    print("=" * 70)
    print(f"  {'Method':<32}{'WMAPE mean':>12}{'WMAPE med.':>12}{'MAE':>9}{'RMSE':>9}{'Bias':>8}{'best':>7}")
    for _, r in summary.iterrows():
        print(f"  {LABELS[r['method']]:<32}{r['wmape_mean']:>11.1f}%{r['wmape_median']:>11.1f}%"
              f"{r['mae_mean']:>9.2f}{r['rmse_mean']:>9.2f}{r['bias_mean']:>8.2f}"
              f"{int(r['n_best']):>4} ({r['best_share_pct']:.0f}%)")
    print("\n  Best method per ABC class:")
    print(best_by_abc.to_string())
    print(f"\n  Reports: {args.out}, {summary_path}")


if __name__ == "__main__":
    main()
