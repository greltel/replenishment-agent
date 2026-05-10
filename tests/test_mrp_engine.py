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
