"""
Abstract BDI (Belief-Desire-Intention) agent.

Reference: Wooldridge, M. (2009). An Introduction to MultiAgent Systems.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, date, timezone
from typing import Any


def _utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(timezone.utc)


@dataclass
class AgentBeliefs:
    """Agent's representation of the world state."""
    current_stock:        dict[str, float] = field(default_factory=dict)
    open_orders:          dict[str, list]  = field(default_factory=dict)
    consumption_history:  dict[str, list]  = field(default_factory=dict)
    annual_demand:        dict[str, float] = field(default_factory=dict)
    # DEMAND_POLICY=pattern (filled in deliberation): demand pattern, the
    # safety stock used and the share of weeks with demand, per material
    demand_pattern:       dict[str, str]   = field(default_factory=dict)
    safety_stock:         dict[str, float] = field(default_factory=dict)
    demand_week_share:    dict[str, float] = field(default_factory=dict)
    # With a service level per ABC class: the ABC class at as_of, from the
    # demand of the 52 weeks up to as_of (src/mrp/service_level.abc_classes)
    abc_class:            dict[str, str]   = field(default_factory=dict)
    timestamp:            datetime         = field(default_factory=_utcnow)
    # The date the beliefs describe ("today" from the agent's point of view).
    # Rules and the MRP engine must reason relative to this date — never the
    # wall clock — so that backtests and historical datasets stay consistent.
    as_of:                date | None      = None


def _service_levels_from_config() -> dict[str, float]:
    from src.config import config
    from src.mrp.service_level import parse_service_levels
    return parse_service_levels(config.service_level_by_abc)


@dataclass
class AgentDesires:
    """High-level goals — what the agent is trying to achieve."""
    target_service_level:    float = 0.98
    minimize_holding_cost:   bool  = True
    avoid_stockouts:         bool  = True
    respect_moq:             bool  = True
    respect_supplier_calendar: bool = True
    # Target per ABC class (SERVICE_LEVEL_BY_ABC, src/mrp/service_level.py);
    # a class not listed keeps target_service_level. Empty by default.
    service_level_by_abc:    dict[str, float] = field(
        default_factory=_service_levels_from_config)

    def service_level_for(self, abc_class: str | None) -> float:
        """Target cycle service level of a material of this ABC class."""
        from src.mrp.service_level import service_level_for
        return service_level_for(abc_class, self.target_service_level,
                                 self.service_level_by_abc)


@dataclass
class Intention:
    """Concrete commitment to a future action."""
    material_id:     str
    proposed_date:   date
    proposed_qty:    float
    supplier_id:     str | None = None
    rule_triggered:  str | None = None
    confidence:      float = 1.0
    expedite:        bool = False
    estimated_cost:  float = 0.0


class BDIAgent(ABC):
    """Abstract base class for BDI agents."""

    def __init__(self, name: str = "Agent"):
        self.name = name
        self.beliefs = AgentBeliefs()
        self.desires = AgentDesires()
        self.intentions: list[Intention] = []

    @abstractmethod
    def perceive(self) -> None:
        """Update beliefs based on environmental observations."""

    @abstractmethod
    def deliberate(self) -> None:
        """Reason over beliefs + desires → produce intentions."""

    @abstractmethod
    def act(self) -> Any:
        """Execute / persist the intentions."""

    def run_cycle(self) -> Any:
        """Standard BDI loop."""
        self.perceive()
        self.deliberate()
        return self.act()
