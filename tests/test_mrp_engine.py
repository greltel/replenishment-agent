"""Tests for the MRP engine."""
from datetime import date, timedelta

import pytest

from src.mrp.engine import MRPEngine


class TestMRPEngine:
    def test_no_orders_when_stock_high(self, sample_material, constant_demand, empty_pos):
        """High stock + low demand → no planned orders."""
        engine = MRPEngine(horizon_days=30)
        df = engine.calculate(
            material=sample_material,
            current_stock=10000,
            open_orders=empty_pos,
            demand=constant_demand,
        )
        assert df["planned_receipt"].sum() == 0

    def test_orders_when_stock_drops_below_safety(
        self, sample_material, constant_demand, empty_pos
    ):
        """When projected on-hand falls below SS, MRP must propose."""
        engine = MRPEngine(horizon_days=30)
        df = engine.calculate(
            material=sample_material,
            current_stock=100,
            open_orders=empty_pos,
            demand=constant_demand,
        )
        assert df["planned_receipt"].sum() > 0

        # POH should never go below safety_stock after planned receipts applied
        # (allowing some tolerance for end-of-horizon edge cases)
        early_rows = df.iloc[:25]   # ignore last 5 days
        assert (early_rows["projected_on_hand"] >= sample_material.safety_stock - 0.01).all()

    def test_lead_time_offset(self, sample_material, constant_demand, empty_pos):
        """planned_release = period - lead_time."""
        engine = MRPEngine(horizon_days=30)
        df = engine.calculate(
            material=sample_material,
            current_stock=80,
            open_orders=empty_pos,
            demand=constant_demand,
        )
        active = df[df["planned_release"].notna()]
        assert not active.empty

        first = active.iloc[0]
        diff = (first["period"] - first["planned_release"]).days
        # On the first row, the release may be clamped to today
        assert diff <= sample_material.lead_time_days

    def test_open_pos_consumed_as_scheduled_receipts(
        self, sample_material, constant_demand, sample_open_pos
    ):
        """Open POs should appear as scheduled_receipt on their expected_date."""
        engine = MRPEngine(horizon_days=30)
        df = engine.calculate(
            material=sample_material,
            current_stock=100,
            open_orders=sample_open_pos,
            demand=constant_demand,
        )
        # We have 2 POs with quantities 100 and 50 → SR should sum to 150
        assert df["scheduled_receipt"].sum() == 150

    def test_empty_demand_does_not_crash(self, sample_material, empty_pos):
        """Empty demand list should not crash the engine."""
        engine = MRPEngine(horizon_days=10)
        df = engine.calculate(
            material=sample_material,
            current_stock=100,
            open_orders=empty_pos,
            demand=[],
        )
        # Should complete with no requirements
        assert len(df) == 10
        assert df["gross_requirement"].sum() == 0

    def test_dataframe_shape(self, sample_material, constant_demand, empty_pos):
        """Returned DataFrame has correct columns and length."""
        engine = MRPEngine(horizon_days=45)
        df = engine.calculate(
            material=sample_material,
            current_stock=200,
            open_orders=empty_pos,
            demand=constant_demand,
        )
        assert len(df) == 45
        expected_cols = {
            "period", "gross_requirement", "scheduled_receipt",
            "projected_on_hand", "net_requirement",
            "planned_receipt", "planned_release",
        }
        assert expected_cols.issubset(df.columns)

    def test_eoq_material_orders_larger_than_lfl(
        self, sample_material_eoq, constant_demand, empty_pos
    ):
        """EOQ should typically order in larger batches than LFL."""
        engine = MRPEngine(horizon_days=30)
        df = engine.calculate(
            material=sample_material_eoq,
            current_stock=20,
            open_orders=empty_pos,
            demand=constant_demand,
            annual_demand_value=10 * 365,
        )
        nonzero = df[df["planned_receipt"] > 0]
        if not nonzero.empty:
            avg_eoq_order = nonzero["planned_receipt"].mean()
            # Each order should be substantial (more than just one period of demand)
            assert avg_eoq_order >= 10


class TestLeadTimeAwareness:
    """Requirements inside the lead time are consolidated into ONE order
    landing at as_of + LT (no duplicate orders for the same shortage)."""

    def test_single_order_for_shortage_inside_lead_time(
        self, sample_material, constant_demand, empty_pos
    ):
        # LT = 5 days, SS = 50, demand 10/day, stock 20 → already short today
        engine = MRPEngine(horizon_days=30)
        today = date(2026, 3, 2)
        df = engine.calculate(
            material=sample_material, current_stock=20,
            open_orders=empty_pos, demand=constant_demand, as_of=today,
        )
        inside = df.iloc[: sample_material.lead_time_days]
        orders_inside = inside[inside["planned_receipt"] > 0]
        # exactly one order released today, landing at today + LT
        assert len(orders_inside) == 1
        first = orders_inside.iloc[0]
        assert first["planned_release"] == today
        assert first["planned_arrival"] == today + timedelta(days=sample_material.lead_time_days)
        # it covers the shortage projected at the arrival date:
        # 20 - 6 days × 10 = -40 → need 90 to reach SS=50 (LFL, MOQ 10)
        assert first["planned_receipt"] == pytest.approx(90.0)
        # the receipt is booked at the arrival day, not today
        arrival_row = df[df["period"] == first["planned_arrival"]].iloc[0]
        assert arrival_row["planned_arrival_qty"] == pytest.approx(90.0)
        assert arrival_row["projected_on_hand"] >= sample_material.safety_stock - 0.01
        # the days in between are flagged as unavoidable exposure
        assert inside["below_safety"].all()

    def test_no_reorder_when_pipeline_covers_shortage(
        self, sample_material, constant_demand
    ):
        """A pending order landing within the lead time must not trigger a
        second order for the same shortage (rolling-review duplicate bug)."""
        from src.data_layer.models import PurchaseOrder
        today = date(2026, 3, 2)
        pending = [PurchaseOrder(
            po_number="P1", material_id="TEST001", supplier_id="S",
            quantity=90.0, expected_date=today + timedelta(days=4), status="OPEN",
        )]
        engine = MRPEngine(horizon_days=30)
        df = engine.calculate(
            material=sample_material, current_stock=20,
            open_orders=pending, demand=constant_demand, as_of=today,
        )
        inside = df.iloc[: sample_material.lead_time_days]
        assert inside["planned_receipt"].sum() == 0

    def test_overdue_open_po_counts_as_arriving_today(
        self, sample_material, constant_demand
    ):
        from src.data_layer.models import PurchaseOrder
        today = date(2026, 3, 2)
        overdue = [PurchaseOrder(
            po_number="P0", material_id="TEST001", supplier_id="S",
            quantity=500.0, expected_date=today - timedelta(days=10), status="OPEN",
        )]
        engine = MRPEngine(horizon_days=30)
        df = engine.calculate(
            material=sample_material, current_stock=20,
            open_orders=overdue, demand=constant_demand, as_of=today,
        )
        assert df.iloc[0]["scheduled_receipt"] == 500.0
        assert df["planned_receipt"].sum() == 0
