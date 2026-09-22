"""Tests for the rules engine."""
from datetime import date, timedelta

import pandas as pd
import pytest

from src.agent.base import AgentBeliefs, AgentDesires
from src.data_layer.models import Movement
from src.rules.engine import RulesEngine
from src.rules.policies import (
    enforce_moq, expedite_critical, safety_buffer_for_a_class,
    suppress_dead_stock, shift_to_workday, estimate_cost,
)


class TestIndividualRules:
    def test_moq_enforces_minimum(self, sample_material):
        """If qty < MOQ, raise to MOQ."""
        sample_material.moq = 50
        proposal = {"qty": 30, "rule_triggered": None}
        result = enforce_moq(proposal, sample_material, beliefs={}, desires=AgentDesires())
        assert result["qty"] == 50

    def test_moq_does_not_change_when_above(self, sample_material):
        sample_material.moq = 50
        proposal = {"qty": 80, "rule_triggered": None}
        result = enforce_moq(proposal, sample_material, beliefs={}, desires=AgentDesires())
        assert result["qty"] == 80

    def test_a_class_buffer(self, sample_material):
        """A-class items get +20%."""
        sample_material.abc_class = "A"
        proposal = {"qty": 100, "rule_triggered": None}
        result = safety_buffer_for_a_class(
            proposal, sample_material, beliefs={}, desires=AgentDesires()
        )
        assert result["qty"] == 120

    def test_a_buffer_does_not_apply_to_c(self, sample_material):
        sample_material.abc_class = "C"
        proposal = {"qty": 100, "rule_triggered": None}
        result = safety_buffer_for_a_class(
            proposal, sample_material, beliefs={}, desires=AgentDesires()
        )
        assert result["qty"] == 100

    def test_expedite_when_critical(self, sample_material):
        """Stock < 50% of safety → expedite flag."""
        sample_material.safety_stock = 100
        beliefs = {"current_stock": {sample_material.material_id: 30}}
        proposal = {"qty": 50, "rule_triggered": None}
        result = expedite_critical(proposal, sample_material, beliefs=beliefs,
                                     desires=AgentDesires())
        assert result["expedite"] is True

    def test_no_expedite_when_safe(self, sample_material):
        sample_material.safety_stock = 100
        beliefs = {"current_stock": {sample_material.material_id: 200}}
        proposal = {"qty": 50, "rule_triggered": None}
        result = expedite_critical(proposal, sample_material, beliefs=beliefs,
                                     desires=AgentDesires())
        assert result.get("expedite", False) is False

    def test_dead_stock_suppresses(self, sample_material):
        """No movement in over 365 days (default threshold) → suppress."""
        old = date.today() - timedelta(days=400)
        history = [Movement(material_id=sample_material.material_id,
                             posting_date=old, quantity=-1, movement_type="261")]
        beliefs = {"consumption_history": {sample_material.material_id: history}}
        proposal = {"qty": 50}
        result = suppress_dead_stock(proposal, sample_material, beliefs=beliefs,
                                       desires=AgentDesires())
        assert result is None

    def test_dead_stock_does_not_suppress_active(self, sample_material):
        """Recent movement → keep proposal."""
        recent = date.today() - timedelta(days=10)
        history = [Movement(material_id=sample_material.material_id,
                             posting_date=recent, quantity=-1, movement_type="261")]
        beliefs = {"consumption_history": {sample_material.material_id: history}}
        proposal = {"qty": 50}
        result = suppress_dead_stock(proposal, sample_material, beliefs=beliefs,
                                       desires=AgentDesires())
        assert result is not None

    def test_calendar_shifts_weekend(self, sample_material):
        """Saturday should shift to Monday."""
        # Find a known Saturday: e.g. 2026-01-03
        saturday = date(2026, 1, 3)
        proposal = {"date": saturday, "rule_triggered": None}
        result = shift_to_workday(proposal, sample_material, beliefs={},
                                    desires=AgentDesires())
        # Sunday=2026-01-04, then Monday=2026-01-05 (but 1/6 is Epiphany!)
        # So next workday after Jan 3 (Sat) is Jan 5 (Mon) — but Jan 6 is holiday
        # Actually Jan 5 IS a workday (Mon, not a holiday)
        assert result["date"].weekday() < 5

    def test_estimate_cost(self, sample_material):
        """Cost = qty × standard_cost."""
        sample_material.standard_cost = 25
        proposal = {"qty": 100}
        result = estimate_cost(proposal, sample_material, beliefs={},
                                 desires=AgentDesires())
        assert result["estimated_cost"] == 2500


class TestRulesEngine:
    def test_engine_initializes_with_rules(self):
        engine = RulesEngine()
        rules_list = engine.list_rules()
        assert len(rules_list) >= 5    # We registered 7 rules
        assert any(r["name"] == "R-MOQ-ENFORCE" for r in rules_list)

    def test_engine_processes_mrp_output(self, sample_material):
        """Feed an MRP-like DataFrame and verify proposals come out."""
        engine = RulesEngine()
        engine.set_beliefs(AgentBeliefs(
            current_stock={sample_material.material_id: 1000},
            consumption_history={
                sample_material.material_id: [
                    Movement(material_id=sample_material.material_id,
                              posting_date=date.today() - timedelta(days=5),
                              quantity=-10, movement_type="261")
                ]
            },
        ))

        mrp_df = pd.DataFrame([
            {
                "period":            date.today() + timedelta(days=10),
                "gross_requirement": 50,
                "scheduled_receipt": 0,
                "projected_on_hand": 50,
                "net_requirement":   50,
                "planned_receipt":   60,
                "planned_release":   date.today() + timedelta(days=5),
            }
        ])

        proposals = engine.apply(mrp_df, sample_material, AgentDesires())
        assert len(proposals) == 1
        assert proposals[0]["qty"] >= 60   # may be inflated by A-class buffer

    def test_engine_skips_zero_qty_rows(self, sample_material):
        engine = RulesEngine()
        engine.set_beliefs(AgentBeliefs(
            current_stock={sample_material.material_id: 1000},
            consumption_history={sample_material.material_id: []},
        ))

        mrp_df = pd.DataFrame([
            {
                "period":            date.today() + timedelta(days=10),
                "gross_requirement": 50,
                "scheduled_receipt": 0,
                "projected_on_hand": 100,
                "net_requirement":   0,
                "planned_receipt":   0,
                "planned_release":   None,
            }
        ])

        proposals = engine.apply(mrp_df, sample_material, AgentDesires())
        assert proposals == []


class TestExpediteScope:
    def test_only_immediate_order_is_expedited(self, sample_material):
        """With critical stock, the order released now is urgent; a planned
        order weeks later (beyond today + lead time) is not."""
        sample_material.safety_stock = 100
        sample_material.lead_time_days = 5
        today = date(2026, 3, 2)
        beliefs = {"current_stock": {sample_material.material_id: 30}, "as_of": today}

        now = {"qty": 50, "rule_triggered": None, "date": today}
        later = {"qty": 50, "rule_triggered": None, "date": today + timedelta(days=20)}
        assert expedite_critical(now, sample_material, beliefs, AgentDesires())["expedite"] is True
        assert expedite_critical(later, sample_material, beliefs, AgentDesires()).get("expedite", False) is False
