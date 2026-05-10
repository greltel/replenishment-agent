"""
Backtest / Validation script — the heart of the thesis evaluation chapter.

Replays the historical period in two parallel scenarios:
  • As-Is:  follow the actual decisions captured in the data
  • To-Be:  what the agent WOULD have decided each day

Computes KPIs for both and writes a comparison report.

Three cost scenarios available:
  • conservative (~12% holding rate)
  • realistic    (~20% holding rate, default)
  • aggressive   (~28% holding rate)

Plus optional sensitivity analysis varying lead time, demand, and holding rate.

Usage:
    python scripts/run_validation.py
    python scripts/run_validation.py --window-days 90 --scenario realistic
    python scripts/run_validation.py --sensitivity
    python scripts/run_validation.py --all-scenarios
"""
from __future__ import annotations

import argparse
import sys
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from src.agent.replenishment import ReplenishmentAgent
from src.config import config
from src.data_layer.repository import Repository
from src.mrp.engine import MRPEngine
from src.rules.engine import RulesEngine
from src.utils.cost_estimator import (
    SCENARIOS, get_scenario, CostScenario,
    HoldingCostComponents, StockoutCostParams,
)
from src.utils.kpi import (
    KPICalculator, KPIReport, compare_scenarios, sensitivity_pivot,
)
from src.utils.logger import log


# ============================================================
# Backtest simulator
# ============================================================
@dataclass
class SimulationState:
    """Mutable state tracked through the simulation."""
    stock_history: list = None
    demand_history: list = None
    orders_placed: list = None

    def __post_init__(self):
        self.stock_history = self.stock_history or []
        self.demand_history = self.demand_history or []
        self.orders_placed = self.orders_placed or []


def _to_df(rows: list, columns: list) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows)


def simulate_asis(
    repo: Repository,
    start: date,
    end: date,
    lead_time_multiplier: float = 1.0,
    demand_multiplier: float = 1.0,
) -> SimulationState:
    """As-Is: replay actual movements + actual PO receipts."""
    state = SimulationState()
    materials = repo.get_all_materials()

    for m in materials:
        mid = m.material_id
        stock = repo.get_current_stock(mid, as_of=start - timedelta(days=1))
        if stock == 0:
            stock = float(m.safety_stock or 0) * 2

        movements = repo.get_all_movements(mid, start=start, end=end)
        movements = sorted(movements, key=lambda x: x.posting_date)

        current = start
        movement_idx = 0
        while current <= end:
            while (movement_idx < len(movements)
                   and movements[movement_idx].posting_date <= current):
                mv = movements[movement_idx]
                qty = mv.quantity * (demand_multiplier if mv.quantity < 0 else 1.0)
                stock += qty

                if mv.movement_type in ("261", "201", "281"):
                    requested = abs(qty)
                    delivered = min(requested, max(stock + abs(qty), 0))
                    state.demand_history.append({
                        "date":          current,
                        "material_id":   mid,
                        "requested_qty": requested,
                        "delivered_qty": delivered,
                    })
                elif mv.movement_type == "101":
                    state.orders_placed.append({
                        "date":        current,
                        "material_id": mid,
                        "quantity":    qty,
                        "unit_cost":   m.standard_cost or 0,
                    })

                movement_idx += 1

            state.stock_history.append({
                "date":        current,
                "material_id": mid,
                "quantity":    max(stock, 0),
            })
            current += timedelta(days=1)

    return state


