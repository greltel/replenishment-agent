"""Tests for the rule-ablation feature in RulesEngine."""
from __future__ import annotations

import pytest

from src.rules.engine import RulesEngine
from src.rules.policies import RULES_REGISTRY


class TestRuleAblation:
    """Verify that disabled_rules parameter works correctly."""

    def test_default_no_rules_disabled(self):
        """By default all rules are active."""
        engine = RulesEngine()
        assert len(engine.disabled_rules) == 0
        # All registered rules are active
        assert len(engine.rules) == len(RULES_REGISTRY)

    def test_disable_single_rule(self):
        """Disabling one rule excludes it from the active set."""
        engine = RulesEngine(disabled_rules={"R-EXPEDITE"})
        active = engine.active_rule_names()
        assert "R-EXPEDITE" not in active
        # All others present
        assert len(active) == len(RULES_REGISTRY) - 1

    def test_disable_multiple_rules(self):
        """Disabling several rules removes all of them."""
        engine = RulesEngine(disabled_rules={"R-EXPEDITE", "R-DEAD-STOCK"})
        active = engine.active_rule_names()
        assert "R-EXPEDITE" not in active
        assert "R-DEAD-STOCK" not in active
        assert len(active) == len(RULES_REGISTRY) - 2

    def test_disable_unknown_rule_is_noop(self):
        """Disabling a non-existent rule name doesn't break anything."""
        engine = RulesEngine(disabled_rules={"R-DOES-NOT-EXIST"})
        # All real rules still active
        assert len(engine.rules) == len(RULES_REGISTRY)

    def test_list_rules_marks_disabled(self):
        """list_rules() output includes an 'active' flag."""
        engine = RulesEngine(disabled_rules={"R-MOQ-ENFORCE"})
        rules_info = engine.list_rules()
        moq = next(r for r in rules_info if r["name"] == "R-MOQ-ENFORCE")
        assert moq["active"] is False
        # Other rules still marked active
        for r in rules_info:
            if r["name"] != "R-MOQ-ENFORCE":
                assert r["active"] is True

    def test_disabled_rule_name_set_preserved(self):
        """The .disabled_rules attribute matches what was passed."""
        engine = RulesEngine(disabled_rules=["R-EXPEDITE"])
        assert engine.disabled_rules == {"R-EXPEDITE"}

    def test_priority_order_maintained_when_disabling(self):
        """Active rules remain sorted by priority after exclusion."""
        engine = RulesEngine(disabled_rules={"R-EXPEDITE"})
        priorities = [
            getattr(r, "priority", 100) for r in engine.rules
        ]
        assert priorities == sorted(priorities)


class TestAblationOutputs:
    """Smoke tests for the ablation script's data structures."""

    def test_ablation_result_dataclass_creates(self):
        from scripts.run_rule_ablation import AblationResult
        r = AblationResult(
            disabled_rule="R-EXPEDITE",
            label="without R-EXPEDITE",
            n_proposals=100,
            service_level=95.0,
            fill_rate=98.0,
            holding_cost=10000.0,
            stockout_cost=500.0,
            stockout_days=5,
            tco=10500.0,
            inventory_turns=4.0,
            n_orders=20,
        )
        assert r.disabled_rule == "R-EXPEDITE"
        assert r.tco == 10500.0

    def test_to_dataframe_with_baseline(self):
        """Conversion to DataFrame produces correct delta calculations."""
        from scripts.run_rule_ablation import AblationResult, to_dataframe

        baseline = AblationResult(
            disabled_rule=None, label="BASELINE",
            n_proposals=100, service_level=99.0, fill_rate=99.5,
            holding_cost=10000.0, stockout_cost=500.0, stockout_days=3,
            tco=10500.0, inventory_turns=4.0, n_orders=20,
        )
        ablation = AblationResult(
            disabled_rule="R-X", label="without R-X",
            n_proposals=90, service_level=95.0, fill_rate=97.0,
            holding_cost=8000.0, stockout_cost=1500.0, stockout_days=10,
            tco=9500.0, inventory_turns=4.5, n_orders=18,
        )

        df = to_dataframe([baseline, ablation])
        assert len(df) == 2

        baseline_row = df.iloc[0]
        assert baseline_row["Δ_proposals"] == 0
        assert baseline_row["Δ_service_pp"] == 0

        ablation_row = df.iloc[1]
        assert ablation_row["Δ_proposals"] == -10
        assert ablation_row["Δ_service_pp"] == -4.0
        assert ablation_row["Δ_holding"] == -2000.0
        assert ablation_row["Δ_stockout_days"] == 7
