"""
Backtest / Validation script — the heart of the thesis evaluation chapter.

Replays the historical period in two parallel scenarios:
  • As-Is:  follow the actual decisions captured in the data
  • To-Be:  what the agent WOULD have decided each day

Computes KPIs for both and writes a comparison report.

Usage:
    python scripts/run_validation.py --window-days 90
"""
from __future__ import annotations

import argparse
import sys
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
from src.utils.kpi import KPICalculator, compare_scenarios
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
) -> SimulationState:
    """
    As-Is simulation: replay actual movements + actual PO receipts.
    Reflects how the company really behaved.
    """
    state = SimulationState()
    materials = repo.get_all_materials()

    for m in materials:
        mid = m.material_id
        # Initial stock at start of window
        stock = repo.get_current_stock(mid, as_of=start - timedelta(days=1))
        if stock == 0:
            stock = float(m.safety_stock or 0) * 2  # bootstrap if no history

        movements = repo.get_all_movements(mid, start=start, end=end)
        # Sort by date
        movements = sorted(movements, key=lambda x: x.posting_date)

        # Walk day by day
        current = start
        movement_idx = 0
        while current <= end:
            # Apply movements for this day
            while (movement_idx < len(movements)
                   and movements[movement_idx].posting_date <= current):
                mv = movements[movement_idx]
                stock += mv.quantity   # negative for consumption, positive for receipt

                # Track demand (consumption events)
                if mv.movement_type in ("261", "201", "281"):
                    requested = abs(mv.quantity)
                    delivered = min(requested, max(stock + abs(mv.quantity), 0))
                    state.demand_history.append({
                        "date":          current,
                        "material_id":   mid,
                        "requested_qty": requested,
                        "delivered_qty": delivered,
                    })
                # Track orders received (mvt type 101)
                elif mv.movement_type == "101":
                    state.orders_placed.append({
                        "date":        current,
                        "material_id": mid,
                        "quantity":    mv.quantity,
                        "unit_cost":   m.standard_cost or 0,
                    })

                movement_idx += 1

            # Snapshot daily stock
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
) -> SimulationState:
    """
    To-Be simulation: at each day, the agent runs and may issue orders.
    Demand is replayed from history; orders received based on agent decisions.
    """
    state = SimulationState()
    materials = repo.get_all_materials()
    materials_by_id = {m.material_id: m for m in materials}

    # Initial stock
    stock_levels: dict[str, float] = {}
    pending_orders: dict[str, list[tuple[date, float]]] = {}  # mid -> [(arrival_date, qty)]
    for m in materials:
        mid = m.material_id
        stock_levels[mid] = repo.get_current_stock(mid, as_of=start - timedelta(days=1))
        if stock_levels[mid] == 0:
            stock_levels[mid] = float(m.safety_stock or 0) * 2
        pending_orders[mid] = []

    # Pre-fetch actual demand per (material, date) — the "truth"
    demand_lookup: dict[tuple[str, date], float] = {}
    for m in materials:
        movements = repo.get_all_movements(m.material_id, start=start, end=end)
        for mv in movements:
            if mv.movement_type in ("261", "201", "281"):
                key = (m.material_id, mv.posting_date)
                demand_lookup[key] = demand_lookup.get(key, 0.0) + abs(mv.quantity)

    # Build agent
    mrp = MRPEngine(horizon_days=horizon)
    rules = RulesEngine()
    agent = ReplenishmentAgent(repo, mrp, rules)

    # Walk the window
    current = start
    review_interval = 7   # the agent reviews weekly (to be more realistic)
    days_since_review = 0

    while current <= end:
        # 1. Process pending order arrivals
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

        # 3. Snapshot stock
        for mid, qty in stock_levels.items():
            state.stock_history.append({
                "date":        current,
                "material_id": mid,
                "quantity":    qty,
            })

        # 4. Periodic agent review — issue new orders
        if days_since_review >= review_interval or current == start:
            days_since_review = 0
            # Override beliefs with simulation state
            agent.perceive(as_of=current)
            # Patch current_stock from simulation (not from DB)
            agent.beliefs.current_stock = dict(stock_levels)
            agent.beliefs.open_orders = {
                mid: [_FakePO(arrival, qty)
                      for arrival, qty in pending_orders.get(mid, [])]
                for mid in stock_levels
            }
            agent.deliberate(as_of=current)

            # Convert intentions to pending orders
            for intention in agent.intentions:
                arrival = intention.proposed_date + timedelta(
                    days=int(materials_by_id[intention.material_id].lead_time_days or 0)
                )
                pending_orders[intention.material_id].append(
                    (arrival, float(intention.proposed_qty))
                )
        else:
            days_since_review += 1

        current += timedelta(days=1)

    return state


class _FakePO:
    """Lightweight stand-in for PurchaseOrder to feed the agent during sim."""
    def __init__(self, expected_date: date, quantity: float):
        self.expected_date = expected_date
        self.quantity = quantity


# ============================================================
# Main
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="Backtest As-Is vs To-Be.")
    parser.add_argument("--window-days", type=int, default=90,
                        help="Backtest window in days")
    parser.add_argument("--end", type=str, default=None,
                        help="End date YYYY-MM-DD (default: today-1)")
    parser.add_argument("--out", type=str, default="validation_report.csv")
    args = parser.parse_args()

    end = date.fromisoformat(args.end) if args.end else date.today() - timedelta(days=1)
    start = end - timedelta(days=args.window_days)
    log.info(f"Backtest window: {start} → {end}")

    repo = Repository()
    materials_df = pd.read_sql("SELECT * FROM materials", repo.engine)

    # As-Is
    log.info("Running As-Is simulation...")
    asis = simulate_asis(repo, start, end)

    # To-Be
    log.info("Running To-Be simulation (agent)...")
    tobe = simulate_tobe(repo, start, end)

    # KPI calculation
    asis_kpi = KPICalculator(
        stock_history=_to_df(asis.stock_history, ["date", "material_id", "quantity"]),
        demand_history=_to_df(asis.demand_history,
                                ["date", "material_id", "requested_qty", "delivered_qty"]),
        orders=_to_df(asis.orders_placed,
                       ["date", "material_id", "quantity", "unit_cost"]),
        materials=materials_df,
        holding_rate=config.default_holding_rate,
    ).report()

    tobe_kpi = KPICalculator(
        stock_history=_to_df(tobe.stock_history, ["date", "material_id", "quantity"]),
        demand_history=_to_df(tobe.demand_history,
                                ["date", "material_id", "requested_qty", "delivered_qty"]),
        orders=_to_df(tobe.orders_placed,
                       ["date", "material_id", "quantity", "unit_cost"]),
        materials=materials_df,
        holding_rate=config.default_holding_rate,
    ).report()

    # Comparison
    df = compare_scenarios(asis_kpi, tobe_kpi)
    print("\n=== As-Is vs To-Be ===")
    print(df.to_string(index=False))

    out_path = Path(args.out)
    df.to_csv(out_path, index=False)
    log.success(f"Report written to {out_path.absolute()}")

    repo.close()


if __name__ == "__main__":
    main()
