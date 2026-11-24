"""
Summary of one agent run on the as-of date, for the thesis tables: the
proposals persisted by run_agent.py, the demand patterns of the 52 weeks up
to the as-of date and the value of the safety stock the agent plans with,
per demand pattern and per ABC class.

    python scripts/pilot_agent_summary.py --out reports/pilot/agent_summary.csv
    python scripts/pilot_agent_summary.py --levels uniform --out reports/pilot/agent_summary_uniform.csv

Without --levels the proposals are the ones run_agent.py persisted. With
--levels the agent is run in memory for that level set (SERVICE_LEVEL_BY_ABC
syntax, "uniform" = 98 % for all; about 3 minutes on the pilot) and nothing
is written to the database — to compare level sets on the as-of date.

The safety stock is the one of the active policy (DEMAND_POLICY):
  legacy  → the master data (materials.safety_stock, from the enrichment);
  pattern → the agent's formula per pattern for the target service level of
            the class (SERVICE_LEVEL_BY_ABC), as in ReplenishmentAgent.
            deliberate; MARC-EISBE wins.
The pattern of every material is computed in both cases, so that the two
policies can be compared per pattern.

Output (long format): section, group, metric, value.
"""
from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.base import AgentDesires  # noqa: E402
from src.config import config  # noqa: E402
from src.data_layer.models import CONSUMPTION_MOVEMENT_TYPES  # noqa: E402
from src.data_layer.repository import Repository  # noqa: E402
from src.mrp import demand_pattern as dp  # noqa: E402
from src.mrp import service_level as sl  # noqa: E402
from src.utils.as_of_date import get_effective_today  # noqa: E402
from src.utils.logger import log  # noqa: E402


def _run_agent_in_memory(repo: Repository, as_of, desires: AgentDesires):
    """Perceive + deliberate on the as-of date, nothing persisted: the
    intentions as a proposals frame and the safety stock the agent used."""
    from src.agent.replenishment import ReplenishmentAgent
    from src.mrp.engine import MRPEngine
    from src.rules.engine import RulesEngine
    mrp = MRPEngine(horizon_days=config.planning_horizon_days,
                    ordering_cost=config.default_ordering_cost,
                    holding_rate=config.default_holding_rate)
    agent = ReplenishmentAgent(repo, mrp, RulesEngine())
    agent.desires = desires
    agent.perceive(as_of=as_of)
    agent.deliberate(as_of=as_of)
    props = pd.DataFrame([{"material_id": i.material_id, "proposed_qty": i.proposed_qty,
                           "expedite": int(i.expedite), "estimated_cost": i.estimated_cost}
                          for i in agent.intentions],
                         columns=["material_id", "proposed_qty", "expedite", "estimated_cost"])
    return props, dict(agent.beliefs.safety_stock)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--levels", type=str, default=None,
                        help='Run the agent in memory with these service levels '
                             '(e.g. "uniform" or "A=0.98,B=0.95,C=0.90")')
    parser.add_argument("--out", type=str, default="agent_summary.csv")
    args = parser.parse_args()

    as_of = get_effective_today()
    repo = Repository()
    mats = pd.read_sql("SELECT * FROM materials", repo.engine)
    desires = AgentDesires()
    run_ss: dict[str, float] = {}       # safety stock the in-memory agent used
    if args.levels is None:
        props = pd.read_sql("SELECT material_id, proposed_qty, expedite, estimated_cost "
                            "FROM proposals", repo.engine)
    else:
        desires.service_level_by_abc = sl.parse_service_levels(args.levels)
        props, run_ss = _run_agent_in_memory(repo, as_of, desires)
    start = as_of - timedelta(days=dp.HISTORY_DAYS - 1)
    mv = pd.read_sql("SELECT material_id, posting_date, movement_type, quantity FROM movements "
                     "WHERE posting_date >= :s AND posting_date <= :e", repo.engine,
                     params={"s": start.isoformat(), "e": as_of.isoformat()})
    repo.close()
    mv = mv[mv["movement_type"].astype(str).isin(CONSUMPTION_MOVEMENT_TYPES)]
    profiles = dp.profiles_from_frame(mv, as_of, mats["material_id"])

    by_pattern = config.demand_policy == "pattern"
    mats["demand_pattern_asof"] = mats["material_id"].map(lambda m: profiles[m].pattern)
    mats["sales_qty_52w"] = mats["material_id"].map(lambda m: float(sum(profiles[m].weekly)))
    mats["sales_value_52w"] = mats["sales_qty_52w"] * mats["standard_cost"].fillna(0.0)

    def agent_ss(row) -> float:
        if row.material_id in run_ss:                    # the agent's own value
            return run_ss[row.material_id]
        if not by_pattern or row.ss_source == "MARC.EISBE":
            return float(row.safety_stock or 0.0)
        return dp.safety_stock_for(profiles[row.material_id], row.lead_time_days,
                                   desires.service_level_for(row.abc_class))

    mats["agent_ss"] = [agent_ss(r) for r in mats.itertuples(index=False)]
    mats["agent_ss_value"] = mats["agent_ss"] * mats["standard_cost"].fillna(0.0)

    p = props.groupby("material_id").agg(n_proposals=("proposed_qty", "size"),
                                         cost=("estimated_cost", "sum"),
                                         expedite=("expedite", "max"))
    mats = mats.merge(p, how="left", left_on="material_id", right_index=True)
    mats[["n_proposals", "cost", "expedite"]] = mats[["n_proposals", "cost", "expedite"]].fillna(0)

    rows = [
        ("run", "ALL", "as_of", as_of.isoformat()),
        ("run", "ALL", "proposals_from", "database" if args.levels is None else "agent in memory"),
        ("run", "ALL", "demand_policy", config.demand_policy),
        ("run", "ALL", "service_levels",
         sl.describe(desires.service_level_by_abc, desires.target_service_level)),
    ]
    total_sales = float(mats["sales_value_52w"].sum()) or 1.0
    for section, col, order in (("pattern", "demand_pattern_asof", list(dp.PATTERNS)),
                                ("abc", "abc_class", ["A", "B", "C"])):
        groups = [(g, mats[mats[col] == g]) for g in order] + [("ALL", mats)]
        for g, sub in groups:
            rows += [
                (section, g, "n_materials", len(sub)),
                (section, g, "sales_value_share_pct",
                 round(float(sub["sales_value_52w"].sum()) / total_sales * 100, 2)),
                (section, g, "n_proposals", int(sub["n_proposals"].sum())),
                (section, g, "materials_with_proposal", int((sub["n_proposals"] > 0).sum())),
                (section, g, "materials_with_expedite", int((sub["expedite"] > 0).sum())),
                (section, g, "proposal_cost_eur", round(float(sub["cost"].sum()), 2)),
                (section, g, "safety_stock_value_eur", round(float(sub["agent_ss_value"].sum()), 2)),
            ]
    out = pd.DataFrame(rows, columns=["section", "group", "metric", "value"])
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False)
    print(out[out["group"] == "ALL"].to_string(index=False))
    log.success(f"Agent summary written to {path.absolute()}")


if __name__ == "__main__":
    main()