def simulate_tobe(
    repo: Repository,
    start: date,
    end: date,
    horizon: int = 60,
    lead_time_multiplier: float = 1.0,
    demand_multiplier: float = 1.0,
) -> SimulationState:
    """To-Be: agent runs periodically and may issue orders."""
    state = SimulationState()
    materials = repo.get_all_materials()
    materials_by_id = {m.material_id: m for m in materials}

    stock_levels: dict[str, float] = {}
    pending_orders: dict[str, list[tuple[date, float]]] = {}
    for m in materials:
        mid = m.material_id
        stock_levels[mid] = repo.get_current_stock(mid, as_of=start - timedelta(days=1))
        if stock_levels[mid] == 0:
            stock_levels[mid] = float(m.safety_stock or 0) * 2
        pending_orders[mid] = []

    # Pre-fetch actual demand
    demand_lookup: dict[tuple[str, date], float] = {}
    for m in materials:
        movements = repo.get_all_movements(m.material_id, start=start, end=end)
        for mv in movements:
            if mv.movement_type in ("261", "201", "281"):
                key = (m.material_id, mv.posting_date)
                demand_lookup[key] = (
                    demand_lookup.get(key, 0.0) + abs(mv.quantity) * demand_multiplier
                )

    mrp = MRPEngine(horizon_days=horizon)
    rules = RulesEngine()
    agent = ReplenishmentAgent(repo, mrp, rules)

    current = start
    review_interval = 7
    days_since_review = 0

    while current <= end:
        # 1. Process pending arrivals
        for mid, queue in pending_orders.items():
            still_pending = []
            for (arrival, qty) in queue:
                if arrival <= current:
                    stock_levels[mid] += qty
                    state.orders_placed.append({
                        "date":        arrival,
                        "material_id": mid,
                        "quantity":    qty,
                        "unit_cost":   materials_by_id[mid].standard_cost or 0,
                    })
                else:
                    still_pending.append((arrival, qty))
            pending_orders[mid] = still_pending

        # 2. Apply demand
        for m in materials:
            mid = m.material_id
            d = demand_lookup.get((mid, current), 0.0)
            if d > 0:
                requested = d
                delivered = min(requested, stock_levels[mid])
                stock_levels[mid] = max(stock_levels[mid] - requested, 0)
                state.demand_history.append({
                    "date":          current,
                    "material_id":   mid,
                    "requested_qty": requested,
                    "delivered_qty": delivered,
                })

        # 3. Snapshot
        for mid, qty in stock_levels.items():
            state.stock_history.append({
                "date":        current,
                "material_id": mid,
                "quantity":    qty,
            })

        # 4. Periodic review
        if days_since_review >= review_interval or current == start:
            days_since_review = 0
            agent.perceive(as_of=current)
            agent.beliefs.current_stock = dict(stock_levels)
            agent.beliefs.open_orders = {
                mid: [_FakePO(arrival, qty)
                      for arrival, qty in pending_orders.get(mid, [])]
                for mid in stock_levels
            }
            agent.deliberate(as_of=current)

            for intention in agent.intentions:
                effective_lt = (
                    int(materials_by_id[intention.material_id].lead_time_days or 0)
                    * lead_time_multiplier
                )
                arrival = intention.proposed_date + timedelta(days=int(effective_lt))
                pending_orders[intention.material_id].append(
                    (arrival, float(intention.proposed_qty))
                )
        else:
            days_since_review += 1

        current += timedelta(days=1)

    return state


class _FakePO:
    def __init__(self, expected_date: date, quantity: float):
        self.expected_date = expected_date
        self.quantity = quantity


# ============================================================
# Single-scenario backtest
# ============================================================
def run_scenario(
    repo: Repository,
    materials_df: pd.DataFrame,
    start: date,
    end: date,
    scenario: CostScenario,
    lead_time_multiplier: float = 1.0,
    demand_multiplier: float = 1.0,
) -> tuple[KPIReport, KPIReport]:
    """Run As-Is and To-Be for a given cost scenario, return both reports."""
    log.info(f"Running As-Is for scenario '{scenario.name}'...")
    asis = simulate_asis(repo, start, end, lead_time_multiplier, demand_multiplier)

    log.info(f"Running To-Be for scenario '{scenario.name}'...")
    tobe = simulate_tobe(repo, start, end, 60, lead_time_multiplier, demand_multiplier)

    asis_kpi = KPICalculator(
        stock_history=_to_df(asis.stock_history, ["date", "material_id", "quantity"]),
        demand_history=_to_df(asis.demand_history,
                                ["date", "material_id", "requested_qty", "delivered_qty"]),
        orders=_to_df(asis.orders_placed,
                       ["date", "material_id", "quantity", "unit_cost"]),
        materials=materials_df,
        holding_rate=scenario.holding,
        stockout_params=scenario.stockout,
    ).report()

    tobe_kpi = KPICalculator(
        stock_history=_to_df(tobe.stock_history, ["date", "material_id", "quantity"]),
        demand_history=_to_df(tobe.demand_history,
                                ["date", "material_id", "requested_qty", "delivered_qty"]),
        orders=_to_df(tobe.orders_placed,
                       ["date", "material_id", "quantity", "unit_cost"]),
        materials=materials_df,
        holding_rate=scenario.holding,
        stockout_params=scenario.stockout,
    ).report()

    return asis_kpi, tobe_kpi


