"""
Rule Ablation Study — measure the marginal contribution of each rule.

Methodology: Leave-One-Out (LOO) ablation.
  1. Run the full agent (baseline) → record KPIs
  2. For each rule R_i:
        Disable R_i → run agent → record KPIs
        Compute delta vs baseline = marginal contribution of R_i
  3. Aggregate results into a comparison table

References:
  • Hooker, J.N. (1995). "Testing heuristics: We have it all wrong."
    Journal of Heuristics, 1(1), 33-42.
  • Lipton, Z.C. (2018). "The mythos of model interpretability."
    Communications of the ACM, 61(10), 36-43.
  • Standard practice in ML: leave-one-feature-out for feature importance.

Why this matters for the thesis:
  This study quantifies how much each rule contributes to the agent's
  overall performance. Without it, the reader can't tell whether all 7
  rules are necessary, or if 1-2 are doing all the work. The result is
  a defensible argument that each rule has a measurable purpose.

Usage:
  python scripts/run_rule_ablation.py
  python scripts/run_rule_ablation.py --window-days 60 --scenario realistic
  python scripts/run_rule_ablation.py --out ablation_report.csv
"""
from __future__ import annotations

import argparse
import sys
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from src.agent.replenishment import ReplenishmentAgent
from src.data_layer.repository import Repository
from src.mrp.engine import MRPEngine
from src.rules.engine import RulesEngine
from src.rules.policies import RULES_REGISTRY
from src.utils.cost_estimator import SCENARIOS, get_scenario, CostScenario
from src.utils.kpi import KPICalculator, KPIReport
from src.utils.logger import log

# Import the existing backtest simulators
from scripts.run_validation import (
    simulate_tobe, simulate_asis, _to_df, run_scenario,
)


# ============================================================
# Single ablation run
# ============================================================
@dataclass
class AblationResult:
    """KPI snapshot from one ablation configuration."""
    disabled_rule:  Optional[str]   # None = baseline (all rules active)
    label:          str             # Display name
    n_proposals:    int
    service_level:  float           # cycle service %
    fill_rate:      float
    holding_cost:   float
    stockout_cost:  float
    stockout_days:  int
    tco:            float
    inventory_turns: float
    n_orders:       int


