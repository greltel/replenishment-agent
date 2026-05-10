"""Tests for the cost estimator and enhanced KPI calculator."""
import pandas as pd
import pytest

from src.utils.cost_estimator import (
    HoldingCostComponents, StockoutCostParams, CostScenario,
    impute_unit_cost, impute_costs_in_df,
    SCENARIOS, get_scenario,
    DEFAULT_COST_BY_TYPE, ABC_COST_MULTIPLIER,
)
from src.utils.kpi import (
    KPICalculator, KPIReport, compare_scenarios, sensitivity_pivot,
)


# ============================================================
# HoldingCostComponents
# ============================================================
class TestHoldingCostComponents:
    def test_default_total_rate(self):
        c = HoldingCostComponents()
        assert abs(c.total_rate - 0.20) < 0.001

    def test_conservative_lower_than_realistic(self):
        c = HoldingCostComponents.conservative()
        r = HoldingCostComponents.realistic()
        assert c.total_rate < r.total_rate

    def test_aggressive_higher_than_realistic(self):
        a = HoldingCostComponents.aggressive()
        r = HoldingCostComponents.realistic()
        assert a.total_rate > r.total_rate

    def test_components_sum_to_total(self):
        c = HoldingCostComponents.realistic()
        manual = (c.capital_cost_rate + c.warehouse_rate
                  + c.obsolescence_rate + c.insurance_rate
                  + c.shrinkage_rate)
        assert abs(c.total_rate - manual) < 0.0001

    def test_to_dict_includes_total(self):
        c = HoldingCostComponents()
        d = c.to_dict()
        assert "total_rate" in d
        assert "capital_cost_rate" in d


# ============================================================
# StockoutCostParams
# ============================================================
class TestStockoutCostParams:
    def test_default_values(self):
        sp = StockoutCostParams()
        assert 0 < sp.gross_margin_pct < 1
        assert sp.revenue_multiplier > 1
        assert 0 < sp.expedite_premium_pct < 1

    def test_aggressive_more_expensive(self):
        c = StockoutCostParams.conservative()
        a = StockoutCostParams.aggressive()
        assert a.gross_margin_pct > c.gross_margin_pct
        assert a.expedite_premium_pct > c.expedite_premium_pct


# ============================================================
# Cost imputation
# ============================================================
class TestCostImputation:
    def test_actual_cost_preserved(self):
        result = impute_unit_cost("ROH", "A", actual_cost=42.0)
        assert result == 42.0

    def test_zero_cost_imputed(self):
        result = impute_unit_cost("ROH", "A", actual_cost=0.0)
        assert result > 0

    def test_a_class_more_expensive_than_c(self):
        a_cost = impute_unit_cost("ROH", "A")
        c_cost = impute_unit_cost("ROH", "C")
        assert a_cost > c_cost

    def test_finished_more_expensive_than_raw(self):
        roh = impute_unit_cost("ROH", "B")
        fert = impute_unit_cost("FERT", "B")
        assert fert > roh

    def test_unknown_type_falls_back(self):
        result = impute_unit_cost("UNKNOWN_TYPE", "B")
        assert result > 0   # should not crash, returns default

    def test_dataframe_imputation(self):
        df = pd.DataFrame({
            "material_id":   ["M1", "M2", "M3"],
            "standard_cost": [10.0, 0.0, None],
            "material_type": ["ROH", "FERT", "HALB"],
            "abc_class":     ["A", "B", "C"],
        })
        out = impute_costs_in_df(df)
        # Original col preserved
        assert out["standard_cost"].iloc[0] == 10.0
        # New imputed_cost column
        assert "imputed_cost" in out.columns
        assert out["imputed_cost"].iloc[0] == 10.0   # passed through
        assert out["imputed_cost"].iloc[1] > 0       # imputed
        assert out["imputed_cost"].iloc[2] > 0       # imputed


# ============================================================
# Scenarios
# ============================================================
class TestScenarios:
    def test_three_scenarios_exist(self):
        assert "conservative" in SCENARIOS
        assert "realistic" in SCENARIOS
        assert "aggressive" in SCENARIOS

    def test_get_scenario_default(self):
        s = get_scenario("realistic")
        assert s.name == "realistic"

    def test_get_scenario_unknown_falls_back(self):
        s = get_scenario("nonexistent")
        assert s.name == "realistic"

    def test_get_scenario_case_insensitive(self):
        s = get_scenario("REALISTIC")
        assert s.name == "realistic"

    def test_scenarios_have_descriptions(self):
        for s in SCENARIOS.values():
            assert s.description