# ============================================================
# Reporting
# ============================================================
def print_comparison_report(
    asis: KPIReport, tobe: KPIReport, scenario_name: str = ""
) -> pd.DataFrame:
    """Print and return the comparison DataFrame."""
    df = compare_scenarios(asis, tobe)

    print(f"\n{'═' * 70}")
    print(f"  Scenario: {scenario_name.upper()}")
    print(f"{'═' * 70}")

    # Group by category for prettier output
    sl_metrics = ["cycle_service_level_pct", "fill_rate_pct", "stockout_days"]
    cost_metrics = ["holding_cost_eur", "capital_cost_eur", "warehouse_cost_eur",
                    "obsolescence_cost_eur", "stockout_cost_eur",
                    "lost_sales_eur", "expedite_premium_eur",
                    "total_cost_of_ownership"]
    op_metrics = ["inventory_turns", "avg_inventory_eur", "days_of_cover_avg",
                  "n_orders", "avg_order_size"]

    def _print_section(title: str, metrics: list):
        print(f"\n  ── {title} ──")
        sub = df[df["metric"].isin(metrics)]
        if not sub.empty:
            print(sub.to_string(index=False))

    _print_section("Service-Level KPIs", sl_metrics)
    _print_section("Cost KPIs (€)", cost_metrics)
    _print_section("Operational KPIs", op_metrics)

    # Per-ABC breakdown if present
    if asis.by_abc_class or tobe.by_abc_class:
        print(f"\n  ── Per ABC Class ──")
        _print_abc_breakdown(asis.by_abc_class, tobe.by_abc_class)

    return df


def _print_abc_breakdown(asis_abc: dict, tobe_abc: dict) -> None:
    classes = sorted(set(asis_abc.keys()) | set(tobe_abc.keys()))
    rows = []
    for cls in classes:
        a = asis_abc.get(cls, {})
        t = tobe_abc.get(cls, {})
        rows.append({
            "ABC":            cls,
            "n_materials":    a.get("n_materials") or t.get("n_materials"),
            "service_asis":   a.get("cycle_service_level"),
            "service_tobe":   t.get("cycle_service_level"),
            "holding_asis":   a.get("holding_cost"),
            "holding_tobe":   t.get("holding_cost"),
            "stockout_asis":  a.get("stockout_cost"),
            "stockout_tobe":  t.get("stockout_cost"),
        })
    if rows:
        print(pd.DataFrame(rows).to_string(index=False))


# ============================================================
# Sensitivity analysis
# ============================================================
def run_sensitivity_analysis(
    repo: Repository,
    materials_df: pd.DataFrame,
    start: date,
    end: date,
    base_scenario: CostScenario,
) -> pd.DataFrame:
    """Vary key parameters and report how TCO responds.

    Variations:
      • Lead time:    0.8x, 1.0x, 1.2x
      • Demand:       0.9x, 1.0x, 1.1x
      • Holding rate: -20%, base, +20%
    """
    log.info("Running sensitivity analysis (9 backtests, ~3-5 minutes)...")

    variations = [
        # (label, lt_mult, demand_mult, holding_mult)
        ("base",                    1.0, 1.0, 1.0),
        ("lt_-20%",                 0.8, 1.0, 1.0),
        ("lt_+20%",                 1.2, 1.0, 1.0),
        ("demand_-10%",             1.0, 0.9, 1.0),
        ("demand_+10%",             1.0, 1.1, 1.0),
        ("holding_-20%",            1.0, 1.0, 0.8),
        ("holding_+20%",            1.0, 1.0, 1.2),
        ("worst_case",              1.2, 1.1, 1.2),
        ("best_case",               0.8, 0.9, 0.8),
    ]

    results = []
    for label, lt_m, dm_m, hr_m in variations:
        # Build perturbed scenario
        scen = deepcopy(base_scenario)
        scen.holding.capital_cost_rate *= hr_m
        scen.holding.warehouse_rate    *= hr_m
        scen.holding.obsolescence_rate *= hr_m
        scen.holding.insurance_rate    *= hr_m
        scen.holding.shrinkage_rate    *= hr_m

        try:
            asis, tobe = run_scenario(
                repo, materials_df, start, end, scen,
                lead_time_multiplier=lt_m,
                demand_multiplier=dm_m,
            )
            results.append({
                "variation":      label,
                "asis_tco":       asis.total_cost_of_ownership,
                "tobe_tco":       tobe.total_cost_of_ownership,
                "tco_savings":    asis.total_cost_of_ownership - tobe.total_cost_of_ownership,
                "asis_service":   asis.cycle_service_level_pct,
                "tobe_service":   tobe.cycle_service_level_pct,
                "asis_stockouts": asis.stockout_days,
                "tobe_stockouts": tobe.stockout_days,
            })
        except Exception as e:
            log.error(f"Variation '{label}' failed: {e}")
            results.append({
                "variation": label, "error": str(e),
            })

    return pd.DataFrame(results)


