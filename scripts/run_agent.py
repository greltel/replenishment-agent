"""Entry point: run a full agent BDI cycle."""
import argparse
import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.replenishment import ReplenishmentAgent
from src.config import config
from src.data_layer.repository import Repository
from src.mrp.engine import MRPEngine
from src.rules.engine import RulesEngine


def main():
    parser = argparse.ArgumentParser(description="Run the replenishment agent.")
    parser.add_argument("--horizon", type=int, default=config.planning_horizon_days,
                        help="Planning horizon in days")
    parser.add_argument("--method", type=str, default="moving_average",
                        choices=["simple_average", "moving_average", "exponential_smoothing"],
                        help="Demand forecasting method")
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't persist proposals to DB")
    args = parser.parse_args()

    # Wire dependencies
    repo = Repository()
    mrp = MRPEngine(
        horizon_days=args.horizon,
        ordering_cost=config.default_ordering_cost,
        holding_rate=config.default_holding_rate,
    )
    rules = RulesEngine()

    print(f"Active rules: {[r['name'] for r in rules.list_rules()]}")

    agent = ReplenishmentAgent(repo, mrp, rules, forecast_method=args.method)

    # Execute BDI cycle
    intentions = agent.run_cycle() if not args.dry_run else _dry_run(agent)

    # Summary
    print(f"\n=== Agent Run Summary ===")
    print(f"Total proposals:     {len(intentions)}")
    if intentions:
        total_qty = sum(i.proposed_qty for i in intentions)
        total_cost = sum(i.estimated_cost for i in intentions)
        n_expedite = sum(1 for i in intentions if i.expedite)
        n_unique = len(set(i.material_id for i in intentions))
        print(f"Total qty:           {total_qty:,.0f}")
        print(f"Estimated cost (€):  {total_cost:,.2f}")
        print(f"Materials covered:   {n_unique}")
        print(f"Expedite alerts:     {n_expedite}")

    repo.close()
    print("\nDone. Launch the dashboard with: streamlit run dashboard/app.py")


def _dry_run(agent: ReplenishmentAgent):
    """Run perceive + deliberate but skip persisting."""
    agent.perceive()
    agent.deliberate()
    intentions = agent.act(persist=False)
    print("[dry-run] proposals NOT persisted")
    return intentions


if __name__ == "__main__":
    main()
