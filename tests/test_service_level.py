"""
Target service level per ABC class (SERVICE_LEVEL_BY_ABC,
src/mrp/service_level.py): parsing, the agent's desires, the safety stock
the agent and the enrichment compute, and the unchanged default.
Hand-computed values check the formulas, not only that the code runs.
"""
from __future__ import annotations

import math
from dataclasses import replace
from datetime import date, timedelta

import pandas as pd
import pytest

from src.agent.base import AgentDesires
from src.config import config
from src.data_layer.models import Material, Movement, Stock
from src.mrp import demand_pattern as dp
from src.mrp import service_level as sl

AS_OF = date(2026, 2, 6)


# ----------------------------------------------------------------------
# Parsing and lookup
# ----------------------------------------------------------------------
def test_parse_service_levels():
    assert sl.parse_service_levels("A=0.98,B=0.95,C=0.90") == {"A": 0.98, "B": 0.95, "C": 0.90}
    # percent, spaces, lower case, a trailing comma
    assert sl.parse_service_levels(" a=98 , B=95%, ") == {"A": 0.98, "B": 0.95}
    assert sl.parse_service_levels("") == {} and sl.parse_service_levels(None) == {}
    assert sl.parse_service_levels("uniform") == {} == sl.parse_service_levels(" Uniform ")


@pytest.mark.parametrize("bad", ["A0.9", "=0.9", "A=x", "A=0.3", "A=100", "A=1.0"])
def test_parse_service_levels_rejects_typos(bad):
    with pytest.raises(ValueError, match="SERVICE_LEVEL_BY_ABC"):
        sl.parse_service_levels(bad)


def test_parsed_levels_are_a_copy():
    first = sl.parse_service_levels("A=0.98")
    first["A"] = 0.5
    assert sl.parse_service_levels("A=0.98") == {"A": 0.98}


def test_service_level_for_class_and_default():
    levels = {"A": 0.98, "C": 0.90}
    assert sl.service_level_for("C", 0.98, levels) == 0.90
    assert sl.service_level_for("c", 0.98, levels) == 0.90
    assert sl.service_level_for("B", 0.97, levels) == 0.97       # not listed → default
    assert sl.service_level_for(None, 0.97, levels) == 0.97      # no class → default
    assert sl.service_level_for("A", 0.97, {}) == 0.97


def test_describe():
    assert sl.describe({}, 0.98) == "98%"
    assert sl.describe({"A": 0.995, "C": 0.9}, 0.98) == "A 99.5% · B 98% · C 90%"


def test_desires_default_is_the_uniform_target():
    """Without SERVICE_LEVEL_BY_ABC every material keeps 98 % (thesis)."""
    assert sl.parse_service_levels(config.service_level_by_abc) == {}
    d = AgentDesires()
    assert d.service_level_by_abc == {}
    assert {d.service_level_for(c) for c in ("A", "B", "C", None)} == {0.98}


def test_desires_per_class():
    d = AgentDesires(service_level_by_abc=sl.parse_service_levels("A=0.99,C=0.90"))
    assert (d.service_level_for("A"), d.service_level_for("B"),
            d.service_level_for("C")) == (0.99, 0.98, 0.90)


# ----------------------------------------------------------------------
# The agent (DEMAND_POLICY=pattern)
# ----------------------------------------------------------------------
def _moves(mid: str, weekly: list[float]) -> list[Movement]:
    out = []
    for w, q in enumerate(weekly):
        if q:
            day = AS_OF - timedelta(days=(51 - w) * 7)
            out.append(Movement(material_id=mid, plant="P", movement_type="601",
                                quantity=-float(q), posting_date=day))
    return out


@pytest.fixture
def pattern_agent(in_memory_repo, monkeypatch):
    """Three intermittent materials with the same demand (13 demand weeks of
    1 unit: λ = 13/52 · 14/7 = 0.5 demand weeks in the lead time); their
    cost 70 / 20 / 10 makes the ABC class of the demand value A / B / C
    (Pareto 70 / 90 / 100 %). The master data say the opposite (C / B / A),
    as if the classes had been set on other sales."""
    import src.agent.replenishment as agent_mod
    monkeypatch.setattr(agent_mod, "config", replace(config, demand_policy="pattern"))
    repo = in_memory_repo
    for mid, cost, master_cls in (("IA", 70.0, "C"), ("IB", 20.0, "B"), ("IC", 10.0, "A")):
        repo.session.add(Material(material_id=mid, lead_time_days=14, standard_cost=cost,
                                  safety_stock=7.0, moq=1.0, lot_sizing="LFL",
                                  abc_class=master_cls))
        repo.session.add(Stock(material_id=mid, plant="P", location="L", quantity=0,
                               snapshot_date=AS_OF))
        repo.session.add_all(_moves(mid, [1, 0, 0, 0] * 13))
    repo.commit()

    def run(spec: str):
        from src.agent.replenishment import ReplenishmentAgent
        from src.mrp.engine import MRPEngine
        from src.rules.engine import RulesEngine
        agent = ReplenishmentAgent(repo, MRPEngine(horizon_days=30), RulesEngine())
        agent.desires.service_level_by_abc = sl.parse_service_levels(spec)
        agent.perceive(as_of=AS_OF)
        agent.deliberate(as_of=AS_OF)
        return agent.beliefs
    return run


