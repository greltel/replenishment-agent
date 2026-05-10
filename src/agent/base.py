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
    timestamp:            datetime         = field(default_factory=_utcnow)


@dataclass
class AgentDesires:
    """High-level goals — what the agent is trying to achieve."""
    target_service_level:    float = 0.98
    minimize_holding_cost:   bool  = True
    avoid_stockouts:         bool  = True
    respect_moq:             bool  = True
    respect_supplier_calendar: bool = True


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
