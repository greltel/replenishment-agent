"""Rule policy configuration (config/rules.json): defaults, overrides,
on/off switches, persistence with changelog, and the engine's trace."""
from datetime import date

import pandas as pd
import pytest

from src.data_layer.models import Movement

from src.rules.engine import RulesEngine
from src.rules.policies import safety_buffer_for_a_class, long_lead_supplier_buffer
from src.rules.rules_config import (
    RULE_CATALOG, RULE_ORDER, RulesConfig, DEFAULT_PATH, set_active, get_active,
)


@pytest.fixture(autouse=True)
def _reset_active_policy():
    """Every test starts from the thesis defaults and leaves them behind."""
    set_active(RulesConfig())
    yield
    set_active(RulesConfig())


class TestDefaults:
    def test_catalog_covers_all_seven_rules_in_priority_order(self):
        assert RULE_ORDER == ["R-DEAD-STOCK", "R-EXPEDITE", "R-SAFETY-BUFFER-A",
                              "R-LONG-LEAD-BUFFER", "R-MOQ-ENFORCE",
                              "R-CALENDAR-SHIFT", "R-COST-ESTIMATE"]

    def test_defaults_are_the_thesis_values(self):
        cfg = RulesConfig()
        assert cfg.param("R-SAFETY-BUFFER-A", "buffer_pct") == 20
        assert cfg.param("R-LONG-LEAD-BUFFER", "threshold_days") == 30
        assert cfg.param("R-LONG-LEAD-BUFFER", "buffer_pct") == 15
        assert cfg.param("R-EXPEDITE", "stock_vs_safety_pct") == 50
        assert cfg.param("R-DEAD-STOCK", "inactive_days") == 365
        assert all(cfg.is_enabled(n) for n in RULE_ORDER)

    def test_shipped_policy_file_equals_defaults(self):
        """config/rules.json in the repo must reproduce the thesis numbers."""
        assert DEFAULT_PATH.exists()
        assert RulesConfig.load(DEFAULT_PATH).diff(RulesConfig()) == []

    def test_missing_file_means_defaults(self, tmp_path):
        cfg = RulesConfig.load(tmp_path / "nope.json")
        assert cfg.diff(RulesConfig()) == []

    def test_describe_fills_live_values(self):
        cfg = RulesConfig()
        cfg.set_param("R-LONG-LEAD-BUFFER", "threshold_days", 45)
        d = cfg.describe("R-LONG-LEAD-BUFFER")
        assert "45 ημέρες" in d["when"]
        assert "+15% αν LT > 45" in cfg.summary_label("R-LONG-LEAD-BUFFER")


class TestRulesReadThePolicy:
    def test_buffer_pct_override_changes_quantity(self, sample_material):
        sample_material.abc_class = "A"
        cfg = RulesConfig(); cfg.set_param("R-SAFETY-BUFFER-A", "buffer_pct", 10); set_active(cfg)
        out = safety_buffer_for_a_class({"qty": 100.0, "rule_triggered": None}, sample_material, {}, None)
        assert out["qty"] == pytest.approx(110.0)

    def test_disabled_rule_leaves_proposal_untouched(self, sample_material):
        sample_material.abc_class = "A"
        cfg = RulesConfig(); cfg.set_enabled("R-SAFETY-BUFFER-A", False); set_active(cfg)
        out = safety_buffer_for_a_class({"qty": 100.0, "rule_triggered": None}, sample_material, {}, None)
        assert out["qty"] == 100.0 and not out["rule_triggered"]

    def test_long_lead_threshold_override(self, sample_material):
        sample_material.lead_time_days = 40
        cfg = RulesConfig(); cfg.set_param("R-LONG-LEAD-BUFFER", "threshold_days", 45); set_active(cfg)
        out = long_lead_supplier_buffer({"qty": 100.0, "rule_triggered": None}, sample_material, {}, None)
        assert out["qty"] == 100.0            # 40 < 45: no buffer
        cfg.set_param("R-LONG-LEAD-BUFFER", "threshold_days", 30)
        out = long_lead_supplier_buffer({"qty": 100.0, "rule_triggered": None}, sample_material, {}, None)
        assert out["qty"] == pytest.approx(115.0)

    def test_engine_installs_its_config_as_active(self):
        cfg = RulesConfig(); cfg.set_enabled("R-CALENDAR-SHIFT", False)
        engine = RulesEngine(config=cfg)
        assert get_active() is cfg
        active = {r["name"]: r["active"] for r in engine.list_rules()}
        assert active["R-CALENDAR-SHIFT"] is False and active["R-MOQ-ENFORCE"] is True


class TestPersistence:
    def test_save_writes_file_and_changelog(self, tmp_path):
        path = tmp_path / "rules.json"
        base = RulesConfig()
        cfg = RulesConfig(); cfg.set_param("R-SAFETY-BUFFER-A", "buffer_pct", 25)
        cfg.set_enabled("R-DEAD-STOCK", False)
        cfg.save(path, changed_by="Υπεύθυνος Σχεδιασμού", note="δοκιμή", previous=base)
        again = RulesConfig.load(path)
        assert again.param("R-SAFETY-BUFFER-A", "buffer_pct") == 25
        assert again.is_enabled("R-DEAD-STOCK") is False
        log = (tmp_path / "rules_changelog.csv").read_text(encoding="utf-8")
        assert "Υπεύθυνος Σχεδιασμού" in log and "buffer_pct: 20 → 25" in log and "ανενεργός" in log

    def test_unknown_rule_in_file_is_ignored(self, tmp_path):
        path = tmp_path / "rules.json"
        path.write_text('{"version": 1, "rules": {"R-NOPE": {"enabled": false}}}', encoding="utf-8")
        cfg = RulesConfig.load(path)
        assert cfg.diff(RulesConfig()) == []


class TestTrace:
    def test_trace_records_every_step(self, sample_material):
        sample_material.abc_class = "A"
        sample_material.lead_time_days = 31
        sample_material.moq = 4
        sample_material.uom = "SET"
        sample_material.fixed_lot_size = 0
        sample_material.standard_cost = 79.29
        mrp = pd.DataFrame([{
            "period": date(2026, 11, 7), "planned_receipt": 51.0,
            "planned_release": date(2026, 10, 7), "planned_arrival": date(2026, 11, 7),
        }])
        engine = RulesEngine(config=RulesConfig())
        recent = [Movement(material_id=sample_material.material_id, posting_date=date(2026, 9, 16),
                           quantity=-4, movement_type="601")]
        engine.set_beliefs({"as_of": date(2026, 9, 21), "current_stock": {sample_material.material_id: 223.0},
                            "consumption_history": {sample_material.material_id: recent}})
        trace = []
        out = engine.apply(mrp, sample_material, desires=None, trace=trace)
        rules = [t["rule"] for t in trace]
        assert rules == ["MRP"] + RULE_ORDER
        qty = {t["rule"]: t["qty_after"] for t in trace}
        assert qty["R-SAFETY-BUFFER-A"] == pytest.approx(61.2)
        assert qty["R-LONG-LEAD-BUFFER"] == pytest.approx(70.38)
        assert qty["R-MOQ-ENFORCE"] == 71.0
        assert out[0]["qty"] == 71.0
