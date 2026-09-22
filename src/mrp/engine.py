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
          period, gross_requirement, scheduled_receipt (open POs),
          planned_arrival_qty (planned orders landing on this day),
          projected_on_hand, net_requirement, planned_receipt (quantity
          decided on this day), planned_release, planned_arrival,
          below_safety.

        Lead-time awareness: a requirement inside the lead time (period <
        as_of + LT) cannot be covered on time. The engine then orders once,
        for the shortage projected at the earliest feasible arrival date
        (as_of + LT), and books the receipt there — instead of booking an
        infeasible receipt today and re-ordering the same shortage in every
        following period / review. Periods in between are flagged
        `below_safety` (the unavoidable exposure a planner should expedite).
        """
        as_of = as_of or date.today()

        # Sanitize demand
        if not demand:
            demand = [0.0] * self.horizon
        demand = list(demand) + [0.0] * max(0, self.horizon - len(demand))
        demand = demand[:self.horizon]

        # Pre-bucket scheduled receipts by date.
        # Overdue open POs (expected before as_of) are treated as arriving on
        # day 0 — the same assumption SAP MRP makes for past-due receipts
        # (they remain in the receipt list and are counted as available on
        # the planning date, flagged with a rescheduling exception).
        sr_by_date: dict[date, float] = {}
        for po in open_orders:
            if po.expected_date is None:
                continue
            arrival = max(po.expected_date, as_of)
            sr_by_date[arrival] = sr_by_date.get(arrival, 0.0) + float(po.quantity)

        # Annual demand for EOQ (estimate from horizon if not provided)
        if annual_demand_value is None:
            avg_daily = sum(demand) / max(len(demand), 1)
            annual_demand_value = avg_daily * 365.0

        lead_time = int(material.lead_time_days or 0)
        safety = float(material.safety_stock or 0.0)
        horizon_dates = [as_of + timedelta(days=t) for t in range(self.horizon)]
        # Index of the first period a NEW order can arrive in (today + LT)
        first_feasible_idx = min(lead_time, self.horizon - 1)

        # Planned receipts that were pushed out to the earliest feasible
        # arrival date, keyed by period index (see "inside lead time" below).
        deferred_receipts: dict[int, float] = {}

        rows = []
        poh = float(current_stock)

        for t in range(self.horizon):
            period = horizon_dates[t]

            gr = float(demand[t])
            sr = float(sr_by_date.get(period, 0.0))          # open POs
            landing = deferred_receipts.get(t, 0.0)          # pushed-out planned orders

            # Projected on-hand BEFORE planned order
            poh_before = poh + sr + landing - gr

            # Lot sizing — POQ and Wagner-Whitin look at the upcoming demand
            # (the rest of the planning horizon)
            future_window = demand[t:] if t < self.horizon else []

            inside_lead_time = t < first_feasible_idx
            if inside_lead_time:
                # A requirement that falls INSIDE the lead time cannot be
                # covered on time: the earliest a new order can arrive is
                # as_of + LT. The net requirement is therefore the shortage
                # projected at that arrival date, netting everything that
                # arrives or is consumed until then. This (a) avoids raising a
                # new order for the same shortage in every period until the
                # first order lands, and (b) is exactly how a rolling review
                # avoids duplicate orders: the previously released order is
                # visible as a scheduled receipt at as_of + LT.
                arrival_idx = first_feasible_idx
                projected = poh_before
                for k in range(t + 1, arrival_idx + 1):
                    projected += (float(sr_by_date.get(horizon_dates[k], 0.0))
                                  + deferred_receipts.get(k, 0.0)
                                  - float(demand[k]))
                nr = max(safety - projected, 0.0)
            else:
                nr = max(safety - poh_before, 0.0)

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

            release_date: date | None = None
            arrival_date: date | None = None
            if por > 0:
                if inside_lead_time:
                    # Release now; the receipt lands at as_of + LT, not today.
                    release_date = as_of
                    arrival_date = horizon_dates[first_feasible_idx]
                    deferred_receipts[first_feasible_idx] = (
                        deferred_receipts.get(first_feasible_idx, 0.0) + por
                    )
                    poh_after = poh_before          # nothing arrives today
                else:
                    release_date = period - timedelta(days=lead_time)
                    arrival_date = period
                    poh_after = poh_before + por
            else:
                poh_after = poh_before

            rows.append({
                "period":            period,
                "gross_requirement": gr,
                "scheduled_receipt": sr,
                "planned_arrival_qty": landing,
                "projected_on_hand": poh_after,
                "net_requirement":   nr,
                "planned_receipt":   por,
                "planned_release":   release_date,
                "planned_arrival":   arrival_date,
                "below_safety":      bool(poh_after < safety),
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