def test_agent_safety_stock_per_class(pattern_agent):
    """Lead-time demand Poisson(0.5) of 1-unit weeks:
    P(≤1) = 1.5·e^-0.5 = 0.910, P(≤2) = 0.986 →
    s* = 2 for 95 % and 98 % (SS 1.5), s* = 1 for 90 % (SS 0.5)."""
    assert 1.5 * math.exp(-0.5) == pytest.approx(0.9098, abs=1e-4)
    uniform = pattern_agent("")
    assert uniform.safety_stock == {"IA": 1.5, "IB": 1.5, "IC": 1.5}
    assert uniform.abc_class == {}                 # not derived without levels
    per_class = pattern_agent("A=0.90,B=0.95,C=0.98")
    # the class of the demand value up to as_of, not the master data's
    assert per_class.abc_class == {"IA": "A", "IB": "B", "IC": "C"}
    assert per_class.safety_stock == {"IA": 0.5, "IB": 1.5, "IC": 1.5}


def test_abc_classes_rule_of_the_enrichment():
    assert sl.abc_classes({"X": (10, 7.0), "Y": (10, 2.0), "Z": (10, 1.0), "N": (0, 5.0)}) == {
        "X": "A", "Y": "B", "Z": "C", "N": "C"}
    # no cost at all → Pareto on the quantity (the enrichment's fallback)
    assert sl.abc_classes({"X": (70, 0), "Y": (20, None), "Z": (10, 0)}) == {
        "X": "A", "Y": "B", "Z": "C"}
    assert sl.abc_classes({}) == {}


def test_desires_read_the_setting(monkeypatch):
    import src.config as config_mod
    monkeypatch.setattr(config_mod, "config", replace(config, service_level_by_abc="C=0.90"))
    assert AgentDesires().service_level_for("C") == 0.90
    assert AgentDesires().service_level_for("A") == 0.98


# ----------------------------------------------------------------------
# Enrichment (both policies)
# ----------------------------------------------------------------------
def _enrichment_input():
    # Three materials with the same weekly demand; their cost makes the ABC
    # class (Pareto 80 / 95 % on cost × annual demand: 70 / 90 / 100 %)
    mats = pd.DataFrame({"material_id": ["MA", "MB", "MC"],
                         "standard_cost": [70.0, 20.0, 10.0],
                         "lead_time_days": [14, 14, 14]})
    rows = [(m, AS_OF - timedelta(days=7 * k), -float(2 + k % 3))
            for m in ("MA", "MB", "MC") for k in range(52)]
    moves = pd.DataFrame(rows, columns=["material_id", "posting_date", "quantity"])
    moves["movement_type"] = "601"
    moves["posting_date"] = moves["posting_date"].astype(str)
    return mats, moves


@pytest.mark.parametrize("policy", ["legacy", "pattern"])
def test_enrichment_safety_stock_per_class(monkeypatch, policy):
    from src.data_layer import master_data_enrichment as enr
    mats, moves = _enrichment_input()
    base_cfg = replace(config, demand_policy=policy, as_of_date=AS_OF.isoformat())
    monkeypatch.setattr(enr, "config", base_cfg)
    uniform = enr.enrich_master_data(mats, moves).set_index("material_id")
    assert list(uniform["abc_class"]) == ["A", "B", "C"]
    assert all("SL=98%" in s for s in uniform["ss_source"])

    monkeypatch.setattr(enr, "config", replace(base_cfg,
                                               service_level_by_abc="A=0.98,B=0.95,C=0.90"))
    per_class = enr.enrich_master_data(mats, moves).set_index("material_id")
    assert per_class.loc["MA", "safety_stock"] == uniform.loc["MA", "safety_stock"]
    assert "SL=95%" in per_class.loc["MB", "ss_source"]
    assert "SL=90%" in per_class.loc["MC", "ss_source"]
    # Same demand and lead time: SS scales with z (continuous demand)
    for mid, z in (("MB", 1.645), ("MC", 1.282)):
        assert per_class.loc[mid, "safety_stock"] == pytest.approx(
            uniform.loc[mid, "safety_stock"] * z / 2.054, rel=2e-3)


def test_derived_safety_stock_for_an_untabulated_level():
    """A level outside SERVICE_LEVEL_Z uses the exact normal quantile, not the
    98 % z (the silent fallback before this setting existed)."""
    from src.data_layer.master_data_enrichment import MaterialStats, derive_safety_stock
    stats = MaterialStats(material_id="M", std_daily_demand=2.0, avg_daily_demand=1.0)
    ss, src = derive_safety_stock(0.0, stats, 16, 0.92)
    assert ss == pytest.approx(round(dp.z_value(0.92) * 2.0 * 4, 2))
    assert src == "derived (SL=92%)"
    ss98, src98 = derive_safety_stock(0.0, stats, 16, 0.98)
    assert ss98 == round(2.054 * 8, 2) and src98 == "derived (SL=98%)"