def _run_with_rule_set(
    repo: Repository,
    materials_df: pd.DataFrame,
    start: date,
    end: date,
    scenario: CostScenario,
    disabled_rules: set[str],
    stress_test: bool = False,
) -> tuple[KPIReport, int]:
    """Run To-Be simulation with a specific rule set, return KPIs + proposal count.

    Args:
        stress_test: If True, start with low initial stock (50% of safety stock)
            to force the rules to "work harder" and reveal their contributions.
            Otherwise use 2× safety stock (well-supplied scenario).

    We need a fresh agent instance because RulesEngine reads the rule set at
    construction time.
    """
    # ─── Build a To-Be simulation from scratch, with our custom rules engine ───
    from scripts.run_validation import _FakePO

    state_stock = []
    state_demand = []
    state_orders = []

    materials = repo.get_all_materials()
    materials_by_id = {m.material_id: m for m in materials}
    stock_levels = {}
    pending_orders = {}
    for m in materials:
        mid = m.material_id
        stock_levels[mid] = repo.get_current_stock(mid, as_of=start - timedelta(days=1))
        if stock_levels[mid] == 0:
            ss = float(m.safety_stock or 0)
            # Stress test = start at 50% safety; otherwise 2× safety
            stock_levels[mid] = ss * 0.5 if stress_test else ss * 2
        pending_orders[mid] = []

    demand_lookup = {}
    for m in materials:
        movements = repo.get_all_movements(m.material_id, start=start, end=end)
        for mv in movements:
            if mv.movement_type in ("261", "201", "281"):
                key = (m.material_id, mv.posting_date)
                demand_lookup[key] = demand_lookup.get(key, 0.0) + abs(mv.quantity)

    mrp = MRPEngine(horizon_days=60)
    rules_engine = RulesEngine(disabled_rules=disabled_rules)
    sim_agent = ReplenishmentAgent(repo, mrp, rules_engine)

    total_proposals_generated = 0
    current = start
    review_interval = 7
    days_since_review = 0

    while current <= end:
        # Process arrivals
        for mid, queue in pending_orders.items():
            still_pending = []
            for (arrival, qty) in queue:
                if arrival <= current:
                    stock_levels[mid] += qty
                    state_orders.append({
                        "date": arrival, "material_id": mid,
                        "quantity": qty,
                        "unit_cost": materials_by_id[mid].standard_cost or 0,
                    })
                else:
                    still_pending.append((arrival, qty))
            pending_orders[mid] = still_pending

        # Apply demand
        for m in materials:
            mid = m.material_id
            d = demand_lookup.get((mid, current), 0.0)
            if d > 0:
                requested = d
                delivered = min(requested, stock_levels[mid])
                stock_levels[mid] = max(stock_levels[mid] - requested, 0)
                state_demand.append({
                    "date": current, "material_id": mid,
                    "requested_qty": requested, "delivered_qty": delivered,
                })

        # Snapshot
        for mid, qty in stock_levels.items():
            state_stock.append({
                "date": current, "material_id": mid, "quantity": qty,
            })

        # Periodic agent review with our custom rules engine
        if days_since_review >= review_interval or current == start:
            days_since_review = 0
            sim_agent.perceive(as_of=current)
            sim_agent.beliefs.current_stock = dict(stock_levels)
            sim_agent.beliefs.open_orders = {
                mid: [_FakePO(arr, q) for arr, q in pending_orders.get(mid, [])]
                for mid in stock_levels
            }
            sim_agent.deliberate(as_of=current)
            total_proposals_generated += len(sim_agent.intentions)

            for intention in sim_agent.intentions:
                lt = int(materials_by_id[intention.material_id].lead_time_days or 0)
                arrival = intention.proposed_date + timedelta(days=lt)
                pending_orders[intention.material_id].append(
                    (arrival, float(intention.proposed_qty))
                )
        else:
            days_since_review += 1

        current += timedelta(days=1)

    # ─── Build KPI report ───
    kpi = KPICalculator(
        stock_history=_to_df(state_stock, ["date", "material_id", "quantity"]),
        demand_history=_to_df(state_demand,
                              ["date", "material_id", "requested_qty", "delivered_qty"]),
        orders=_to_df(state_orders,
                      ["date", "material_id", "quantity", "unit_cost"]),
        materials=materials_df,
        holding_rate=scenario.holding,
        stockout_params=scenario.stockout,
    ).report()

    return kpi, total_proposals_generated


# ============================================================
# Main ablation loop
# ============================================================
def run_ablation_study(
    repo: Repository,
    materials_df: pd.DataFrame,
    start: date,
    end: date,
    scenario: CostScenario,
    stress_test: bool = False,
) -> list[AblationResult]:
    """Execute the full leave-one-out study.

    Returns N+1 results: baseline + one for each disabled rule.
    """
    results: list[AblationResult] = []

    # ─── Baseline: all rules active ───
    log.info("Running BASELINE (all rules active)...")
    baseline_kpi, baseline_n = _run_with_rule_set(
        repo, materials_df, start, end, scenario,
        disabled_rules=set(), stress_test=stress_test,
    )
    baseline = AblationResult(
        disabled_rule=None,
        label="BASELINE (all rules)",
        n_proposals=baseline_n,
        service_level=baseline_kpi.cycle_service_level_pct,
        fill_rate=baseline_kpi.fill_rate_pct,
        holding_cost=baseline_kpi.holding_cost_eur,
        stockout_cost=baseline_kpi.stockout_cost_eur,
        stockout_days=baseline_kpi.stockout_days,
        tco=baseline_kpi.total_cost_of_ownership,
        inventory_turns=baseline_kpi.inventory_turns,
        n_orders=baseline_kpi.n_orders,
    )
    results.append(baseline)

    # ─── One ablation per rule ───
    rule_names = sorted({getattr(r, "rule_name", r.__name__) for r in RULES_REGISTRY})

    for rule_name in rule_names:
        log.info(f"Running ABLATION: disabled = {rule_name}")
        try:
            kpi, n_prop = _run_with_rule_set(
                repo, materials_df, start, end, scenario,
                disabled_rules={rule_name},
                stress_test=stress_test,
            )
            results.append(AblationResult(
                disabled_rule=rule_name,
                label=f"without {rule_name}",
                n_proposals=n_prop,
                service_level=kpi.cycle_service_level_pct,
                fill_rate=kpi.fill_rate_pct,
                holding_cost=kpi.holding_cost_eur,
                stockout_cost=kpi.stockout_cost_eur,
                stockout_days=kpi.stockout_days,
                tco=kpi.total_cost_of_ownership,
                inventory_turns=kpi.inventory_turns,
                n_orders=kpi.n_orders,
            ))
        except Exception as e:
            log.error(f"Ablation for {rule_name} failed: {e}")
            results.append(AblationResult(
                disabled_rule=rule_name,
                label=f"without {rule_name} (FAILED)",
                n_proposals=-1,
                service_level=0, fill_rate=0, holding_cost=0,
                stockout_cost=0, stockout_days=-1, tco=0,
                inventory_turns=0, n_orders=0,
            ))

    return results


