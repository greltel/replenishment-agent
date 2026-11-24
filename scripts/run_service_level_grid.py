"""
Backtest of the To-Be agent for several target service levels per ABC class
(SERVICE_LEVEL_BY_ABC, src/mrp/service_level.py), against the same As-Is.

Each level set is one full To-Be run of run_validation (same window, same
cost scenario, same evaluation); only the safety stock the agent computes
changes. The result is one CSV in long format: per level set, the totals,
the ABC classes and the demand patterns, As-Is and To-Be side by side, and
the value of the safety stock the agent would hold on the last day of the
window.

    python scripts/run_service_level_grid.py --out reports/pilot/service_level_grid.csv
    python scripts/run_service_level_grid.py --levels "" "A=0.98,B=0.95,C=0.90" --jobs 2

Default level sets: uniform 98 % (the agent's default — reproduces
validation_report.csv), the usual practice A 98 / B 95 / C 90, and uniform
95 % and 90 %, so that the effect of differentiating by class can be told
apart from the effect of a lower level overall.

Run time on the pilot data: about 15 minutes per level set and job; each
job needs about 3.5 GB of memory (--jobs 2: about 7 GB).
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.run_validation import kpis_from_state, simulate_asis, simulate_tobe  # noqa: E402
from src.agent.base import AgentDesires  # noqa: E402
from src.config import config  # noqa: E402
from src.data_layer.models import CONSUMPTION_MOVEMENT_TYPES  # noqa: E402
from src.data_layer.repository import Repository  # noqa: E402
from src.mrp import demand_pattern as dp  # noqa: E402
from src.mrp import service_level as sl  # noqa: E402
from src.utils.as_of_date import get_effective_today  # noqa: E402
from src.utils.cost_estimator import get_scenario  # noqa: E402
from src.utils.logger import log  # noqa: E402

DEFAULT_LEVEL_SETS = [
    "",                                 # uniform 98 % (AgentDesires default)
    "A=0.98,B=0.95,C=0.90",             # the usual practice
    "A=0.95,B=0.95,C=0.95",
    "A=0.90,B=0.90,C=0.90",
]

# KPIReport attribute / report_by key → column of the CSV
_TOTAL_FIELDS = {
    "cycle_service_level_pct": "cycle_service_pct",
    "fill_rate_pct":           "fill_rate_pct",
    "avg_inventory_eur":       "avg_inventory_eur",
    "holding_cost_eur":        "holding_eur",
    "stockout_cost_eur":       "stockout_eur",
    "lost_sales_eur":          "lost_sales_eur",
    "ordering_cost_eur":       "ordering_eur",
    "n_orders":                "n_orders",
    "total_cost_of_ownership": "tco_eur",
}
_GROUP_FIELDS = {
    "cycle_service_level": "cycle_service_pct",
    "fill_rate":           "fill_rate_pct",
    "avg_inventory":       "avg_inventory_eur",
    "holding_cost":        "holding_eur",
    "stockout_cost":       "stockout_eur",
    "lost_sales":          "lost_sales_eur",
    "ordering_cost":       "ordering_eur",
    "n_orders":            "n_orders",
    "backorder_lines":     "backorder_lines",
    "tco":                 "tco_eur",
}


def label_of(spec: str) -> str:
    desires = AgentDesires(service_level_by_abc=sl.parse_service_levels(spec))
    return sl.describe(desires.service_level_by_abc, desires.target_service_level)


def _rows(report, side: str) -> list[dict]:
    """Totals, ABC classes and demand patterns of one KPI report."""
    total = {col: getattr(report, attr) for attr, col in _TOTAL_FIELDS.items()}
    total["backorder_lines"] = (report.backorders or {}).get("lines")
    rows = [{"side": side, "group_type": "total", "group": "ALL", "n_materials": None, **total}]
    for group_type, groups in (("abc", report.by_abc_class),
                               ("pattern", report.by_demand_pattern)):
        for name, kpis in sorted((groups or {}).items()):
            rows.append({"side": side, "group_type": group_type, "group": name,
                         "n_materials": kpis.get("n_materials"),
                         **{col: kpis.get(key) for key, col in _GROUP_FIELDS.items()}})
    return rows


def safety_stock_value(repo: Repository, materials_df: pd.DataFrame, as_of: date,
                       spec: str) -> dict[str, float]:
    """Value (€) of the safety stock the agent computes at `as_of` for the
    level set, per ABC class and in total (DEMAND_POLICY=pattern formulas;
    MARC-EISBE wins, as in ReplenishmentAgent.deliberate)."""
    window_start = as_of - timedelta(days=dp.HISTORY_DAYS - 1)
    mv = pd.read_sql(
        "SELECT material_id, posting_date, movement_type, quantity FROM movements "
        "WHERE posting_date >= :s AND posting_date <= :e",
        repo.engine, params={"s": window_start.isoformat(), "e": as_of.isoformat()})
    mv = mv[mv["movement_type"].astype(str).isin(CONSUMPTION_MOVEMENT_TYPES)]
    profiles = dp.profiles_from_frame(mv, as_of, materials_df["material_id"])
    desires = AgentDesires(service_level_by_abc=sl.parse_service_levels(spec))
    out: dict[str, float] = {}
    for m in materials_df.itertuples(index=False):
        if m.ss_source == "MARC.EISBE":
            ss = float(m.safety_stock or 0.0)
        else:
            ss = dp.safety_stock_for(profiles[m.material_id], m.lead_time_days,
                                     desires.service_level_for(m.abc_class))
        value = ss * float(m.standard_cost or 0.0)
        out[m.abc_class or "-"] = out.get(m.abc_class or "-", 0.0) + value
        out["ALL"] = out.get("ALL", 0.0) + value
    return {k: round(v, 2) for k, v in out.items()}


def run_level_set(spec: str, start: date, end: date, scenario_name: str,
                  with_asis: bool) -> list[dict]:
    """One To-Be run (and, for the first level set, the As-Is run)."""
    levels = sl.parse_service_levels(spec)
    label = label_of(spec)
    log.info(f"Service levels {label}: To-Be backtest {start} → {end}")
    repo = Repository()
    materials_df = pd.read_sql("SELECT * FROM materials", repo.engine)
    scenario = get_scenario(scenario_name)
    rows: list[dict] = []
    if with_asis:
        asis = simulate_asis(repo, start, end, by_pattern=True)
        rows += _rows(kpis_from_state(asis, materials_df, scenario, start, end), "As-Is")
    tobe = simulate_tobe(repo, start, end, 60, by_pattern=True, service_levels=levels)
    rows += _rows(kpis_from_state(tobe, materials_df, scenario, start, end), "To-Be")
    ss = safety_stock_value(repo, materials_df, end, spec)
    repo.close()
    for r in rows:
        r["levels"] = label if r["side"] == "To-Be" else "—"
        r["spec"] = spec if r["side"] == "To-Be" else ""
        if r["side"] == "To-Be" and r["group_type"] in ("total", "abc"):
            r["ss_value_eur_at_end"] = ss.get(r["group"])
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--levels", nargs="+", default=DEFAULT_LEVEL_SETS,
                        help='Level sets, each like "A=0.98,B=0.95,C=0.90"; "" = uniform 98%%')
    parser.add_argument("--window-days", type=int, default=60)
    parser.add_argument("--end", type=str, default=None,
                        help="End date YYYY-MM-DD (default: the dataset's as-of date)")
    parser.add_argument("--scenario", type=str, default="realistic")
    parser.add_argument("--jobs", type=int, default=1,
                        help="Level sets run in parallel (one process each)")
    parser.add_argument("--out", type=str, default="service_level_grid.csv")
    args = parser.parse_args()

    if config.demand_policy != "pattern":
        log.warning("DEMAND_POLICY is not 'pattern': the agent's safety stock comes from the "
                    "master data, so the level sets change nothing in the backtest "
                    "(re-run the enrichment with SERVICE_LEVEL_BY_ABC instead).")
    for spec in args.levels:
        sl.parse_service_levels(spec)          # fail before hours of simulation

    end = date.fromisoformat(args.end) if args.end else get_effective_today()
    start = end - timedelta(days=args.window_days - 1)
    tasks = [(spec, start, end, args.scenario, i == 0) for i, spec in enumerate(args.levels)]
    if args.jobs > 1:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            results = list(pool.map(run_level_set, *zip(*tasks)))
    else:
        results = [run_level_set(*t) for t in tasks]

    df = pd.DataFrame([r for rows in results for r in rows])
    cols = ["side", "levels", "spec", "group_type", "group", "n_materials",
            "cycle_service_pct", "fill_rate_pct", "avg_inventory_eur", "holding_eur",
            "stockout_eur", "lost_sales_eur", "ordering_eur", "n_orders", "backorder_lines",
            "tco_eur", "ss_value_eur_at_end"]
    df = df.reindex(columns=cols)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)

    totals = df[df["group_type"] == "total"][["side", "levels", "tco_eur", "holding_eur",
                                               "lost_sales_eur", "fill_rate_pct",
                                               "backorder_lines", "ss_value_eur_at_end"]]
    print(totals.to_string(index=False))
    log.success(f"Service-level comparison written to {out.absolute()}")


if __name__ == "__main__":
    main()
