"""
Target cycle service level per ABC class (SERVICE_LEVEL_BY_ABC).

Why
───
With one target for every material (98 %), the safety stock of the many
low-value parts weighs as much in the decision as that of the few parts
that make most of the sales value. Setting the service level per ABC class
is the usual practice: "the standard approach in ABC applications is to set
the same service level for all stock keeping units (SKUs) in a class"
(Teunter, Babai & Syntetos 2010). The same authors show on three large real
datasets that fixed service levels per class on the demand-value ranking
are far from cost optimal and propose a cost criterion instead (b·D/(h·Q):
shortage cost × demand over holding cost × order quantity). This module
implements the standard practice, so that its effect can be measured in the
backtest; the cost criterion is left as an extension.

Setting
───────
    SERVICE_LEVEL_BY_ABC=A=0.98,B=0.95,C=0.90

Comma-separated CLASS=level pairs, levels as fractions (0.95) or percent
(95). A class that is not listed, or a material without a class, keeps the
uniform target (AgentDesires.target_service_level, 98 %). Empty (the
default) or "uniform" = the uniform target for every material — the
behaviour before this setting existed, so the sample-data results of the
thesis are unchanged (run_all.* pin "uniform", so that a .env value never
reaches the sample data).

Where it applies
────────────────
• the agent (DEMAND_POLICY=pattern): the safety stock it computes at every
  review, ReplenishmentAgent.deliberate → demand_pattern.safety_stock_for;
• the master-data enrichment (both policies): the derived safety stock of
  materials.csv (MARC-EISBE, when maintained in SAP, always wins);
• the dashboard drill-down, which repeats the agent's calculation.

The ABC class is the Pareto class on demand value (80 % / 95 %) of the
master-data enrichment (src/data_layer/master_data_enrichment). The agent
derives it again at every review from the demand of the 52 weeks up to the
review date (abc_classes): on the as-of date of the data it equals the class
of the master data, while in the backtest a review uses the class that was
known at that date — the master-data class, computed up to the end of the
window, would contain the window's own sales (1,085 of the 50,160 pilot
materials change class between the start and the end of the 60-day window).

Reference
─────────
Teunter, R.H., Babai, M.Z. and Syntetos, A.A. (2010). ABC classification:
    service levels and inventory costs. Production and Operations
    Management, 19(3), 343–352. doi:10.1111/j.1937-5956.2009.01098.x
"""
from __future__ import annotations

from functools import lru_cache

# A service level must be a probability strictly between these bounds:
# below 50 % the normal safety stock turns negative, 100 % has no quantile.
MIN_SERVICE_LEVEL = 0.5
MAX_SERVICE_LEVEL = 0.9999


def parse_service_levels(spec: str | None) -> dict[str, float]:
    """'A=0.98,B=0.95,C=0.90' → {'A': 0.98, 'B': 0.95, 'C': 0.90}.

    Levels above 1 are read as percent (95 → 0.95). Raises ValueError on a
    malformed pair or a level outside [0.5, 0.9999], so that a typo in the
    setting stops the run instead of silently using another target.
    """
    return dict(_parse(spec or ""))


UNIFORM = "uniform"


@lru_cache(maxsize=32)
def _parse(spec: str) -> tuple[tuple[str, float], ...]:
    if spec.strip().lower() == UNIFORM:
        return ()
    out: dict[str, float] = {}
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        cls, sep, value = part.partition("=")
        cls = cls.strip().upper()
        if not sep or not cls:
            raise ValueError(f"SERVICE_LEVEL_BY_ABC: expected CLASS=level, got {part!r}")
        try:
            level = float(value.strip().replace("%", ""))
        except ValueError:
            raise ValueError(f"SERVICE_LEVEL_BY_ABC: {part!r} has no numeric level") from None
        if level > 1:
            level /= 100.0
        if not MIN_SERVICE_LEVEL <= level <= MAX_SERVICE_LEVEL:
            raise ValueError(f"SERVICE_LEVEL_BY_ABC: level of class {cls} must be between "
                             f"{MIN_SERVICE_LEVEL:.0%} and {MAX_SERVICE_LEVEL:.2%} (got {value})")
        out[cls] = level
    return tuple(out.items())


def service_level_for(abc_class: str | None, default: float,
                      levels: dict[str, float] | None = None) -> float:
    """Target service level of a material of class `abc_class`: the level of
    its class when one is set, otherwise `default` (the uniform target)."""
    if levels is None:
        from src.config import config
        levels = dict(_parse(config.service_level_by_abc or ""))
    if abc_class:
        return levels.get(str(abc_class).strip().upper(), default)
    return default


def abc_classes(value_inputs: dict[str, tuple[float, float | None]]) -> dict[str, str]:
    """ABC class per material from {material_id: (annual demand, unit cost)}
    with the rule of the master-data enrichment (Pareto on cost × annual
    demand, A ≤ 80 %, B ≤ 95 %; no demand → C;
    master_data_enrichment.derive_abc_class).

    The agent calls it at every review with the demand of the 52 weeks up to
    the review date: on the as-of date of the data this is the class of the
    master data; in a backtest it is the class the planner could have known
    at that date, not one drawn from the sales of the window itself.
    """
    if not value_inputs:
        return {}
    import pandas as pd
    from src.data_layer.master_data_enrichment import derive_abc_class
    ids = list(value_inputs)
    df = pd.DataFrame({"annual_demand": [float(value_inputs[i][0] or 0.0) for i in ids],
                       "standard_cost": [float(value_inputs[i][1] or 0.0) for i in ids]},
                      index=ids)
    return derive_abc_class(None, df).to_dict()


def pct(level: float) -> str:
    """0.98 → '98%', 0.995 → '99.5%'."""
    return f"{round(level * 100, 2):g}%"


def describe(levels: dict[str, float], default: float) -> str:
    """Short label of the targets, e.g. 'A 98% · B 95% · C 90%' or '98%'."""
    if not levels:
        return pct(default)
    classes = sorted(set(levels) | {"A", "B", "C"})
    return " · ".join(f"{c} {pct(levels.get(c, default))}" for c in classes)