# ============================================================
# Reporting
# ============================================================
def to_dataframe(results: list[AblationResult]) -> pd.DataFrame:
    """Convert results into a comparison DataFrame with deltas from baseline."""
    baseline = results[0]
    rows = []
    for r in results:
        d_proposals = r.n_proposals - baseline.n_proposals
        d_service = r.service_level - baseline.service_level
        d_holding = r.holding_cost - baseline.holding_cost
        d_stockout = r.stockout_cost - baseline.stockout_cost
        d_tco = r.tco - baseline.tco
        d_stockout_d = r.stockout_days - baseline.stockout_days

        rows.append({
            "configuration":      r.label,
            "disabled_rule":      r.disabled_rule or "(none)",
            "n_proposals":        r.n_proposals,
            "Δ_proposals":        d_proposals,
            "service_level_pct":  round(r.service_level, 2),
            "Δ_service_pp":       round(d_service, 2),
            "fill_rate_pct":      round(r.fill_rate, 2),
            "holding_cost_eur":   round(r.holding_cost, 2),
            "Δ_holding":          round(d_holding, 2),
            "stockout_cost_eur":  round(r.stockout_cost, 2),
            "Δ_stockout_cost":    round(d_stockout, 2),
            "stockout_days":      r.stockout_days,
            "Δ_stockout_days":    d_stockout_d,
            "tco_eur":            round(r.tco, 2),
            "Δ_tco":              round(d_tco, 2),
            "inventory_turns":    round(r.inventory_turns, 2),
        })

    return pd.DataFrame(rows)


