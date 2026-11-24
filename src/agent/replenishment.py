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
from src.config import config
from src.data_layer.models import Proposal
from src.data_layer.repository import Repository
from src.mrp import demand_pattern as dp
from src.mrp import service_level as sl
from src.mrp.engine import MRPEngine
from src.rules.engine import RulesEngine
from src.utils.as_of_date import get_effective_today
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
        # "Today" must be the same date the beliefs were perceived for.
        # Resolution: explicit argument → beliefs.as_of → AS_OF_DATE setting.
        as_of = as_of or self.beliefs.as_of or get_effective_today()
        if self.beliefs.as_of is None:
            self.beliefs.as_of = as_of
            self.rules.set_beliefs(self.beliefs)

        policy = config.demand_policy
        if policy not in ("legacy", "pattern"):
            raise ValueError(f"DEMAND_POLICY must be 'legacy' or 'pattern' (got {policy!r})")
        by_pattern = policy == "pattern"
        for key in ("demand_pattern", "safety_stock", "demand_week_share", "abc_class"):
            getattr(self.beliefs, key).clear()

        materials = self.repo.get_all_materials()
        levels = self.desires.service_level_by_abc
        log.info(f"Deliberating over {len(materials)} materials (as-of {as_of}"
                 f"{', policy per demand pattern' if by_pattern else ''}"
                 f"{', service level ' + sl.describe(levels, self.desires.target_service_level) if levels else ''})...")

        # DEMAND_POLICY=pattern: demand profile of the 52 weeks up to as_of,
        # and — with a service level per ABC class — the ABC class of as_of
        # from the same demand (Pareto on demand value, the enrichment's rule),
        # so that a backtest review never uses a class drawn from later sales
        profiles: dict[str, dp.DemandProfile] = {}
        if by_pattern:
            profiles = {m.material_id: dp.profile_from_movements(
                self.beliefs.consumption_history.get(m.material_id, []), as_of)
                for m in materials}
            if levels:
                self.beliefs.abc_class.update(sl.abc_classes(
                    {m.material_id: (profiles[m.material_id].daily_mean * 365.0,
                                     m.standard_cost) for m in materials}))

        for material in materials:
            mid = material.material_id
            history = self.beliefs.consumption_history.get(mid, [])

            # 1. Forecast demand (history anchored at as_of, so a material whose
            #    consumption stopped months ago forecasts ~0, not its old rate).
            #    DEMAND_POLICY=pattern: method and safety stock per demand
            #    pattern of the 52 weeks up to as_of (src/mrp/demand_pattern.py)
            safety = None
            method = self.forecast_method
            if by_pattern:
                profile = profiles[mid]
                method = dp.forecast_method_for(profile.pattern, self.forecast_method)
                if material.ss_source == "MARC.EISBE":
                    safety = float(material.safety_stock or 0.0)   # maintained in SAP
                else:
                    safety = dp.safety_stock_for(
                        profile, material.lead_time_days,
                        self.desires.service_level_for(
                            self.beliefs.abc_class.get(mid, material.abc_class)))
                self.beliefs.demand_pattern[mid] = profile.pattern
                self.beliefs.safety_stock[mid] = safety
                self.beliefs.demand_week_share[mid] = profile.week_share
            if method is None:                      # RARE / NONE: bought to order
                demand = [0.0] * self.mrp.horizon
            else:
                demand = forecast(
                    movements=history,
                    horizon_days=self.mrp.horizon,
                    method=method,
                    as_of=as_of,
                )

            # 2. Run MRP
            mrp_df = self.mrp.calculate(
                material=material,
                current_stock=self.beliefs.current_stock.get(mid, 0.0),
                open_orders=self.beliefs.open_orders.get(mid, []),
                demand=demand,
                annual_demand_value=self.beliefs.annual_demand.get(mid),
                as_of=as_of,
                safety_stock=safety,
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
