"""
Business rules engine — declarative policies that enrich, modify, or
suppress proposals coming out of the MRP engine.

Each rule is a function decorated with @rule(name, priority).
Rules execute in priority order (LOWER priority value = runs FIRST).
A rule returning None suppresses the proposal entirely.

The *logic* of every rule lives here; its company-specific *parameters*
(thresholds, buffer percentages, on/off) live in config/rules.json and are
read through src.rules.rules_config (defaults = the thesis values).
A rule that is switched off in the policy returns the proposal unchanged.
"""
from __future__ import annotations

import math

from datetime import date, timedelta
from typing import Callable, Optional

from src.config import config
from src.mrp import demand_pattern
from src.rules.rules_config import get_active
from src.utils.as_of_date import get_effective_today
from src.utils.calendar_utils import next_workday


# ============================================================
# Registry
# ============================================================
RULES_REGISTRY: list[Callable] = []


def rule(name: str, priority: int = 100):
    """Decorator that registers a rule."""
    def decorator(func: Callable) -> Callable:
        func.rule_name = name      # type: ignore[attr-defined]
        func.priority = priority   # type: ignore[attr-defined]
        RULES_REGISTRY.append(func)
        return func
    return decorator


# ============================================================
# Rule implementations
# ============================================================

def _belief(beliefs, key: str, default=None):
    """Read a field from beliefs, which may be an AgentBeliefs dataclass or a
    dict (RulesEngine.set_beliefs converts dataclasses via vars())."""
    if isinstance(beliefs, dict):
        return beliefs.get(key, default)
    return getattr(beliefs, key, default)


def _today(beliefs) -> date:
    """The date the rules reason about: the beliefs' as-of date if known,
    otherwise the configured AS_OF_DATE / wall clock."""
    return _belief(beliefs, "as_of") or get_effective_today()


def _param(rule_name: str, key: str, default=None):
    """Company policy parameter for a rule (config/rules.json)."""
    return get_active().param(rule_name, key, default)


def _enabled(rule_name: str) -> bool:
    return get_active().is_enabled(rule_name)


@rule("R-DEAD-STOCK", priority=1)
def suppress_dead_stock(proposal: dict, material, beliefs, desires) -> Optional[dict]:
    """
    Suppress proposals for materials with no movement in a long time.
    These are likely obsolete or phased-out items.

    Threshold is configurable via DEAD_STOCK_THRESHOLD_DAYS (default 365).
    "Today" is the beliefs' as-of date (the simulation date in a backtest),
    falling back to AS_OF_DATE (see src/utils/as_of_date.py).
    """
    if not _enabled("R-DEAD-STOCK"):
        return proposal
    history = _belief(beliefs, "consumption_history", {}).get(material.material_id, [])
    if not history:
        # No history at all — could be a brand-new item; suppress conservatively
        return None

    last_movement = max((m.posting_date for m in history), default=None)
    if last_movement is None:
        return None

    days_since = (_today(beliefs) - last_movement).days
    threshold = int(_param("R-DEAD-STOCK", "inactive_days", config.dead_stock_threshold_days))
    if days_since > threshold:
        return None  # suppress

    return proposal


@rule("R-EXPEDITE", priority=10)
def expedite_critical(proposal: dict, material, beliefs, desires) -> dict:
    """
    Mark a proposal as urgent when the current stock is critically low
    (< 50% of safety stock) AND this is the order that resolves the situation,
    i.e. the one to be released immediately (release date = today / inside the
    lead time). Later planned orders of the same material are normal — they
    only exist because the horizon is long, not because of the shortage.
    """
    if not _enabled("R-EXPEDITE"):
        return proposal
    mid = material.material_id
    current_stock = _belief(beliefs, "current_stock", {}).get(mid, 0.0)
    # DEMAND_POLICY=pattern: the safety stock the agent used for this
    # material, and no express shipment for parts bought to order or for a
    # sporadic part unlikely to be asked for within the lead time
    # (src/mrp/demand_pattern.py, step 5)
    safety = float(_belief(beliefs, "safety_stock", {}).get(mid, material.safety_stock) or 0.0)
    pattern = _belief(beliefs, "demand_pattern", {}).get(mid)
    if pattern is not None:
        share = _belief(beliefs, "demand_week_share", {}).get(mid, 0.0)
        lam = share * max(float(material.lead_time_days or 0), 0.0) / 7.0
        if not demand_pattern.expedite_allowed(pattern, 1.0 - math.exp(-lam)):
            return proposal
    threshold = float(_param("R-EXPEDITE", "stock_vs_safety_pct", 50)) / 100.0
    if not (safety > 0 and current_stock < safety * threshold):
        return proposal

    today = _belief(beliefs, "as_of")
    release = proposal.get("date")
    if today is not None and release is not None:
        lead_time = int(material.lead_time_days or 0)
        if release > today + timedelta(days=lead_time):
            return proposal      # a later order: not the urgent one

    proposal["expedite"] = True
    proposal["confidence"] = 1.0
    existing = proposal.get("rule_triggered") or ""
    proposal["rule_triggered"] = (existing + " | R-EXPEDITE").strip(" |")
    return proposal