def interpret_results(df: pd.DataFrame) -> str:
    """Human-readable narrative interpretation of which rules matter most."""
    baseline = df[df["disabled_rule"] == "(none)"].iloc[0]
    ablations = df[df["disabled_rule"] != "(none)"].copy()

    if ablations.empty:
        return "(No ablation runs to interpret)"

    # Worst service-level degradation
    ablations["abs_service_drop"] = -ablations["Δ_service_pp"]
    most_service_critical = ablations.nlargest(3, "abs_service_drop")

    # Biggest TCO increase
    most_tco_critical = ablations.nlargest(3, "Δ_tco")

    # Biggest stockout impact
    most_stockout_critical = ablations.nlargest(3, "Δ_stockout_days")

    lines = ["", "═" * 70, "INTERPRETATION", "═" * 70, ""]

    lines.append("📊 Baseline (all rules active):")
    lines.append(f"   Service level: {baseline['service_level_pct']:.2f}%")
    lines.append(f"   Holding cost: €{baseline['holding_cost_eur']:,.0f}")
    lines.append(f"   TCO: €{baseline['tco_eur']:,.0f}")
    lines.append(f"   Stockout days: {baseline['stockout_days']}")
    lines.append(f"   Proposals: {baseline['n_proposals']}")
    lines.append("")

    lines.append("🔴 Rules whose removal HURTS service level most:")
    for _, row in most_service_critical.iterrows():
        delta = row["Δ_service_pp"]
        if abs(delta) < 0.01:
            continue
        lines.append(f"   • {row['disabled_rule']:25s} → Δ service: {delta:+.2f}pp")
    lines.append("")

    lines.append("💸 Rules whose removal INCREASES total cost (TCO) most:")
    for _, row in most_tco_critical.iterrows():
        if row["Δ_tco"] < 100:
            continue
        lines.append(f"   • {row['disabled_rule']:25s} → Δ TCO: €{row['Δ_tco']:+,.0f}")
    lines.append("")

    lines.append("📉 Rules whose removal INCREASES stockouts most:")
    for _, row in most_stockout_critical.iterrows():
        if row["Δ_stockout_days"] <= 0:
            continue
        lines.append(f"   • {row['disabled_rule']:25s} → Δ stockout days: {row['Δ_stockout_days']:+d}")
    lines.append("")

    # Find any "dead weight" rules
    dead_weight = ablations[
        (ablations["Δ_service_pp"].abs() < 0.1)
        & (ablations["Δ_tco"].abs() < baseline["tco_eur"] * 0.01)
        & (ablations["Δ_stockout_days"] == 0)
    ]
    if not dead_weight.empty:
        lines.append("⚠️  Rules with negligible measurable impact in this window:")
        for _, row in dead_weight.iterrows():
            lines.append(f"   • {row['disabled_rule']}")
        lines.append("   (May still matter in other periods or scenarios — "
                     "do not remove without further investigation.)")
        lines.append("")

    return "\n".join(lines)


# ============================================================
# CLI
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="Leave-one-out ablation study of agent rules.",
    )
    parser.add_argument("--window-days", type=int, default=60,
                        help="Backtest window in days (default 60)")
    parser.add_argument("--end", type=str, default=None,
                        help="End date YYYY-MM-DD (default: today-1)")
    parser.add_argument("--scenario", type=str, default="realistic",
                        choices=list(SCENARIOS.keys()),
                        help="Cost scenario (default: realistic)")
    parser.add_argument("--stress-test", action="store_true",
                        help="Start the simulation with low initial stock "
                             "(50%% of safety stock instead of 200%%). "
                             "This forces rules to work harder and reveals "
                             "their contributions more clearly.")
    parser.add_argument("--out", type=str, default="ablation_report.csv",
                        help="Output filename for the comparison CSV")
    args = parser.parse_args()

    end = date.fromisoformat(args.end) if args.end else date.today() - timedelta(days=1)
    start = end - timedelta(days=args.window_days)

    log.info(f"Ablation study: {start} → {end} ({args.window_days} days)")
    log.info(f"Scenario: {args.scenario}")
    if args.stress_test:
        log.info("⚡ Stress-test mode: starting with low initial stock")

    repo = Repository()
    materials_df = pd.read_sql("SELECT * FROM materials", repo.engine)
    scenario = get_scenario(args.scenario)

    log.info(f"This will run {len(RULES_REGISTRY) + 1} backtests "
             f"(1 baseline + {len(RULES_REGISTRY)} ablations). "
             f"Estimated time: {(len(RULES_REGISTRY) + 1) * 30}-{(len(RULES_REGISTRY) + 1) * 90} seconds.")

    results = run_ablation_study(
        repo, materials_df, start, end, scenario,
        stress_test=args.stress_test,
    )

    df = to_dataframe(results)

    # Print
    print("\n" + "═" * 70)
    print("  RULE ABLATION STUDY RESULTS")
    print("═" * 70)
    print(df.to_string(index=False))

    # Interpret
    print(interpret_results(df))

    # Save
    out_path = Path(args.out)
    df.to_csv(out_path, index=False)
    log.success(f"Ablation report saved to {out_path.absolute()}")

    repo.close()


if __name__ == "__main__":
    main()
