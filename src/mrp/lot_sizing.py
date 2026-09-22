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


def poq_period(
    annual_demand: float,
    ordering_cost: float,
    holding_rate: float,
    unit_cost: float,
    min_periods: int = 7,
    max_periods: int = 60,
) -> int:
    """Economic order interval for POQ: T* = EOQ / daily demand, clamped.

    Textbook definition (Silver, Pyke & Peterson 1998, §6.5; Vollmann et al.
    2005): the period order quantity covers the number of periods that the
    economic order quantity would last. Falls back to `min_periods` (one
    week) when demand or cost information is missing.
    """
    H = holding_rate * unit_cost
    if annual_demand <= 0 or H <= 0 or ordering_cost <= 0:
        return min_periods
    eoq = math.sqrt(2 * annual_demand * ordering_cost / H)
    daily = annual_demand / 365.0
    periods = int(round(eoq / daily)) if daily > 0 else min_periods
    return max(min_periods, min(max_periods, periods))


def periodic_order_qty(
    future_demand: Sequence[float],
    n_periods: int = 7,
    moq: float = 0.0,
    net_req: float = 0.0,
) -> float:
    """Order enough to cover the next n_periods of forecasted demand.

    The order never falls below the current net requirement: if the stock
    deficit today is larger than the next n_periods of demand (e.g. after a
    demand spike pushed stock far below safety stock), POQ must still restore
    the safety level. Without this floor the projected on-hand would remain
    below safety stock after the receipt.
    """
    if not future_demand:
        return max(net_req, moq) if net_req > 0 else moq
    coverage = float(sum(future_demand[:n_periods]))
    if coverage <= 0 and net_req <= 0:
        return 0.0
    return max(coverage, net_req, moq)


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


def wagner_whitin_first_order(
    net_req: float,
    future_demand: Sequence[float],
    ordering_cost: float,
    holding_rate: float,
    unit_cost: float,
    moq: float = 0.0,
) -> float:
    """
    Rolling-horizon Wagner-Whitin: the quantity to order NOW.

    The DP is solved over [net requirement today] + [forecast demand of the
    following periods]; only the first period's order is released (the rest
    is re-planned at the next review). This is the standard way of embedding
    the multi-period optimum in a period-by-period MRP run (Silver, Pyke &
    Peterson 1998, ch. 6; Vollmann et al. 2005, ch. 14).

    Holding cost per unit per period = annual holding rate × unit cost / 365.
    """
    if net_req <= 0:
        return 0.0

    horizon = [float(net_req)] + [float(d) for d in future_demand[1:]]
    holding_per_period = max(holding_rate * unit_cost / 365.0, 1e-9)
    orders = wagner_whitin(horizon, setup_cost=ordering_cost,
                           holding_cost_per_unit_per_period=holding_per_period)
    qty = orders[0] if orders else float(net_req)
    return max(qty, float(net_req), moq)


# ============================================================
# Dispatcher
# ============================================================
KNOWN_POLICIES = ("LFL", "FOQ", "EOQ", "POQ", "WW")


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
    poq_periods: int | None = None,
) -> float:
    """
    Apply the configured lot-sizing policy to a single MRP period.

    Policies: LFL, FOQ, EOQ, POQ, WW (rolling-horizon Wagner-Whitin).
    Unknown codes fall back to LFL.

    poq_periods: explicit POQ interval in days. None (default) derives the
    economic interval from the EOQ (see poq_period), clamped to 7–60 days
    (the forecast window handed over by the MRP engine).
    """
    if net_req <= 0:
        return 0.0

    policy = (policy or "LFL").upper()
    if poq_periods is None:
        poq_periods = poq_period(
            annual_demand=annual_demand_value,
            ordering_cost=ordering_cost,
            holding_rate=holding_rate,
            unit_cost=unit_cost,
        )

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
            net_req=net_req,
        )

    elif policy in ("WW", "W-W", "WAGNER-WHITIN"):
        return wagner_whitin_first_order(
            net_req=net_req,
            future_demand=future_demand or [],
            ordering_cost=ordering_cost,
            holding_rate=holding_rate,
            unit_cost=unit_cost,
            moq=moq,
        )

    else:
        # Unknown policy → fall back to LFL
        return lot_for_lot(net_req, moq)
