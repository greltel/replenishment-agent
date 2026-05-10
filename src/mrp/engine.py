"""
MRP Engine — time-phased material requirements planning.

Core algorithm:
  1. Compute Gross Requirements (from forecast)
  2. Add Scheduled Receipts (open POs)
  3. Compute Projected On-Hand
  4. Compute Net Requirements (when POH < safety_stock)
  5. Apply lot sizing → Planned Order Receipt
  6. Offset by Lead Time → Planned Order Release
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Sequence

import pandas as pd

from src.data_layer.models import Material, PurchaseOrder
from src.mrp.lot_sizing import apply_lot_sizing
from src.utils.logger import log


class MRPEngine:
    """Time-phased MRP calculator."""

    def __init__(
        self,
        horizon_days: int = 60,
        ordering_cost: float = 50.0,
        holding_rate: float = 0.20,
    ):
        self.horizon = horizon_days
        self.ordering_cost = ordering_cost
        self.holding_rate = holding_rate

    def calculate(
        self,
        material: Material,
        current_stock: float,
        open_orders: Sequence[PurchaseOrder],
        demand: Sequence[float],
        annual_demand_value: float | None = None,
        as_of: date | None = None,
    ) -> pd.DataFrame:
        """
        Run MRP for a single material.

        Returns a DataFrame with one row per day in the horizon, columns:
          period, gross_requirement, scheduled_receipt, projected_on_hand,
          net_requirement, planned_receipt, planned_release.
        """
        as_of = as_of or date.today()

        # Sanitize demand
        if not demand:
            demand = [0.0] * self.horizon
        demand = list(demand) + [0.0] * max(0, self.horizon - len(demand))
        demand = demand[:self.horizon]

        # Pre-bucket scheduled receipts by date
        sr_by_date: dict[date, float] = {}
        for po in open_orders:
            if po.expected_date is None:
                continue
            sr_by_date[po.expected_date] = (
                sr_by_date.get(po.expected_date, 0.0) + float(po.quantity)
            )

        # Annual demand for EOQ (estimate from horizon if not provided)
        if annual_demand_value is None:
            avg_daily = sum(demand) / max(len(demand), 1)
            annual_demand_value = avg_daily * 365.0

        rows = []
        poh = float(current_stock)

        for t in range(self.horizon):
            period = as_of + timedelta(days=t)

            gr = float(demand[t])
            sr = float(sr_by_date.get(period, 0.0))

            # Projected on-hand BEFORE planned order
            poh_before = poh + sr - gr

            # Net requirement
            if poh_before < material.safety_stock:
                nr = material.safety_stock - poh_before
            else:
                nr = 0.0

            # Lot sizing — for POQ we need future demand window
            future_window = demand[t : t + 30] if t < self.horizon else []

            por = apply_lot_sizing(
                net_req=nr,
                policy=material.lot_sizing or "LFL",
                moq=material.moq,
                fixed_lot_size=material.fixed_lot_size,
                future_demand=future_window,
                annual_demand_value=annual_demand_value,
                ordering_cost=self.ordering_cost,
                holding_rate=self.holding_rate,
                unit_cost=material.standard_cost or 1.0,
            )

            # Update POH after planned order
            poh_after = poh_before + por

            # Compute planned release (offset by lead time)
            release_date: date | None = None
            if por > 0:
                release_date = period - timedelta(days=int(material.lead_time_days or 0))
                if release_date < as_of:
                    release_date = as_of  # cannot order in the past

            rows.append({
                "period":            period,
                "gross_requirement": gr,
                "scheduled_receipt": sr,
                "projected_on_hand": poh_after,
                "net_requirement":   nr,
                "planned_receipt":   por,
                "planned_release":   release_date,
            })

            # Carry POH forward
            poh = poh_after

        df = pd.DataFrame(rows)
        return df

    def calculate_batch(
        self,
        materials: Sequence[Material],
        beliefs: dict,
        demand_forecasts: dict[str, list[float]],
        as_of: date | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Run MRP for many materials. Returns {material_id: DataFrame}."""
        results = {}
        as_of = as_of or date.today()

        for material in materials:
            mid = material.material_id
            try:
                df = self.calculate(
                    material=material,
                    current_stock=beliefs.get("current_stock", {}).get(mid, 0.0),
                    open_orders=beliefs.get("open_orders", {}).get(mid, []),
                    demand=demand_forecasts.get(mid, []),
                    annual_demand_value=beliefs.get("annual_demand", {}).get(mid),
                    as_of=as_of,
                )
                results[mid] = df
            except Exception as e:
                log.error(f"MRP failed for {mid}: {e}")
                continue

        log.info(f"MRP computed for {len(results)} / {len(materials)} materials")
        return results
