"""Tests for lot sizing policies."""
import pytest

from src.mrp.lot_sizing import (
    lot_for_lot,
    fixed_order_qty,
    economic_order_qty,
    periodic_order_qty,
    wagner_whitin,
    apply_lot_sizing,
)


# ============================================================
# Lot-for-Lot
# ============================================================
class TestLotForLot:
    def test_returns_zero_when_no_demand(self):
        assert lot_for_lot(0) == 0
        assert lot_for_lot(-5) == 0

    def test_returns_exact_qty(self):
        assert lot_for_lot(50) == 50

    def test_respects_moq(self):
        assert lot_for_lot(20, moq=50) == 50
        assert lot_for_lot(80, moq=50) == 80


# ============================================================
# Fixed Order Quantity
# ============================================================
class TestFixedOrderQty:
    def test_rounds_up_to_multiple(self):
        # need 30, FOQ=50 → order 50
        assert fixed_order_qty(30, foq=50) == 50

    def test_handles_exact_multiple(self):
        assert fixed_order_qty(100, foq=50) == 100

    def test_orders_multiple_lots_when_needed(self):
        # need 75, FOQ=50 → order 100 (2 lots)
        assert fixed_order_qty(75, foq=50) == 100

    def test_respects_moq(self):
        # need 20, FOQ=10, MOQ=50 → order 50 (MOQ wins over multiples of FOQ)
        result = fixed_order_qty(20, foq=10, moq=50)
        assert result >= 50


# ============================================================
# Economic Order Quantity
# ============================================================
class TestEOQ:
    def test_classic_eoq_formula(self):
        # D=1000, S=50, h=0.20, c=10 → H=2 → EOQ = sqrt(2*1000*50/2) = 223.6
        result = economic_order_qty(
            annual_demand=1000, ordering_cost=50,
            holding_rate=0.20, unit_cost=10, current_need=100
        )
        assert 220 < result < 230

    def test_returns_zero_if_no_need(self):
        result = economic_order_qty(
            annual_demand=1000, ordering_cost=50,
            holding_rate=0.20, unit_cost=10, current_need=0
        )
        assert result == 0

    def test_falls_back_when_holding_zero(self):
        result = economic_order_qty(
            annual_demand=1000, ordering_cost=50,
            holding_rate=0, unit_cost=10, current_need=50, moq=20
        )
        assert result >= 50


# ============================================================
# Periodic Order Quantity
# ============================================================
class TestPOQ:
    def test_covers_n_periods(self):
        future_demand = [10] * 30
        result = periodic_order_qty(future_demand, n_periods=7)
        assert result == 70

    def test_empty_demand(self):
        assert periodic_order_qty([], n_periods=7, moq=20) == 20


# ============================================================
# Wagner-Whitin
# ============================================================
class TestWagnerWhitin:
    def test_simple_case(self):
        # Demand: 10, 20, 30 / setup=100 / holding=1
        # Optimal: order all 60 in period 1 if holding cheap, or split
        orders = wagner_whitin([10, 20, 30], setup_cost=100, holding_cost_per_unit_per_period=1)
        # The total ordered should equal total demand
        assert sum(orders) == 60

    def test_empty_demand(self):
        assert wagner_whitin([], 100, 1) == []

    def test_high_holding_cost_orders_per_period(self):
        # When holding cost is huge relative to setup, order per period
        orders = wagner_whitin([10, 20, 30], setup_cost=1, holding_cost_per_unit_per_period=1000)
        # Should order each period separately
        nonzero = sum(1 for o in orders if o > 0)
        assert nonzero == 3


# ============================================================
# Dispatcher
# ============================================================
class TestApplyLotSizing:
    def test_dispatches_to_lfl(self):
        assert apply_lot_sizing(net_req=50, policy="LFL") == 50

    def test_dispatches_to_foq(self):
        result = apply_lot_sizing(net_req=30, policy="FOQ", fixed_lot_size=50)
        assert result == 50

    def test_dispatches_to_eoq(self):
        result = apply_lot_sizing(
            net_req=50, policy="EOQ",
            annual_demand_value=1000, ordering_cost=50,
            holding_rate=0.20, unit_cost=10,
        )
        assert result > 0

    def test_unknown_policy_falls_back_to_lfl(self):
        result = apply_lot_sizing(net_req=50, policy="UNKNOWN")
        assert result == 50

    def test_zero_demand_returns_zero(self):
        assert apply_lot_sizing(net_req=0, policy="LFL") == 0


class TestPolicySelection:
    """ABC × CV automatic policy choice (thesis Table 4.3)."""

    def test_table_4_3_mapping(self):
        from src.mrp.lot_sizing import select_policy
        assert select_policy("A", 0.3) == "WW"
        assert select_policy("A", 0.5) == "POQ"
        assert select_policy("A", 1.0) == "POQ"
        assert select_policy("A", 1.4) == "LFL"
        assert select_policy("B", 0.2) == "EOQ"
        assert select_policy("B", 2.0) == "EOQ"
        assert select_policy("C", 0.1) == "FOQ"
        assert select_policy("C", 3.0) == "FOQ"

    def test_sparse_history_falls_back_to_lfl(self):
        from src.mrp.lot_sizing import select_policy
        assert select_policy("A", 0.2, n_events=2) == "LFL"
        assert select_policy("C", 0.2, n_events=0) == "LFL"
        assert select_policy("A", None) == "LFL"

    def test_enrichment_keeps_explicit_sap_procedure(self):
        from src.data_layer.master_data_enrichment import MaterialStats, derive_lot_sizing
        s = MaterialStats(material_id="M", n_consumption_events=50, cv_weekly=0.2)
        assert derive_lot_sizing("POQ", s, "A") == ("POQ", "MARC.DISLS")
        # the LFL placeholder is overridden by the ABC × CV choice
        policy, source = derive_lot_sizing("LFL", s, "A")
        assert policy == "WW" and source.startswith("derived")
        assert derive_lot_sizing(None, s, "C")[0] == "FOQ"

    def test_fixed_lot_for_foq_is_moq_multiple(self):
        from src.data_layer.master_data_enrichment import MaterialStats, derive_fixed_lot_size
        s = MaterialStats(material_id="M", avg_daily_demand=3.0)
        lot, src = derive_fixed_lot_size(0, s, moq=10.0, policy="FOQ")
        assert lot == 90.0 and lot % 10 == 0          # 4 weeks × 3/day = 84 → 90
        assert derive_fixed_lot_size(0, s, moq=10.0, policy="EOQ")[0] == 0.0
        assert derive_fixed_lot_size(120.0, s, moq=10.0, policy="FOQ") == (120.0, "MARC.BSTFE")
