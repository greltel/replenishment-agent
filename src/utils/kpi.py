"""
KPI calculator for As-Is and To-Be scenarios.

Used both at runtime (compute current state KPIs) and in backtest
(compare agent decisions vs actual historical decisions).

Provides three layers of metric depth:
  1. Service-level KPIs:    cycle service, fill rate, stockout days
  2. Cost KPIs:             holding (decomposed), stockout, total
  3. Operational KPIs:      orders, turns, days-of-cover

Cost methodology follows Silver/Pyke/Peterson (1998) and Vollmann et al.
(2005). Holding cost is decomposed into capital + warehouse + obsolescence
+ insurance + shrinkage. Stockout cost includes lost-sale loss + expedite
premium. Ordering cost = number of orders × fixed cost per order.

COST BASIS — read this before quoting any € figure
---------------------------------------------------
All cost KPIs are expressed FOR THE SIMULATED WINDOW (e.g. 60 days), so
that holding, stockout and ordering cost are on the same basis and can be
added into a Total Cost of Ownership for that window:

    holding_cost   = avg inventory value × annual holding rate × (days / 365)
    stockout_cost  = lost sales + expedite premium incurred inside the window
    ordering_cost  = n_orders × ordering cost per order
    TCO            = holding + stockout + ordering

The *annualised* equivalent of the same window is reported alongside
(`*_annualized` fields, = window value × 365 / days). Quote the window
figure when describing the backtest and the annualised figure when
building a yearly business case — never multiply the annualised figure by
365/days again.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Iterable, Optional

import numpy as np
import pandas as pd

from src.utils.cost_estimator import (
    HoldingCostComponents, StockoutCostParams, CostScenario,
    impute_costs_in_df,
)

# Fixed administrative cost per purchase order (€). Mirrors
# config.default_ordering_cost / the MRP engine's EOQ setup cost, but kept
# as a module constant so the KPI layer has no dependency on the env config.
DEFAULT_ORDERING_COST = 50.0


# ============================================================
# Report containers
# ============================================================
@dataclass
class KPIReport:
    """Container for KPI results — backward-compatible with v1."""
    cycle_service_level_pct: float
    fill_rate_pct:           float
    holding_cost_eur:        float
    stockout_days:           int
    inventory_turns:         float
    avg_inventory_eur:       float
    n_orders:                int
    avg_order_size:          float

    # New v2 fields
    capital_cost_eur:        float = 0.0
    warehouse_cost_eur:      float = 0.0
    obsolescence_cost_eur:   float = 0.0
    insurance_cost_eur:      float = 0.0
    stockout_cost_eur:       float = 0.0
    lost_sales_eur:          float = 0.0
    expedite_premium_eur:    float = 0.0
    ordering_cost_eur:       float = 0.0
    total_cost_of_ownership: float = 0.0
    days_of_cover_avg:       float = 0.0

    # v3: explicit cost basis
    period_days:             int   = 0      # length of the simulated window
    holding_cost_annualized_eur:    float = 0.0
    tco_annualized_eur:             float = 0.0

    # Per-class breakdown (optional)
    by_abc_class:            dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        # Drop nested by_abc_class for the flat report version
        d.pop("by_abc_class", None)
        return d

    def to_df(self, label: str = "KPI") -> pd.DataFrame:
        return pd.DataFrame([{"scenario": label, **self.to_dict()}])


# ============================================================
# KPI Calculator
# ============================================================
class KPICalculator:
    """
    Computes KPIs from time-series stock & demand data.

    Inputs are pandas DataFrames with the following minimal schemas:
      stock_history:  [date, material_id, quantity]
      demand_history: [date, material_id, requested_qty, delivered_qty]
      orders:         [date, material_id, quantity, unit_cost]
      materials:      [material_id, standard_cost, material_type, abc_class]

    Args:
        holding_rate: scalar (legacy mode) or HoldingCostComponents — an
            ANNUAL rate; it is pro-rated to the window length automatically.
        stockout_params: StockoutCostParams for cost-of-stockout calculation
        impute_missing_costs: if True, fill in missing standard_cost values
            from heuristics (material_type + abc_class)
        ordering_cost_per_order: fixed administrative cost per purchase
            order (€), used for the ordering-cost KPI
        period_days: length of the simulated window in days. If omitted it
            is inferred from the stock history date range (inclusive). Pass
            it explicitly when the stock history is empty.
    """

    def __init__(
        self,
        stock_history: pd.DataFrame,
        demand_history: pd.DataFrame,
        orders: pd.DataFrame,
        materials: pd.DataFrame,
        holding_rate: float | HoldingCostComponents = 0.20,
        stockout_params: Optional[StockoutCostParams] = None,
        impute_missing_costs: bool = True,
        ordering_cost_per_order: float = DEFAULT_ORDERING_COST,
        period_days: Optional[int] = None,
    ):
        self.stock = stock_history.copy()
        self.demand = demand_history.copy()
        self.orders = orders.copy()
        self.materials = materials.copy()
        self.ordering_cost_per_order = float(ordering_cost_per_order)

        # Holding rate may be scalar or decomposed
        if isinstance(holding_rate, HoldingCostComponents):
            self.holding_components = holding_rate
            self.holding_rate = holding_rate.total_rate
        else:
            self.holding_components = None
            self.holding_rate = float(holding_rate)

        self.stockout_params = stockout_params or StockoutCostParams.realistic()

        # Impute missing costs
        if impute_missing_costs and not self.materials.empty:
            self.materials = impute_costs_in_df(self.materials)
            self._cost_col = "imputed_cost"
        else:
            self._cost_col = "standard_cost"

        # Normalize dates
        for df in (self.stock, self.demand, self.orders):
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])

        # Window length → pro-rating factor for the annual holding rate
        self.period_days = int(period_days) if period_days else self._infer_period_days()

    # ---------- Cost basis helpers ----------
    def _infer_period_days(self) -> int:
        """Inclusive number of days covered by the stock history."""
        if self.stock.empty or "date" not in self.stock.columns:
            return 0
        span = (self.stock["date"].max() - self.stock["date"].min()).days + 1
        return int(max(span, 1))

    @property
    def period_fraction(self) -> float:
        """Fraction of a year covered by the window (1.0 if unknown)."""
        return self.period_days / 365.0 if self.period_days > 0 else 1.0

    def annualize(self, window_value: float) -> float:
        """Scale a window-based cost to a 365-day equivalent."""
        return window_value / self.period_fraction if self.period_fraction > 0 else 0.0

    # ---------- Service-level KPIs ----------
    def cycle_service_level(self) -> float:
        """% of (material × day) combinations where stock > 0."""
        if self.stock.empty:
            return 1.0
        return float((self.stock["quantity"] > 0).mean())

    def fill_rate(self) -> float:
        """Delivered / requested across all materials & periods."""
        if self.demand.empty:
            return 1.0
        requested = self.demand["requested_qty"].sum()
        delivered = (self.demand["delivered_qty"].sum()
                     if "delivered_qty" in self.demand.columns else requested)
        return float(delivered / requested) if requested > 0 else 1.0

    def stockout_days(self) -> int:
        """Total (material × day) combinations with stock == 0."""
        if self.stock.empty:
            return 0
        return int((self.stock["quantity"] == 0).sum())

    # ---------- Cost KPIs ----------
    def avg_inventory_value(self) -> float:
        """Mean inventory value held (€)."""
        if self.stock.empty or self.materials.empty:
            return 0.0
        avg_per_material = self.stock.groupby("material_id")["quantity"].mean()
        cost_map = self.materials.set_index("material_id")[self._cost_col]
        joined = avg_per_material.to_frame("avg_qty").join(cost_map, how="inner")
        return float((joined["avg_qty"] * joined[self._cost_col]).sum())

    def holding_cost_annualized(self) -> float:
        """avg_inventory_value × annual holding_rate (365-day equivalent)."""
        return self.avg_inventory_value() * self.holding_rate

    def holding_cost(self) -> float:
        """Holding cost incurred INSIDE the window:
        avg_inventory_value × annual holding_rate × (period_days / 365)."""
        return self.holding_cost_annualized() * self.period_fraction

    def holding_cost_decomposed(self) -> dict:
        """Break the (window) holding cost into its components."""
        base = self.avg_inventory_value() * self.period_fraction
        if self.holding_components is None:
            return {
                "capital_cost":   base * self.holding_rate * 0.5,
                "warehouse":      base * self.holding_rate * 0.2,
                "obsolescence":   base * self.holding_rate * 0.2,
                "insurance":      base * self.holding_rate * 0.05,
                "shrinkage":      base * self.holding_rate * 0.05,
                "total":          base * self.holding_rate,
            }
        c = self.holding_components
        return {
            "capital_cost":   base * c.capital_cost_rate,
            "warehouse":      base * c.warehouse_rate,
            "obsolescence":   base * c.obsolescence_rate,
            "insurance":      base * c.insurance_rate,
            "shrinkage":      base * c.shrinkage_rate,
            "total":          base * c.total_rate,
        }

    def ordering_cost(self) -> float:
        """n_orders × fixed cost per order (window basis)."""
        if self.orders.empty:
            return 0.0
        return float(len(self.orders)) * self.ordering_cost_per_order

    def stockout_cost(self) -> dict:
        """Cost of stockouts: lost sales + expedite premium."""
        if self.demand.empty or self.materials.empty:
            return {"lost_sales": 0.0, "expedite_premium": 0.0, "total": 0.0}

        cost_map = self.materials.set_index("material_id")[self._cost_col]
        sp = self.stockout_params

        # Shortage = requested - delivered
        d = self.demand.copy()
        d["unit_cost"] = d["material_id"].map(cost_map).fillna(0)
        delivered_col = "delivered_qty" if "delivered_qty" in d.columns else "requested_qty"
        d["shortage"] = (d["requested_qty"] - d[delivered_col]).clip(lower=0)
        d["lost_revenue"] = d["shortage"] * d["unit_cost"] * sp.revenue_multiplier
        lost_sales = float((d["lost_revenue"] * sp.gross_margin_pct).sum())

        # Expedite premium
        if not self.orders.empty:
            o = self.orders.copy()
            o["unit_cost"] = o["material_id"].map(cost_map).fillna(0)
            o["order_value"] = o["quantity"] * o["unit_cost"]
            stockout_pressure = (
                self.stockout_days() / max(len(self.stock), 1)
            )
            expedite_share = min(stockout_pressure * 2, 1.0) * sp.expedite_probability
            expedite_premium = float(
                o["order_value"].sum() * expedite_share * sp.expedite_premium_pct
            )
        else:
            expedite_premium = 0.0

        return {
            "lost_sales":         lost_sales,
            "expedite_premium":   expedite_premium,
            "total":              lost_sales + expedite_premium,
        }

    def total_cost_of_ownership(self) -> float:
        """TCO = holding + stockout + ordering cost (window basis).
        Excludes acquisition cost (identical in As-Is and To-Be)."""
        return (self.holding_cost()
                + self.stockout_cost()["total"]
                + self.ordering_cost())

    # ---------- Operational KPIs ----------
    def inventory_turns(self) -> float:
        """COGS / avg inventory value (annualized)."""
        if self.stock.empty or self.materials.empty or self.demand.empty:
            return 0.0

        cost_map = self.materials.set_index("material_id")[self._cost_col]
        delivered_col = "delivered_qty" if "delivered_qty" in self.demand.columns else "requested_qty"
        cogs_df = self.demand.copy()
        cogs_df["cost"] = cogs_df["material_id"].map(cost_map).fillna(0) * cogs_df[delivered_col]
        cogs = float(cogs_df["cost"].sum())

        avg_inv_value = self.avg_inventory_value()

        if not self.stock.empty:
            date_range = (self.stock["date"].max() - self.stock["date"].min()).days
            if 0 < date_range < 365:
                cogs = cogs * (365 / date_range)

        return cogs / avg_inv_value if avg_inv_value > 0 else 0.0

    def avg_days_of_cover(self) -> float:
        """How many days of demand the average inventory covers."""
        if self.stock.empty or self.demand.empty:
            return 0.0
        avg_per_material = self.stock.groupby("material_id")["quantity"].mean()
        demand_per_material = self.demand.groupby("material_id")["requested_qty"].sum()
        date_range = max((self.stock["date"].max() - self.stock["date"].min()).days, 1)
        daily_demand = demand_per_material / date_range

        joined = avg_per_material.to_frame("stock").join(
            daily_demand.to_frame("daily_demand"), how="inner"
        )
        joined = joined[joined["daily_demand"] > 0]
        if joined.empty:
            return 0.0
        joined["days_cover"] = joined["stock"] / joined["daily_demand"]
        return float(joined["days_cover"].mean())

    # ---------- Per-ABC breakdown ----------
    def report_by_abc(self) -> dict[str, dict]:
        """Compute KPIs separately for each ABC class."""
        if self.materials.empty or "abc_class" not in self.materials.columns:
            return {}

        classes = self.materials["abc_class"].dropna().unique()
        out: dict[str, dict] = {}

        for cls in sorted(classes):
            mids = set(self.materials[
                self.materials["abc_class"] == cls
            ]["material_id"])

            sub_stock = self.stock[self.stock["material_id"].isin(mids)] \
                if not self.stock.empty else self.stock
            sub_demand = self.demand[self.demand["material_id"].isin(mids)] \
                if not self.demand.empty else self.demand
            sub_orders = self.orders[self.orders["material_id"].isin(mids)] \
                if not self.orders.empty else self.orders
            sub_materials = self.materials[self.materials["material_id"].isin(mids)]

            sub_calc = KPICalculator(
                sub_stock, sub_demand, sub_orders, sub_materials,
                holding_rate=(self.holding_components if self.holding_components
                              else self.holding_rate),
                stockout_params=self.stockout_params,
                impute_missing_costs=False,
                ordering_cost_per_order=self.ordering_cost_per_order,
                period_days=self.period_days,
            )
            sub_calc._cost_col = self._cost_col

            out[str(cls)] = {
                "n_materials":           len(mids),
                "cycle_service_level":   round(sub_calc.cycle_service_level() * 100, 2),
                "fill_rate":             round(sub_calc.fill_rate() * 100, 2),
                "holding_cost":          round(sub_calc.holding_cost(), 2),
                "stockout_cost":         round(sub_calc.stockout_cost()["total"], 2),
                "ordering_cost":         round(sub_calc.ordering_cost(), 2),
                "tco":                   round(sub_calc.total_cost_of_ownership(), 2),
                "n_orders":              len(sub_orders),
                "stockout_days":         sub_calc.stockout_days(),
            }

        return out

    # ---------- Aggregate report ----------
    def report(self) -> KPIReport:
        decomp = self.holding_cost_decomposed()
        stockout = self.stockout_cost()
        tco = self.total_cost_of_ownership()
        return KPIReport(
            cycle_service_level_pct=round(self.cycle_service_level() * 100, 2),
            fill_rate_pct=round(self.fill_rate() * 100, 2),
            holding_cost_eur=round(decomp["total"], 2),
            stockout_days=self.stockout_days(),
            inventory_turns=round(self.inventory_turns(), 2),
            avg_inventory_eur=round(self.avg_inventory_value(), 2),
            n_orders=len(self.orders),
            avg_order_size=round(float(self.orders["quantity"].mean()), 2)
                if not self.orders.empty else 0.0,
            capital_cost_eur=round(decomp["capital_cost"], 2),
            warehouse_cost_eur=round(decomp["warehouse"], 2),
            obsolescence_cost_eur=round(decomp["obsolescence"], 2),
            insurance_cost_eur=round(decomp["insurance"], 2),
            stockout_cost_eur=round(stockout["total"], 2),
            lost_sales_eur=round(stockout["lost_sales"], 2),
            expedite_premium_eur=round(stockout["expedite_premium"], 2),
            ordering_cost_eur=round(self.ordering_cost(), 2),
            total_cost_of_ownership=round(tco, 2),
            days_of_cover_avg=round(self.avg_days_of_cover(), 2),
            period_days=self.period_days,
            holding_cost_annualized_eur=round(self.holding_cost_annualized(), 2),
            tco_annualized_eur=round(self.annualize(tco), 2),
            by_abc_class=self.report_by_abc(),
        )


# ============================================================
# Comparison
# ============================================================
def compare_scenarios(
    asis: KPIReport,
    tobe: KPIReport,
    significance_threshold_pct: float = 5.0,
) -> pd.DataFrame:
    """Side-by-side comparison DataFrame."""
    asis_dict = asis.to_dict()
    tobe_dict = tobe.to_dict()

    higher_is_better = {
        "cycle_service_level_pct", "fill_rate_pct", "inventory_turns",
    }
    lower_is_better = {
        "holding_cost_eur", "stockout_days", "stockout_cost_eur",
        "lost_sales_eur", "expedite_premium_eur", "ordering_cost_eur",
        "capital_cost_eur", "warehouse_cost_eur",
        "obsolescence_cost_eur", "insurance_cost_eur",
        "total_cost_of_ownership", "avg_inventory_eur",
        "holding_cost_annualized_eur", "tco_annualized_eur",
    }
    # n_orders, avg_order_size, days_of_cover_avg and period_days are
    # descriptive: more orders is neither good nor bad by itself (the
    # trade-off is captured by ordering_cost_eur vs holding_cost_eur).
    descriptive = {"period_days"}

    rows = []
    for key in asis_dict:
        a = asis_dict[key]
        t = tobe_dict[key]

        if not isinstance(a, (int, float)):
            continue

        delta_abs = t - a
        delta_pct = (delta_abs / a * 100) if a not in (0, 0.0) else float("nan")

        direction = "neutral"
        if key in descriptive:
            direction = "—"
        elif delta_abs == 0:
            direction = "= same"
        elif key in higher_is_better:
            direction = "↑ better" if delta_abs > 0 else "↓ worse"
        elif key in lower_is_better:
            direction = "↓ better" if delta_abs < 0 else "↑ worse"

        is_sig = (not np.isnan(delta_pct)
                  and abs(delta_pct) >= significance_threshold_pct)

        rows.append({
            "metric":      key,
            "as_is":       a,
            "to_be":       t,
            "delta_abs":   round(delta_abs, 2),
            "delta_pct":   round(delta_pct, 2) if not np.isnan(delta_pct) else None,
            "direction":   direction,
            "significant": is_sig,
        })
    return pd.DataFrame(rows)


# ============================================================
# Sensitivity analysis helper
# ============================================================
def sensitivity_pivot(
    results: list[tuple[str, KPIReport]],
    metrics: Optional[list[str]] = None,
) -> pd.DataFrame:
    """Pivot multiple KPIReport results into a comparison table."""
    if metrics is None:
        metrics = [
            "cycle_service_level_pct", "fill_rate_pct",
            "holding_cost_eur", "stockout_cost_eur", "ordering_cost_eur",
            "total_cost_of_ownership", "tco_annualized_eur", "stockout_days",
            "inventory_turns", "n_orders", "period_days",
        ]

    rows = []
    for name, report in results:
        d = report.to_dict()
        row = {"scenario": name}
        for m in metrics:
            row[m] = d.get(m, None)
        rows.append(row)

    return pd.DataFrame(rows)