@rule("R-SAFETY-BUFFER-A", priority=20)
def safety_buffer_for_a_class(proposal: dict, material, beliefs, desires) -> dict:
    """
    For A-class items, add 20% extra to the order quantity as a safety buffer.
    Rationale: highest-value items deserve extra protection.
    """
    if not _enabled("R-SAFETY-BUFFER-A"):
        return proposal
    buffer_pct = float(_param("R-SAFETY-BUFFER-A", "buffer_pct", 20))
    if material.abc_class == "A" and buffer_pct > 0:
        proposal["qty"] = float(proposal["qty"]) * (1.0 + buffer_pct / 100.0)
        existing = proposal.get("rule_triggered") or ""
        proposal["rule_triggered"] = (existing + " | R-SAFETY-BUFFER-A").strip(" |")
    return proposal


CONTINUOUS_UOMS = {"KG", "G", "L", "ML", "M", "M2", "M3", "T", "TO"}


@rule("R-MOQ-ENFORCE", priority=30)
def enforce_moq(proposal: dict, material, beliefs, desires) -> dict:
    """Make the quantity orderable: at least the MOQ, a multiple of the fixed
    lot size when one is defined (pack / carton size), and whole units for
    discrete units of measure (a spare part is not ordered as 70.4 pieces).
    Runs AFTER the buffer rules, so the buffers are rounded as well."""
    if not _enabled("R-MOQ-ENFORCE"):
        return proposal
    qty = float(proposal["qty"])
    original = qty
    moq = float(material.moq or 0.0)
    if moq > 0 and qty < moq:
        qty = moq
    lot = float(material.fixed_lot_size or 0.0)
    whole_units = bool(_param("R-MOQ-ENFORCE", "whole_units", True))
    if lot > 0:
        qty = math.ceil(qty / lot - 1e-9) * lot
    elif whole_units and (material.uom or "PC").upper() not in CONTINUOUS_UOMS:
        qty = float(math.ceil(qty - 1e-9))
    if qty != original:
        proposal["qty"] = qty
        existing = proposal.get("rule_triggered") or ""
        proposal["rule_triggered"] = (existing + " | R-MOQ-ENFORCE").strip(" |")
    return proposal


@rule("R-CALENDAR-SHIFT", priority=80)
def shift_to_workday(proposal: dict, material, beliefs, desires) -> dict:
    """Shift release date forward to the next working day if needed."""
    if not _enabled("R-CALENDAR-SHIFT"):
        return proposal
    d = proposal.get("date")
    if d is not None:
        new_d = next_workday(d)
        if new_d != d:
            proposal["date"] = new_d
            existing = proposal.get("rule_triggered") or ""
            proposal["rule_triggered"] = (existing + " | R-CALENDAR-SHIFT").strip(" |")
    return proposal


LONG_LEAD_THRESHOLD_DAYS = 30     # default: sea freight / overseas suppliers
LONG_LEAD_BUFFER = 1.15           # default: +15 % on the order quantity


@rule("R-LONG-LEAD-BUFFER", priority=25)
def long_lead_supplier_buffer(proposal: dict, material, beliefs, desires) -> dict:
    """
    For materials with a long import lead time (> 30 days — typically
    overseas suppliers / sea freight), add a 15 % buffer to the quantity to
    absorb lead-time variability (customs, consolidation, missed vessels).
    """
    if not _enabled("R-LONG-LEAD-BUFFER"):
        return proposal
    threshold = int(_param("R-LONG-LEAD-BUFFER", "threshold_days", LONG_LEAD_THRESHOLD_DAYS))
    factor = 1.0 + float(_param("R-LONG-LEAD-BUFFER", "buffer_pct", 15)) / 100.0
    if material.lead_time_days and material.lead_time_days > threshold and factor > 1.0:
        proposal["qty"] = float(proposal["qty"]) * factor
        existing = proposal.get("rule_triggered") or ""
        proposal["rule_triggered"] = (existing + " | R-LONG-LEAD-BUFFER").strip(" |")
    return proposal


@rule("R-COST-ESTIMATE", priority=90)
def estimate_cost(proposal: dict, material, beliefs, desires) -> dict:
    """Compute estimated cost = qty × standard_cost."""
    if not _enabled("R-COST-ESTIMATE"):
        return proposal
    proposal["estimated_cost"] = float(proposal["qty"]) * float(material.standard_cost or 0.0)
    return proposal