# ============================================================
# Main
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="Backtest As-Is vs To-Be with realistic cost scenarios."
    )
    parser.add_argument("--window-days", type=int, default=90,
                        help="Backtest window in days (default 90)")
    parser.add_argument("--end", type=str, default=None,
                        help="End date YYYY-MM-DD (default: today-1)")
    parser.add_argument("--scenario", type=str, default="realistic",
                        choices=list(SCENARIOS.keys()),
                        help="Cost scenario (default: realistic)")
    parser.add_argument("--all-scenarios", action="store_true",
                        help="Run all 3 scenarios and produce a comparison")
    parser.add_argument("--sensitivity", action="store_true",
                        help="Run sensitivity analysis (LT, demand, holding)")
    parser.add_argument("--out", type=str, default="validation_report.csv")
    args = parser.parse_args()

    end = date.fromisoformat(args.end) if args.end else date.today() - timedelta(days=1)
    start = end - timedelta(days=args.window_days)

    log.info(f"Backtest window: {start} → {end} ({args.window_days} days)")

    repo = Repository()
    materials_df = pd.read_sql("SELECT * FROM materials", repo.engine)

    out_dir = Path(args.out).parent if Path(args.out).parent != Path("") else Path(".")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_base = Path(args.out).stem  # filename without extension

    # ─── Path 1: All scenarios comparison ───
    if args.all_scenarios:
        log.info("Running ALL scenarios (conservative / realistic / aggressive)...")
        all_results = []
        for scen_name in SCENARIOS:
            scen = get_scenario(scen_name)
            log.info(f"  Scenario: {scen_name} — {scen.description}")
            asis, tobe = run_scenario(repo, materials_df, start, end, scen)
            print_comparison_report(asis, tobe, scen_name)
            all_results.append((f"{scen_name}_asis", asis))
            all_results.append((f"{scen_name}_tobe", tobe))

        pivot = sensitivity_pivot(all_results)
        all_path = out_dir / f"{out_base}_all_scenarios.csv"
        pivot.to_csv(all_path, index=False)
        log.success(f"Cross-scenario comparison saved to {all_path.absolute()}")

        print(f"\n{'═' * 70}")
        print("  Cross-Scenario Summary (key metrics)")
        print(f"{'═' * 70}")
        print(pivot.to_string(index=False))

    # ─── Path 2: Sensitivity ───
    elif args.sensitivity:
        scen = get_scenario(args.scenario)
        sens_df = run_sensitivity_analysis(repo, materials_df, start, end, scen)
        sens_path = out_dir / f"{out_base}_sensitivity.csv"
        sens_df.to_csv(sens_path, index=False)

        print(f"\n{'═' * 70}")
        print(f"  Sensitivity Analysis (base scenario: {args.scenario})")
        print(f"{'═' * 70}")
        print(sens_df.to_string(index=False))
        log.success(f"Sensitivity report saved to {sens_path.absolute()}")

    # ─── Path 3: Single scenario (default) ───
    else:
        scen = get_scenario(args.scenario)
        log.info(f"Scenario: {args.scenario} — {scen.description}")
        log.info(
            f"  Holding rate breakdown: capital={scen.holding.capital_cost_rate:.0%}, "
            f"warehouse={scen.holding.warehouse_rate:.0%}, "
            f"obsolescence={scen.holding.obsolescence_rate:.0%}, "
            f"total={scen.holding.total_rate:.0%}"
        )
        asis, tobe = run_scenario(repo, materials_df, start, end, scen)
        df = print_comparison_report(asis, tobe, args.scenario)

        out_path = Path(args.out)
        df.to_csv(out_path, index=False)
        log.success(f"Report written to {out_path.absolute()}")

    repo.close()


if __name__ == "__main__":
    main()
