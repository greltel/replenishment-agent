"""
Tools available to the AI Copilot.

Each tool is a Python function that the LLM can decide to call.
The LLM sees the JSON schemas in TOOL_SCHEMAS and asks to invoke them
when the user's question requires data from the system.

Design principles:
  • Each tool returns structured data (dict / list[dict])
  • Tools are read-only — no mutations to the agent's state
  • Tools are scoped — they can't access arbitrary DB tables
  • Errors return {"error": "..."} so the LLM can describe what went wrong
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Callable

from sqlalchemy import func

from src.data_layer.models import (
    Material, Stock, PurchaseOrder, Movement, Proposal
)
from src.data_layer.repository import Repository
from src.utils.logger import log


# ============================================================
# Tool registry & schemas (OpenAI-compatible format)
# ============================================================
TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_summary",
            "description": (
                "Get an overview of the current state of the replenishment system: "
                "total materials, total proposals, expedite alerts, total qty, etc. "
                "Use this when the user asks 'how are things' or wants a high-level summary."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_critical_proposals",
            "description": (
                "List proposals flagged for expedite (critical stock situations). "
                "Returns up to N proposals sorted by urgency. Use this when the user "
                "asks 'what needs immediate attention', 'critical items', 'urgent', etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max number of proposals to return (default 10)",
                        "default": 10,
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_material_details",
            "description": (
                "Get full details for one material: master data (lead time, safety stock, "
                "MOQ, ABC class, lot sizing), current stock, open purchase orders, "
                "consumption history summary, and any pending proposals. "
                "Use this when the user asks about a specific material by ID."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "material_id": {
                        "type": "string",
                        "description": "The material ID (e.g. 'MAT4DA9F2C8')",
                    },
                },
                "required": ["material_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explain_proposal",
            "description": (
                "Explain WHY the agent generated a specific proposal: which rules were "
                "triggered, what the MRP calculation was based on, current stock state. "
                "Use this when the user asks 'why' a proposal was made, or wants the "
                "reasoning behind a recommendation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "material_id": {
                        "type": "string",
                        "description": "The material ID",
                    },
                },
                "required": ["material_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_proposals",
            "description": (
                "Search and filter proposals by ABC class, expedite flag, or rule. "
                "Use this for queries like 'show me all A-class proposals', "
                "'proposals triggered by SAFETY-BUFFER rule', etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "abc_class": {
                        "type": "string",
                        "description": "Filter by ABC class: 'A', 'B', or 'C'",
                        "enum": ["A", "B", "C"],
                    },
                    "expedite_only": {
                        "type": "boolean",
                        "description": "Only return expedite-flagged proposals",
                    },
                    "rule_contains": {
                        "type": "string",
                        "description": "Filter to proposals where this rule name appears",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 20)",
                        "default": 20,
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_materials_by_demand",
            "description": (
                "Return top-N materials ranked by recent consumption. Useful when the "
                "user asks about high-consumption items or biggest demand drivers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "n": {
                        "type": "integer",
                        "description": "How many top materials to return (default 10)",
                        "default": 10,
                    },
                    "days": {
                        "type": "integer",
                        "description": "Look-back window in days (default 90)",
                        "default": 90,
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_abc_distribution",
            "description": (
                "Return counts of materials by ABC class, plus total proposals per class. "
                "Use this for distribution / segmentation questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]


# ============================================================
# Tool implementations
# ============================================================
def _serialize_dates(obj: Any) -> Any:
    """Make dates JSON-serializable."""
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _serialize_dates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize_dates(x) for x in obj]
    return obj


def get_summary(repo: Repository) -> dict:
    s = repo.session
    n_materials = s.query(func.count(Material.material_id)).scalar() or 0
    n_proposals = s.query(func.count(Proposal.proposal_id)).scalar() or 0
    n_expedite = (s.query(func.count(Proposal.proposal_id))
                   .filter(Proposal.rule_triggered.like("%EXPEDITE%"))
                   .scalar() or 0)
    total_qty = s.query(func.sum(Proposal.proposed_qty)).scalar() or 0
    materials_covered = (s.query(func.count(func.distinct(Proposal.material_id)))
                          .scalar() or 0)
    n_open_pos = (s.query(func.count(PurchaseOrder.po_line_id))
                   .filter(PurchaseOrder.status == "OPEN")
                   .scalar() or 0)

    return {
        "total_materials":   n_materials,
        "total_proposals":   n_proposals,
        "expedite_alerts":   n_expedite,
        "total_proposed_qty": float(total_qty),
        "materials_covered": materials_covered,
        "open_purchase_orders": n_open_pos,
    }


def list_critical_proposals(repo: Repository, limit: int = 10) -> list[dict]:
    rows = (repo.session.query(Proposal, Material)
              .join(Material, Material.material_id == Proposal.material_id)
              .filter(Proposal.rule_triggered.like("%EXPEDITE%"))
              .order_by(Proposal.proposed_date)
              .limit(limit)
              .all())

    return [_serialize_dates({
        "material_id":    p.material_id,
        "description":    m.description or "",
        "proposed_date":  p.proposed_date,
        "proposed_qty":   p.proposed_qty,
        "rule_triggered": p.rule_triggered,
        "confidence":     p.confidence,
    }) for p, m in rows]


def get_material_details(repo: Repository, material_id: str) -> dict:
    m = repo.get_material(material_id)
    if not m:
        return {"error": f"Material '{material_id}' not found"}

    current_stock = repo.get_current_stock(material_id)
    open_pos = repo.get_open_pos(material_id)
    history = repo.get_consumption_history(material_id, days=90)
    proposals = (repo.session.query(Proposal)
                  .filter(Proposal.material_id == material_id)
                  .order_by(Proposal.proposed_date)
                  .all())

    total_consumed = sum(abs(m.quantity) for m in history)

    return _serialize_dates({
        "material_id":      m.material_id,
        "description":      m.description or "",
        "material_type":    m.material_type,
        "uom":               m.uom,
        "abc_class":         m.abc_class,
        "lot_sizing":       m.lot_sizing,
        "lead_time_days":   m.lead_time_days,
        "safety_stock":     m.safety_stock,
        "moq":              m.moq,
        "standard_cost":    m.standard_cost,
        "current_stock":    current_stock,
        "open_pos_count":   len(open_pos),
        "open_pos_total_qty": sum(po.quantity for po in open_pos),
        "consumption_last_90d": total_consumed,
        "consumption_events_last_90d": len(history),
        "active_proposals":   len(proposals),
        "next_proposal": ({
            "date":    proposals[0].proposed_date,
            "qty":     proposals[0].proposed_qty,
            "rules":   proposals[0].rule_triggered,
        } if proposals else None),
    })


def explain_proposal(repo: Repository, material_id: str) -> dict:
    m = repo.get_material(material_id)
    if not m:
        return {"error": f"Material '{material_id}' not found"}

    proposals = (repo.session.query(Proposal)
                  .filter(Proposal.material_id == material_id)
                  .order_by(Proposal.proposed_date)
                  .limit(5)
                  .all())

    if not proposals:
        return {
            "material_id": material_id,
            "description": m.description or "",
            "explanation": "No proposals exist for this material currently.",
        }

    current_stock = repo.get_current_stock(material_id)
    open_pos = repo.get_open_pos(material_id)
    history = repo.get_consumption_history(material_id, days=90)

    # Note: 'mv' (not 'm') to avoid shadowing the outer Material variable
    avg_daily = sum(abs(mv.quantity) for mv in history) / 90 if history else 0

    # Build a structured explanation that the LLM can transform to natural language
    return _serialize_dates({
        "material_id":     material_id,
        "description":     m.description or "",
        "abc_class":       m.abc_class,
        "current_stock":   current_stock,
        "safety_stock":    m.safety_stock,
        "stock_vs_safety": (
            "below_safety" if current_stock < (m.safety_stock or 0)
            else "above_safety"
        ),
        "lead_time_days":  m.lead_time_days,
        "moq":             m.moq,
        "avg_daily_demand_last_90d": round(avg_daily, 2),
        "days_of_cover":   round(current_stock / avg_daily, 1) if avg_daily > 0 else None,
        "open_pos_count":  len(open_pos),
        "open_pos_qty":    sum(po.quantity for po in open_pos),
        "n_proposals":     len(proposals),
        "first_proposal": {
            "date":            proposals[0].proposed_date,
            "qty":             proposals[0].proposed_qty,
            "rules_triggered": proposals[0].rule_triggered,
            "confidence":      proposals[0].confidence,
        },
    })


def search_proposals(
    repo: Repository,
    abc_class: str | None = None,
    expedite_only: bool = False,
    rule_contains: str | None = None,
    limit: int = 20,
) -> list[dict]:
    q = (repo.session.query(Proposal, Material)
          .join(Material, Material.material_id == Proposal.material_id))

    if abc_class:
        q = q.filter(Material.abc_class == abc_class.upper())
    if expedite_only:
        q = q.filter(Proposal.rule_triggered.like("%EXPEDITE%"))
    if rule_contains:
        q = q.filter(Proposal.rule_triggered.like(f"%{rule_contains}%"))

    rows = q.order_by(Proposal.proposed_date).limit(limit).all()

    return [_serialize_dates({
        "material_id":    p.material_id,
        "description":    m.description or "",
        "abc_class":      m.abc_class,
        "proposed_date":  p.proposed_date,
        "proposed_qty":   p.proposed_qty,
        "rule_triggered": p.rule_triggered,
        "expedite":       "EXPEDITE" in (p.rule_triggered or ""),
    }) for p, m in rows]


def get_top_materials_by_demand(
    repo: Repository,
    n: int = 10,
    days: int = 90,
) -> list[dict]:
    from datetime import timedelta
    from src.utils.as_of_date import get_effective_today

    cutoff = get_effective_today() - timedelta(days=days)

    rows = (repo.session.query(
                Movement.material_id,
                Material.description,
                func.sum(func.abs(Movement.quantity)).label("total_consumed"),
                func.count(Movement.movement_id).label("n_events"),
            )
            .join(Material, Material.material_id == Movement.material_id)
            .filter(
                Movement.movement_type.in_(["261", "201", "281"]),
                Movement.posting_date >= cutoff,
            )
            .group_by(Movement.material_id, Material.description)
            .order_by(func.sum(func.abs(Movement.quantity)).desc())
            .limit(n)
            .all())

    return [{
        "material_id":     r[0],
        "description":     r[1] or "",
        "total_consumed":  float(r[2] or 0),
        "n_events":        r[3],
    } for r in rows]


def get_abc_distribution(repo: Repository) -> dict:
    counts = dict(repo.session.query(
        Material.abc_class, func.count(Material.material_id)
    ).group_by(Material.abc_class).all())

    proposals_by_class = dict(
        repo.session.query(Material.abc_class, func.count(Proposal.proposal_id))
        .join(Proposal, Proposal.material_id == Material.material_id)
        .group_by(Material.abc_class).all()
    )

    return {
        "materials_by_class":  {k or "?": v for k, v in counts.items()},
        "proposals_by_class":  {k or "?": v for k, v in proposals_by_class.items()},
    }


# ============================================================
# Dispatcher
# ============================================================
TOOL_FUNCTIONS: dict[str, Callable] = {
    "get_summary":               get_summary,
    "list_critical_proposals":   list_critical_proposals,
    "get_material_details":      get_material_details,
    "explain_proposal":          explain_proposal,
    "search_proposals":          search_proposals,
    "get_top_materials_by_demand": get_top_materials_by_demand,
    "get_abc_distribution":      get_abc_distribution,
}


def execute_tool(name: str, args: dict, repo: Repository) -> str:
    """Dispatch a tool call. Returns JSON-encoded string for LLM consumption."""
    func = TOOL_FUNCTIONS.get(name)
    if not func:
        return json.dumps({"error": f"Unknown tool: {name}"})

    try:
        # Filter args to those the function accepts
        result = func(repo=repo, **args) if args else func(repo=repo)
        return json.dumps(_serialize_dates(result), ensure_ascii=False, default=str)
    except TypeError as e:
        log.warning(f"Tool '{name}' called with bad args {args}: {e}")
        return json.dumps({"error": f"Invalid arguments: {e}"})
    except Exception as e:
        log.error(f"Tool '{name}' raised: {e}")
        return json.dumps({"error": f"Tool execution failed: {e}"})
