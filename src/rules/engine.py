"""
Rules engine — applies registered rules to proposals in priority order.

Supports rule ablation: pass `disabled_rules` to skip specific rules.
This is used by scripts/run_rule_ablation.py to measure the marginal
contribution of each rule (leave-one-out methodology).
"""
from __future__ import annotations

from typing import Iterable, Optional

import pandas as pd

# Force registry population by importing policies
from src.rules import policies  # noqa: F401
from src.rules.policies import RULES_REGISTRY
from src.rules.rules_config import RulesConfig, get_active, set_active
from src.utils.logger import log


class RulesEngine:
    """Applies business rules to MRP-generated proposals.

    Args:
        disabled_rules: Optional set of rule names to skip. Used for ablation
            studies. Example: {"R-EXPEDITE"} disables the expedite rule and
            keeps all others active.
    """

    def __init__(self, disabled_rules: Optional[Iterable[str]] = None,
                 config: Optional[RulesConfig] = None):
        # Company policy (thresholds, buffers, on/off). None = keep the active
        # one (config/rules.json by default).
        self.config = set_active(config) if config is not None else get_active()
        # Sort rules once at init by priority (low value = first)
        all_rules = sorted(RULES_REGISTRY, key=lambda r: r.priority)
        self.disabled_rules = set(disabled_rules) if disabled_rules else set()
        # Filter out disabled rules
        self.rules = [
            r for r in all_rules
            if getattr(r, "rule_name", r.__name__) not in self.disabled_rules
        ]
        self._beliefs = {}

        if self.disabled_rules:
            active_names = [getattr(r, "rule_name", r.__name__) for r in self.rules]
            log.info(
                f"RulesEngine: {len(self.disabled_rules)} disabled "
                f"({', '.join(sorted(self.disabled_rules))}), "
                f"{len(self.rules)} active"
            )

    def set_beliefs(self, beliefs) -> None:
        """
        Inject the agent's current beliefs (current_stock, open_orders, etc.).
        Accepts either a dict or an AgentBeliefs dataclass.
        """
        if hasattr(beliefs, "__dict__"):
            self._beliefs = vars(beliefs)
        else:
            self._beliefs = beliefs

    def apply(self, mrp_result: pd.DataFrame, material, desires,
              trace: Optional[list] = None) -> list[dict]:
        """
        Process MRP output for one material. Returns a list of enriched
        proposal dicts (after all rules are applied).

        If `trace` is a list, one dict per (order, rule) is appended to it:
        {order, rule, qty_before, qty_after, date_before, date_after,
         expedite, suppressed, changed} — the step-by-step audit trail the
        dashboard shows (and Table 4.5 of the thesis).
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

            if trace is not None:
                trace.append({"order": len(proposals) + 1, "rule": "MRP",
                              "qty_before": None, "qty_after": proposal["qty"],
                              "date_before": None, "date_after": proposal["date"],
                              "expedite": False, "suppressed": False, "changed": True,
                              "enabled": True})

            # Apply rules sequentially (priority order)
            suppressed = False
            for rule_func in self.rules:
                name = getattr(rule_func, "rule_name", rule_func.__name__)
                before = (proposal["qty"], proposal.get("date"), bool(proposal.get("expedite")),
                          proposal.get("estimated_cost"))
                proposal = rule_func(
                    proposal,
                    material,
                    beliefs=self._beliefs,
                    desires=desires,
                )
                if trace is not None:
                    if proposal is None:
                        trace.append({"order": len(proposals) + 1, "rule": name,
                                      "qty_before": before[0], "qty_after": None,
                                      "date_before": before[1], "date_after": None,
                                      "expedite": False, "suppressed": True, "changed": True,
                                      "enabled": self.config.is_enabled(name)})
                    else:
                        after = (proposal["qty"], proposal.get("date"), bool(proposal.get("expedite")),
                                 proposal.get("estimated_cost"))
                        trace.append({"order": len(proposals) + 1, "rule": name,
                                      "qty_before": before[0], "qty_after": after[0],
                                      "date_before": before[1], "date_after": after[1],
                                      "expedite": after[2], "suppressed": False,
                                      "changed": before != after,
                                      "enabled": self.config.is_enabled(name)})
                if proposal is None:
                    suppressed = True
                    break

            if not suppressed and proposal is not None and proposal["qty"] > 0:
                proposals.append(proposal)

        log.debug(f"Material {material.material_id}: "
                  f"{len(active)} MRP orders → {len(proposals)} proposals")
        return proposals

    def list_rules(self) -> list[dict]:
        """Diagnostic: list all registered rules (including disabled)."""
        all_rules = sorted(RULES_REGISTRY, key=lambda r: r.priority)
        return [
            {
                "name": getattr(r, "rule_name", r.__name__),
                "priority": getattr(r, "priority", 100),
                "function": r.__name__,
                "active": (getattr(r, "rule_name", r.__name__) not in self.disabled_rules
                           and self.config.is_enabled(getattr(r, "rule_name", r.__name__))),
            }
            for r in all_rules
        ]

    def active_rule_names(self) -> list[str]:
        """Names of currently-active rules (excludes disabled)."""
        return [getattr(r, "rule_name", r.__name__) for r in self.rules]
