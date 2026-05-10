"""
Rules engine — applies registered rules to proposals in priority order.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

# Force registry population by importing policies
from src.rules import policies  # noqa: F401
from src.rules.policies import RULES_REGISTRY
from src.utils.logger import log


class RulesEngine:
    """Applies business rules to MRP-generated proposals."""

    def __init__(self):
        # Sort rules once at init by priority (low value = first)
        self.rules = sorted(RULES_REGISTRY, key=lambda r: r.priority)
        self._beliefs = {}

    def set_beliefs(self, beliefs) -> None:
        """
        Inject the agent's current beliefs (current_stock, open_orders, etc.).
        Accepts either a dict or an AgentBeliefs dataclass.
        """
        if hasattr(beliefs, "__dict__"):
            self._beliefs = vars(beliefs)
        else:
            self._beliefs = beliefs

    def apply(self, mrp_result: pd.DataFrame, material, desires) -> list[dict]:
        """
        Process MRP output for one material. Returns a list of enriched
        proposal dicts (after all rules are applied).
        """
        if mrp_result is None or mrp_result.empty:
            return []

        # Keep only rows with a real planned order
        active = mrp_result[
            (mrp_result["planned_receipt"] > 0)
            & (mrp_result["planned_release"].notna())
        ].copy()

        if active.empty:
            return []

        proposals = []
        for _, row in active.iterrows():
            proposal = {
                "date":            row["planned_release"],
                "qty":             float(row["planned_receipt"]),
                "rule_triggered":  None,
                "expedite":        False,
                "confidence":      1.0,
                "estimated_cost":  0.0,
            }

            # Apply rules sequentially (priority order)
            suppressed = False
            for rule_func in self.rules:
                proposal = rule_func(
                    proposal,
                    material,
                    beliefs=self._beliefs,
                    desires=desires,
                )
                if proposal is None:
                    suppressed = True
                    break

            if not suppressed and proposal is not None and proposal["qty"] > 0:
                proposals.append(proposal)

        log.debug(f"Material {material.material_id}: "
                  f"{len(active)} MRP orders → {len(proposals)} proposals")
        return proposals

    def list_rules(self) -> list[dict]:
        """Diagnostic: list all registered rules."""
        return [
            {
                "name": getattr(r, "rule_name", r.__name__),
                "priority": getattr(r, "priority", 100),
                "function": r.__name__,
            }
            for r in self.rules
        ]
