"""
Perception module — reads world state from the data layer
and populates the agent's beliefs.

Separated from the agent class to allow swapping the data source
(e.g., from offline DB to live SAP API) without touching agent logic.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from src.agent.base import AgentBeliefs
from src.data_layer.repository import Repository
from src.utils.as_of_date import get_effective_today
from src.utils.forecasting import annual_demand
from src.utils.logger import log


class PerceptionModule:
    """Encapsulates 'reading the world'."""

    def __init__(self, repo: Repository):
        self.repo = repo

    def perceive(
        self,
        as_of: Optional[date] = None,
        history_days: int = 365,
    ) -> AgentBeliefs:
        """Build an AgentBeliefs snapshot."""
        # Resolve "today" from explicit arg → config (AS_OF_DATE) → wall clock
        as_of = as_of or get_effective_today()
        materials = self.repo.get_all_materials()

        beliefs = AgentBeliefs(as_of=as_of)
        # Stock at the end of the as-of day for all materials at once (same
        # values as get_current_stock(mid, as_of=as_of)); orders created
        # after the as-of date are not supply yet.
        stock = self.repo.get_stock_levels(as_of)

        for m in materials:
            mid = m.material_id
            beliefs.current_stock[mid] = stock.get(mid, 0.0)
            beliefs.open_orders[mid]   = self.repo.get_open_pos(mid, as_of=as_of)
            history = self.repo.get_consumption_history(
                mid, days=history_days, as_of=as_of
            )
            beliefs.consumption_history[mid] = history
            beliefs.annual_demand[mid] = annual_demand(history, as_of=as_of)

        log.info(
            f"Perception complete: {len(materials)} materials, "
            f"{sum(len(v) for v in beliefs.consumption_history.values())} movements "
            f"(as-of {as_of})"
        )
        return beliefs
