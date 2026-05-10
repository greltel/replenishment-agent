"""
ReplenishmentAgent — the main intelligent agent.

Combines:
  • PerceptionModule (read world state)
  • MRPEngine (compute net requirements & planned orders)
  • RulesEngine (enrich/filter proposals)
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from src.agent.base import BDIAgent, Intention
from src.agent.perception import PerceptionModule
from src.data_layer.models import Proposal
from src.data_layer.repository import Repository
from src.mrp.engine import MRPEngine
from src.rules.engine import RulesEngine
from src.utils.forecasting import forecast
from src.utils.logger import log


class ReplenishmentAgent(BDIAgent):
    """Intelligent agent for inventory replenishment decisions."""

    def __init__(
        self,
        repo: Repository,
        mrp: MRPEngine,
        rules: RulesEngine,
        forecast_method: str = "moving_average",
    ):
        super().__init__(name="ReplenishmentAgent")
        self.repo = repo
        self.mrp = mrp
        self.rules = rules
        self.perception = PerceptionModule(repo)
        self.forecast_method = forecast_method
        self._mrp_results: dict = {}    # cached for inspection

    # --------------------------------------------------------
    # BDI methods
    # --------------------------------------------------------
    def perceive(self, as_of: Optional[date] = None) -> None:
        self.beliefs = self.perception.perceive(as_of=as_of)
        self.rules.set_beliefs(self.beliefs)

    def deliberate(self, as_of: Optional[date] = None) -> None:
        self.intentions = []
        self._mrp_results = {}
        as_of = as_of or date.today()

        materials = self.repo.get_all_materials()
        log.info(f"Deliberating over {len(materials)} materials...")

        for material in materials:
            mid = material.material_id

            # 1. Forecast demand
            history = self.beliefs.consumption_history.get(mid, [])
            demand = forecast(
                movements=history,
                horizon_days=self.mrp.horizon,
                method=self.forecast_method,
            )

            # 2. Run MRP
            mrp_df = self.mrp.calculate(
                material=material,
                current_stock=self.beliefs.current_stock.get(mid, 0.0),
                open_orders=self.beliefs.open_orders.get(mid, []),
                demand=demand,
                annual_demand_value=self.beliefs.annual_demand.get(mid),
                as_of=as_of,
            )
            self._mrp_results[mid] = mrp_df

            # 3. Apply business rules
            enriched_proposals = self.rules.apply(
                mrp_result=mrp_df,
                material=material,
                desires=self.desires,
            )

            # 4. Convert to Intentions
            for prop in enriched_proposals:
                self.intentions.append(Intention(
                    material_id=mid,
                    proposed_date=prop["date"],
                    proposed_qty=float(prop["qty"]),
                    supplier_id=material.preferred_supplier_id,
                    rule_triggered=prop.get("rule_triggered"),
                    confidence=prop.get("confidence", 1.0),
                    expedite=bool(prop.get("expedite", False)),
                    estimated_cost=float(prop.get("estimated_cost", 0.0)),
                ))

        log.info(f"Generated {len(self.intentions)} intentions")

    def act(self, persist: bool = True, clear_existing: bool = True) -> list[Intention]:
        """Persist intentions as Proposal rows in the DB."""
        if persist:
            if clear_existing:
                n_cleared = self.repo.clear_proposals()
                if n_cleared > 0:
                    log.info(f"Cleared {n_cleared} existing proposals")

            objects = [
                Proposal(
                    material_id=i.material_id,
                    proposed_date=i.proposed_date,
                    proposed_qty=i.proposed_qty,
                    supplier_id=i.supplier_id,
                    rule_triggered=i.rule_triggered,
                    confidence=i.confidence,
                    expedite=int(i.expedite),
                    estimated_cost=i.estimated_cost,
                )
                for i in self.intentions
            ]
            self.repo.save_proposals(objects)
            self.repo.commit()
            log.success(f"Persisted {len(objects)} proposals to DB")

        return self.intentions

    # --------------------------------------------------------
    # Convenience
    # --------------------------------------------------------
    def get_mrp_grid(self, material_id: str):
        """Return the cached MRP grid for a specific material."""
        return self._mrp_results.get(material_id)
