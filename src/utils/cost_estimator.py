"""
Realistic cost estimation for backtest scenarios.

Many SAP environments have STPRS (standard cost) blank or zero, especially
in sandbox/demo systems. This module imputes plausible costs using:
  • Material type heuristics (ROH cheaper than FERT)
  • ABC class proxies (A items typically more expensive)
  • Industry benchmarks from the literature

Holding cost is decomposed into its components per Silver, Pyke & Peterson
(1998, ch. 3) and Vollmann et al. (2005, ch. 14):

  holding_rate = capital_cost_rate    (~ WACC, typically 8-12%)
               + warehouse_rate        (~ 3-5%, depends on storage type)
               + obsolescence_rate     (~ 2-8%, higher for tech/perishable)
               + insurance_rate        (~ 0.5-1.5%)
               + shrinkage_rate        (~ 1-2%)

Cost of stockout is decomposed into:
  • Lost-sales penalty: gross margin foregone × stockout qty
  • Expedite premium:   urgent-order fee (typically 15-30% of order value)

References:
  • Silver, E.A., Pyke, D.F., Peterson, R. (1998). Inventory Management
    and Production Planning and Scheduling. Wiley.
  • Vollmann, T.E., Berry, W.L., Whybark, D.C., Jacobs, F.R. (2005).
    Manufacturing Planning and Control Systems. McGraw-Hill.
  • Stock, J.R., Lambert, D.M. (2001). Strategic Logistics Management.
    McGraw-Hill (cost-of-stockout framework).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

import pandas as pd

from src.utils.logger import log


# ============================================================
# Industry-typical cost benchmarks
# ============================================================
# Default unit costs by material type (€/unit) — used when STPRS is missing.
# Conservative ranges drawn from manufacturing benchmarks.
DEFAULT_COST_BY_TYPE: dict[str, float] = {
    "HAWA": 30.00,   # Trading goods (spare parts) — mid-tier
    "ROH":  5.00,    # Raw materials — cheapest
    "HALB": 25.00,   # Semi-finished — mid-tier
    "FERT": 80.00,   # Finished goods — most expensive
}

# Multipliers by ABC class (A items are typically more valuable)
ABC_COST_MULTIPLIER: dict[str, float] = {
    "A": 3.0,
    "B": 1.5,
    "C": 0.7,
}


# ============================================================
# Holding cost decomposition
# ============================================================
@dataclass
class HoldingCostComponents:
    """Breakdown of the holding rate into economic components.

    All rates are annual (e.g., 0.10 = 10% per year).
    """
    capital_cost_rate:   float = 0.10   # WACC / opportunity cost
    warehouse_rate:      float = 0.04   # Storage, handling, energy
    obsolescence_rate:   float = 0.04   # Risk-adjusted write-off rate
    insurance_rate:      float = 0.01   # Property insurance on inventory
    shrinkage_rate:      float = 0.01   # Loss/damage/theft

    @property
    def total_rate(self) -> float:
        return (self.capital_cost_rate + self.warehouse_rate
                + self.obsolescence_rate + self.insurance_rate
                + self.shrinkage_rate)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["total_rate"] = self.total_rate
        return d

    @classmethod
    def conservative(cls) -> "HoldingCostComponents":
        """Lower-end estimate — stable industry, low-cost capital."""
        return cls(0.08, 0.03, 0.02, 0.005, 0.005)

    @classmethod
    def realistic(cls) -> "HoldingCostComponents":
        """Mid-range — typical European manufacturer."""
        return cls(0.10, 0.04, 0.04, 0.01, 0.01)

    @classmethod
    def aggressive(cls) -> "HoldingCostComponents":
        """High-end — fast-moving, high obsolescence (tech, fashion)."""
        return cls(0.12, 0.05, 0.08, 0.015, 0.02)


# ============================================================
# Cost of stockout
# ============================================================
@dataclass
class StockoutCostParams:
    """Parameters for cost-of-stockout calculation.

    The total cost of one stockout event has two components:
      lost_sale_loss = gross_margin_pct × unit_revenue × shortage_qty
      expedite_premium_per_order = expedite_premium_pct × unit_cost × order_qty
    """
    gross_margin_pct:    float = 0.30   # 30% margin lost per missed sale
    revenue_multiplier:  float = 1.5    # selling price = cost × this
    expedite_premium_pct: float = 0.20  # 20% premium on urgent orders
    expedite_probability: float = 0.7   # P(stockout triggers expedite)

    @classmethod
    def conservative(cls) -> "StockoutCostParams":
        return cls(0.20, 1.3, 0.10, 0.5)

    @classmethod
    def realistic(cls) -> "StockoutCostParams":
        return cls(0.30, 1.5, 0.20, 0.7)

    @classmethod
    def aggressive(cls) -> "StockoutCostParams":
        return cls(0.40, 1.8, 0.35, 0.9)


# ============================================================
# Imputation
# ============================================================
def impute_unit_cost(
    material_type: Optional[str],
    abc_class: Optional[str],
    actual_cost: float = 0.0,
) -> float:
    """Return a plausible unit cost.

    If actual_cost > 0, return it unchanged. Otherwise, derive a synthetic
    cost from material_type and abc_class.
    """
    if actual_cost and actual_cost > 0:
        return float(actual_cost)

    base = DEFAULT_COST_BY_TYPE.get(material_type or "ROH", 10.0)
    multiplier = ABC_COST_MULTIPLIER.get(abc_class or "B", 1.0)
    return round(base * multiplier, 2)


def impute_costs_in_df(
    materials_df: pd.DataFrame,
    cost_col: str = "standard_cost",
    type_col: str = "material_type",
    abc_col: str = "abc_class",
) -> pd.DataFrame:
    """Add an 'imputed_cost' column to a materials DataFrame.

    Original 'standard_cost' is preserved. The new column contains the same
    value when present, or an imputed estimate when missing/zero.
    """
    df = materials_df.copy()
    n_imputed = 0

    def _impute(row):
        nonlocal n_imputed
        actual = row.get(cost_col, 0)
        if actual and actual > 0:
            return float(actual)
        n_imputed += 1
        return impute_unit_cost(
            material_type=row.get(type_col),
            abc_class=row.get(abc_col),
        )

    df["imputed_cost"] = df.apply(_impute, axis=1)

    if n_imputed > 0:
        log.info(
            f"Cost imputation: {n_imputed}/{len(df)} materials had missing or "
            f"zero standard_cost — synthesized from type+ABC heuristics."
        )

    return df


# ============================================================
# Scenario presets
# ============================================================
@dataclass
class CostScenario:
    """Bundle of cost parameters used to drive a backtest scenario."""
    name: str
    holding: HoldingCostComponents
    stockout: StockoutCostParams
    description: str = ""

    def to_summary_dict(self) -> dict:
        return {
            "scenario":             self.name,
            "holding_rate_total":   self.holding.total_rate,
            "capital_cost_rate":    self.holding.capital_cost_rate,
            "warehouse_rate":       self.holding.warehouse_rate,
            "obsolescence_rate":    self.holding.obsolescence_rate,
            "gross_margin_pct":     self.stockout.gross_margin_pct,
            "expedite_premium_pct": self.stockout.expedite_premium_pct,
        }


SCENARIOS: dict[str, CostScenario] = {
    "conservative": CostScenario(
        name="conservative",
        holding=HoldingCostComponents.conservative(),
        stockout=StockoutCostParams.conservative(),
        description=(
            "Low-end estimates: stable industry, cheap capital, low margins. "
            "Total holding rate ~12%."
        ),
    ),
    "realistic": CostScenario(
        name="realistic",
        holding=HoldingCostComponents.realistic(),
        stockout=StockoutCostParams.realistic(),
        description=(
            "Mid-range: typical European manufacturer. Total holding rate ~20%."
        ),
    ),
    "aggressive": CostScenario(
        name="aggressive",
        holding=HoldingCostComponents.aggressive(),
        stockout=StockoutCostParams.aggressive(),
        description=(
            "High-end: fast-moving products with high obsolescence (tech, "
            "consumer electronics, fashion). Total holding rate ~28%."
        ),
    ),
}


def get_scenario(name: str) -> CostScenario:
    """Look up a scenario by name. Falls back to 'realistic'."""
    name = (name or "realistic").lower()
    if name not in SCENARIOS:
        log.warning(f"Unknown scenario '{name}', using 'realistic'")
        name = "realistic"
    return SCENARIOS[name]