# ============================================================
# KPI Calculator with new fields
# ============================================================
class TestEnhancedKPICalculator:
    @pytest.fixture
    def sample_data(self):
        materials = pd.DataFrame({
            "material_id":   ["M1", "M2"],
            "standard_cost": [10.0, 20.0],
            "material_type": ["ROH", "FERT"],
            "abc_class":     ["A", "B"],
        })
        stock = pd.DataFrame({
            "date":        pd.date_range("2025-01-01", periods=10).repeat(2),
            "material_id": ["M1", "M2"] * 10,
            "quantity":    [100, 200] * 10,
        })
        demand = pd.DataFrame({
            "date":          pd.date_range("2025-01-01", periods=5).repeat(2),
            "material_id":   ["M1", "M2"] * 5,
            "requested_qty": [10, 20] * 5,
            "delivered_qty": [10, 20] * 5,
        })
        orders = pd.DataFrame({
            "date":        pd.date_range("2025-01-02", periods=2),
            "material_id": ["M1", "M2"],
            "quantity":    [50, 100],
            "unit_cost":   [10.0, 20.0],
        })
        return materials, stock, demand, orders

    def test_decomposed_holding_cost(self, sample_data):
        materials, stock, demand, orders = sample_data
        calc = KPICalculator(
            stock_history=stock, demand_history=demand,
            orders=orders, materials=materials,
            holding_rate=HoldingCostComponents.realistic(),
        )
        decomp = calc.holding_cost_decomposed()
        # All components present
        for key in ["capital_cost", "warehouse", "obsolescence",
                    "insurance", "shrinkage", "total"]:
            assert key in decomp
            assert decomp[key] >= 0
        # Components sum to total
        component_sum = sum(decomp[k] for k in
                            ["capital_cost", "warehouse", "obsolescence",
                             "insurance", "shrinkage"])
        assert abs(decomp["total"] - component_sum) < 0.01

    def test_stockout_cost_no_shortages(self, sample_data):
        """If everything is delivered, stockout cost should be 0."""
        materials, stock, demand, orders = sample_data
        calc = KPICalculator(
            stock_history=stock, demand_history=demand,
            orders=orders, materials=materials,
        )
        cost = calc.stockout_cost()
        assert cost["lost_sales"] == 0.0

    def test_stockout_cost_with_shortages(self, sample_data):
        """Partial delivery should produce lost_sales > 0."""
        materials, stock, demand, orders = sample_data
        # Shortages
        demand["delivered_qty"] = demand["delivered_qty"] / 2
        calc = KPICalculator(
            stock_history=stock, demand_history=demand,
            orders=orders, materials=materials,
        )
        cost = calc.stockout_cost()
        assert cost["lost_sales"] > 0

    def test_tco_includes_both_components(self, sample_data):
        materials, stock, demand, orders = sample_data
        calc = KPICalculator(
            stock_history=stock, demand_history=demand,
            orders=orders, materials=materials,
        )
        tco = calc.total_cost_of_ownership()
        hc = calc.holding_cost()
        sc = calc.stockout_cost()["total"]
        assert abs(tco - (hc + sc)) < 0.01

    def test_per_abc_breakdown(self, sample_data):
        materials, stock, demand, orders = sample_data
        calc = KPICalculator(
            stock_history=stock, demand_history=demand,
            orders=orders, materials=materials,
        )
        report = calc.report()
        # Each material is a different class, so we should get 2 entries
        assert "A" in report.by_abc_class
        assert "B" in report.by_abc_class
        assert report.by_abc_class["A"]["n_materials"] == 1
        assert report.by_abc_class["B"]["n_materials"] == 1

    def test_days_of_cover_positive(self, sample_data):
        materials, stock, demand, orders = sample_data
        calc = KPICalculator(
            stock_history=stock, demand_history=demand,
            orders=orders, materials=materials,
        )
        # Stock=100, daily demand is small → high days of cover
        assert calc.avg_days_of_cover() > 0

    def test_cost_imputation_when_missing(self):
        """Materials with missing standard_cost get imputed values."""
        materials = pd.DataFrame({
            "material_id":   ["M1"],
            "standard_cost": [0.0],
            "material_type": ["FERT"],
            "abc_class":     ["A"],
        })
        stock = pd.DataFrame({
            "date":        pd.date_range("2025-01-01", periods=3),
            "material_id": ["M1"] * 3,
            "quantity":    [100, 100, 100],
        })
        calc = KPICalculator(
            stock_history=stock,
            demand_history=pd.DataFrame(columns=["date", "material_id",
                                                   "requested_qty", "delivered_qty"]),
            orders=pd.DataFrame(columns=["date", "material_id", "quantity", "unit_cost"]),
            materials=materials,
        )
        # With imputation, holding cost should not be 0
        assert calc.holding_cost() > 0


# ============================================================
# Comparison & sensitivity
# ============================================================
class TestComparison:
    def _make_report(self, **overrides) -> KPIReport:
        defaults = dict(
            cycle_service_level_pct=95.0, fill_rate_pct=98.0,
            holding_cost_eur=1000.0, stockout_days=10,
            inventory_turns=4.0, avg_inventory_eur=5000.0,
            n_orders=20, avg_order_size=100.0,
        )
        defaults.update(overrides)
        return KPIReport(**defaults)

    def test_compare_returns_dataframe(self):
        a = self._make_report()
        t = self._make_report(holding_cost_eur=800.0)
        df = compare_scenarios(a, t)
        assert not df.empty
        assert "metric" in df.columns
        assert "delta_pct" in df.columns

    def test_lower_holding_marked_better(self):
        a = self._make_report(holding_cost_eur=1000.0)
        t = self._make_report(holding_cost_eur=800.0)
        df = compare_scenarios(a, t)
        row = df[df["metric"] == "holding_cost_eur"].iloc[0]
        assert "better" in row["direction"]

    def test_significance_threshold(self):
        a = self._make_report(holding_cost_eur=1000.0)
        t = self._make_report(holding_cost_eur=995.0)  # only 0.5% change
        df = compare_scenarios(a, t)
        row = df[df["metric"] == "holding_cost_eur"].iloc[0]
        assert bool(row["significant"]) is False

    def test_sensitivity_pivot(self):
        results = [
            ("base", self._make_report()),
            ("variant", self._make_report(holding_cost_eur=900.0)),
        ]
        df = sensitivity_pivot(results)
        assert len(df) == 2
        assert "scenario" in df.columns
        assert "holding_cost_eur" in df.columns
