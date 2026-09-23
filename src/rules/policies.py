"""
Business rules engine — declarative policies that enrich, modify, or
suppress proposals coming out of the MRP engine.

Each rule is a function decorated with @rule(name, priority).
Rules execute in priority order (LOWER priority value = runs FIRST).
A rule returning None suppresses the proposal entirely.
"""
from __future__ import annotations

import math

from datetime import date, timedelta
from typing import Callable, Optional

from src.config import config
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


@rule("R-DEAD-STOCK", priority=1)
def suppress_dead_stock(proposal: dict, material, beliefs, desires) -> Optional[dict]:
    """
    Suppress proposals for materials with no movement in a long time.
    These are likely obsolete or phased-out items.

    Threshold is configurable via DEAD_STOCK_THRESHOLD_DAYS (default 365).
    "Today" is the beliefs' as-of date (the simulation date in a backtest),
    falling back to AS_OF_DATE (see src/utils/as_of_date.py).
    """
    history = _belief(beliefs, "consumption_history", {}).get(material.material_id, [])
    if not history:
        # No history at all — could be a brand-new item; suppress conservatively
        return None

    last_movement = max((m.posting_date for m in history), default=None)
    if last_movement is None:
        return None

    days_since = (_today(beliefs) - last_movement).days
    if days_since > config.dead_stock_threshold_days:
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
    current_stock = _belief(beliefs, "current_stock", {}).get(material.material_id, 0.0)
    safety = float(material.safety_stock or 0.0)
    if not (safety > 0 and current_stock < safety * 0.5):
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
    if material.abc_class == "A":
        proposal["qty"] = float(proposal["qty"]) * 1.20
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
    qty = float(proposal["qty"])
    original = qty
    moq = float(material.moq or 0.0)
    if moq > 0 and qty < moq:
        qty = moq
    lot = float(material.fixed_lot_size or 0.0)
    if lot > 0:
        qty = math.ceil(qty / lot - 1e-9) * lot
    elif (material.uom or "PC").upper() not in CONTINUOUS_UOMS:
        qty = float(math.ceil(qty - 1e-9))
    if qty != original:
        proposal["qty"] = qty
        existing = proposal.get("rule_triggered") or ""
        proposal["rule_triggered"] = (existing + " | R-MOQ-ENFORCE").strip(" |")
    return proposal


@rule("R-CALENDAR-SHIFT", priority=80)
def shift_to_workday(proposal: dict, material, beliefs, desires) -> dict:
    """Shift release date forward to the next working day if needed."""
    d = proposal.get("date")
    if d is not None:
        new_d = next_workday(d)
        if new_d != d:
            proposal["date"] = new_d
            existing = proposal.get("rule_triggered") or ""
            proposal["rule_triggered"] = (existing + " | R-CALENDAR-SHIFT").strip(" |")
    return proposal


LONG_LEAD_THRESHOLD_DAYS = 30     # sea freight / overseas suppliers
LONG_LEAD_BUFFER = 1.15           # +15 % on the order quantity


@rule("R-LONG-LEAD-BUFFER", priority=25)
def long_lead_supplier_buffer(proposal: dict, material, beliefs, desires) -> dict:
    """
    For materials with a long import lead time (> 30 days — typically
    overseas suppliers / sea freight), add a 15 % buffer to the quantity to
    absorb lead-time variability (customs, consolidation, missed vessels).
    """
    if material.lead_time_days and material.lead_time_days > LONG_LEAD_THRESHOLD_DAYS:
        proposal["qty"] = float(proposal["qty"]) * LONG_LEAD_BUFFER
        existing = proposal.get("rule_triggered") or ""
        proposal["rule_triggered"] = (existing + " | R-LONG-LEAD-BUFFER").strip(" |")
    return proposal


@rule("R-COST-ESTIMATE", priority=90)
def estimate_cost(proposal: dict, material, beliefs, desires) -> dict:
    """Compute estimated cost = qty × standard_cost."""
    proposal["estimated_cost"] = float(proposal["qty"]) * float(material.standard_cost or 0.0)
    return proposal
