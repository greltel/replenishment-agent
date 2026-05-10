"""
KPI calculator for As-Is and To-Be scenarios.

Used both at runtime (compute current state KPIs) and in backtest
(compare agent decisions vs actual historical decisions).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass
class KPIReport:
    """Container for KPI results."""
    cycle_service_level_pct: float   # % of days with no stockout
    fill_rate_pct: float             # delivered qty / requested qty
    holding_cost_eur: float          # total holding cost €
    stockout_days: int               # total days with stock = 0
    inventory_turns: float           # COGS / avg inventory value
    avg_inventory_eur: float         # average inventory value held
    n_orders: int                    # number of replenishment orders
    avg_order_size: float            # mean order quantity

    def to_dict(self) -> dict:
        return asdict(self)

    def to_df(self, label: str = "KPI") -> pd.DataFrame:
        return pd.DataFrame([{"scenario": label, **self.to_dict()}])


class KPICalculator:
    """
    Computes KPIs from time-series stock & demand data.

    Inputs are pandas DataFrames with the following minimal schemas:
      stock_history:  [date, material_id, quantity]
      demand_history: [date, material_id, requested_qty, delivered_qty]
      orders:         [date, material_id, quantity, unit_cost]
      materials:      [material_id, standard_cost]
    """

    def __init__(
        self,
        stock_history: pd.DataFrame,
        demand_history: pd.DataFrame,
        orders: pd.DataFrame,
        materials: pd.DataFrame,
        holding_rate: float = 0.20,
    ):
        self.stock = stock_history.copy()
        self.demand = demand_history.copy()
        self.orders = orders.copy()
        self.materials = materials.copy()
        self.holding_rate = holding_rate

        # Normalize dates
        for df in (self.stock, self.demand, self.orders):
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])

    # ---------- individual KPIs ----------
    def cycle_service_level(self) -> float:
        """% of (material × day) combinations where stock > 0."""
        if self.stock.empty:
            return 1.0
        return float((self.stock["quantity"] > 0).mean())

    def fill_rate(self) -> float:
        """Delivered qty / requested qty (across all materials & periods)."""
        if self.demand.empty:
            return 1.0
        requested = self.demand["requested_qty"].sum()
        delivered = self.demand["delivered_qty"].sum() if "delivered_qty" in self.demand.columns else requested
        return float(delivered / requested) if requested > 0 else 1.0

    def holding_cost(self) -> float:
        """Σ (avg_inventory × unit_cost × holding_rate)."""
        if self.stock.empty or self.materials.empty:
            return 0.0

        avg_per_material = self.stock.groupby("material_id")["quantity"].mean()
        cost_map = self.materials.set_index("material_id")["standard_cost"]
        joined = avg_per_material.to_frame("avg_qty").join(cost_map, how="inner")
        return float((joined["avg_qty"] * joined["standard_cost"] * self.holding_rate).sum())

    def stockout_days(self) -> int:
        """Total (material × day) combinations with quantity == 0."""
        if self.stock.empty:
            return 0
        return int((self.stock["quantity"] == 0).sum())

    def inventory_turns(self) -> float:
        """COGS / avg inventory value (annualized)."""
        if self.stock.empty or self.materials.empty or self.demand.empty:
            return 0.0

        cost_map = self.materials.set_index("material_id")["standard_cost"]

        # COGS = sum of delivered_qty × unit_cost
        delivered_col = "delivered_qty" if "delivered_qty" in self.demand.columns else "requested_qty"
        cogs_df = self.demand.copy()
        cogs_df["cost"] = cogs_df["material_id"].map(cost_map) * cogs_df[delivered_col]
        cogs = float(cogs_df["cost"].sum())

        # Avg inventory value
        avg_per_material = self.stock.groupby("material_id")["quantity"].mean()
        joined = avg_per_material.to_frame("avg_qty").join(cost_map, how="inner")
        avg_inv_value = float((joined["avg_qty"] * joined["standard_cost"]).sum())

        # Annualize if needed
        date_range = (self.stock["date"].max() - self.stock["date"].min()).days
        if date_range > 0 and date_range < 365:
            cogs = cogs * (365 / date_range)

        return cogs / avg_inv_value if avg_inv_value > 0 else 0.0

    def avg_inventory_value(self) -> float:
        """Mean inventory value held (€)."""
        if self.stock.empty or self.materials.empty:
            return 0.0
        avg_per_material = self.stock.groupby("material_id")["quantity"].mean()
        cost_map = self.materials.set_index("material_id")["standard_cost"]
        joined = avg_per_material.to_frame("avg_qty").join(cost_map, how="inner")
        return float((joined["avg_qty"] * joined["standard_cost"]).sum())

    # ---------- summary ----------
    def report(self) -> KPIReport:
        return KPIReport(
            cycle_service_level_pct=round(self.cycle_service_level() * 100, 2),
            fill_rate_pct=round(self.fill_rate() * 100, 2),
            holding_cost_eur=round(self.holding_cost(), 2),
            stockout_days=self.stockout_days(),
            inventory_turns=round(self.inventory_turns(), 2),
            avg_inventory_eur=round(self.avg_inventory_value(), 2),
            n_orders=len(self.orders),
            avg_order_size=round(float(self.orders["quantity"].mean()), 2)
                if not self.orders.empty else 0.0,
        )


def compare_scenarios(asis: KPIReport, tobe: KPIReport) -> pd.DataFrame:
    """Side-by-side comparison DataFrame."""
    asis_dict = asis.to_dict()
    tobe_dict = tobe.to_dict()

    rows = []
    for key in asis_dict:
        a = asis_dict[key]
        t = tobe_dict[key]
        delta_abs = t - a
        delta_pct = (delta_abs / a * 100) if a not in (0, 0.0) else float("nan")
        rows.append({
            "metric": key,
            "as_is": a,
            "to_be": t,
            "delta_abs": round(delta_abs, 2),
            "delta_pct": round(delta_pct, 2) if not np.isnan(delta_pct) else None,
        })
    return pd.DataFrame(rows)
