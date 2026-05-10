"""
Lot sizing policies for MRP.

Implemented:
  - LFL (Lot-for-Lot)
  - FOQ (Fixed Order Quantity)
  - EOQ (Economic Order Quantity, classic Wilson formula)
  - POQ (Periodic Order Quantity)
  - WW  (Wagner-Whitin dynamic programming optimum)
"""
from __future__ import annotations

import math
from typing import Sequence


# ============================================================
# Individual policies
# ============================================================
def lot_for_lot(net_req: float, moq: float = 0.0) -> float:
    """Order exactly what is needed (respecting MOQ)."""
    if net_req <= 0:
        return 0.0
    return max(net_req, moq)


def fixed_order_qty(net_req: float, foq: float, moq: float = 0.0) -> float:
    """Order in multiples of `foq`, never below MOQ."""
    if net_req <= 0:
        return 0.0
    if foq <= 0:
        return max(net_req, moq)
    multiples = math.ceil(net_req / foq)
    return max(multiples * foq, moq)


def economic_order_qty(
    annual_demand: float,
    ordering_cost: float,
    holding_rate: float,
    unit_cost: float,
    current_need: float = 0.0,
    moq: float = 0.0,
) -> float:
    """
    Classic Wilson EOQ:  Q* = sqrt(2 * D * S / (h * c))
      D = annual demand
      S = ordering cost per order
      h = holding rate (fraction)
      c = unit cost
    """
    if current_need <= 0:
        return 0.0

    H = holding_rate * unit_cost
    if H <= 0 or annual_demand <= 0:
        return max(current_need, moq)

    eoq = math.sqrt(2 * annual_demand * ordering_cost / H)
    return max(eoq, current_need, moq)


def periodic_order_qty(
    future_demand: Sequence[float],
    n_periods: int = 7,
    moq: float = 0.0,
) -> float:
    """Order enough to cover the next n_periods of forecasted demand."""
    if not future_demand:
        return moq
    coverage = float(sum(future_demand[:n_periods]))
    if coverage <= 0:
        return 0.0
    return max(coverage, moq)


def wagner_whitin(
    demand_per_period: Sequence[float],
    setup_cost: float,
    holding_cost_per_unit_per_period: float,
) -> list[float]:
    """
    Wagner-Whitin DP — returns optimal order quantity per period.

    Minimizes total cost (setup + holding) over the planning horizon.
    Returns a list aligned with `demand_per_period` where each entry is the
    quantity to order at that period (0 if none).
    """
    n = len(demand_per_period)
    if n == 0:
        return []

    # f[t] = minimum total cost for periods 1..t
    # We fix f[0] = 0 (before period 1)
    f = [0.0] + [float("inf")] * n
    # last_order_period[t] = the period at which the last order was placed
    # to cover up to period t
    last_order_period = [0] * (n + 1)

    for t in range(1, n + 1):
        for j in range(1, t + 1):
            # Order at period j to cover demand from j to t
            order_qty = sum(demand_per_period[j-1:t])
            # Holding cost: items received at j and held until consumed
            holding = 0.0
            for k in range(j, t + 1):
                holding += (k - j) * demand_per_period[k-1] * holding_cost_per_unit_per_period
            cost = f[j - 1] + setup_cost + holding
            if cost < f[t]:
                f[t] = cost
                last_order_period[t] = j

    # Reconstruct order schedule
    orders = [0.0] * n
    t = n
    while t > 0:
        j = last_order_period[t]
        orders[j - 1] = float(sum(demand_per_period[j-1:t]))
        t = j - 1
    return orders


# ============================================================
# Dispatcher
# ============================================================
def apply_lot_sizing(
    net_req: float,
    policy: str,
    moq: float = 0.0,
    fixed_lot_size: float = 0.0,
    future_demand: Sequence[float] | None = None,
    annual_demand_value: float = 0.0,
    ordering_cost: float = 50.0,
    holding_rate: float = 0.20,
    unit_cost: float = 1.0,
    poq_periods: int = 7,
) -> float:
    """
    Apply the configured lot-sizing policy to a single MRP period.

    Note: for Wagner-Whitin, use the function `wagner_whitin` directly
    over the entire horizon (it is multi-period optimal).
    """
    if net_req <= 0:
        return 0.0

    policy = (policy or "LFL").upper()

    if policy == "LFL":
        return lot_for_lot(net_req, moq)

    elif policy == "FOQ":
        return fixed_order_qty(net_req, fixed_lot_size or moq or 1.0, moq)

    elif policy == "EOQ":
        return economic_order_qty(
            annual_demand=annual_demand_value,
            ordering_cost=ordering_cost,
            holding_rate=holding_rate,
            unit_cost=unit_cost,
            current_need=net_req,
            moq=moq,
        )

    elif policy == "POQ":
        return periodic_order_qty(
            future_demand=future_demand or [],
            n_periods=poq_periods,
            moq=moq,
        )

    else:
        # Unknown policy → fall back to LFL
        return lot_for_lot(net_req, moq)
