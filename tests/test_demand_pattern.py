"""
Demand pattern policy (DEMAND_POLICY=pattern, src/mrp/demand_pattern.py):
classification, intermittent-demand forecasts, safety stock, expedite, the
agent, the enrichment, the KPIs and the backtest. Hand-computed values
check the formulas, not only that the code runs.
"""
from __future__ import annotations

import math
from dataclasses import replace
from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.config import config
from src.data_layer.models import Material, Movement, Stock
from src.mrp import demand_pattern as dp
from src.utils import forecasting as fc

AS_OF = date(2026, 2, 6)


def _daily_from_weeks(weekly: list[float]) -> np.ndarray:
    """364-day window with each week's quantity on its last day."""
    assert len(weekly) == 52
    daily = np.zeros(dp.HISTORY_DAYS)
    for w, q in enumerate(weekly):
        daily[w * 7 + 6] = q
    return daily


def _moves(mid: str, weekly: list[float], as_of: date = AS_OF) -> list[Movement]:
    """Movements (negative quantities) matching _daily_from_weeks."""
    out = []
    for w, q in enumerate(weekly):
        if q:
            day = as_of - timedelta(days=(51 - w) * 7)
            out.append(Movement(material_id=mid, plant="P", movement_type="601",
                                quantity=-q, posting_date=day))
    return out


# ----------------------------------------------------------------------
# 2. Classification (Syntetos, Boylan & Croston 2005)
# ----------------------------------------------------------------------
@pytest.mark.parametrize("weekly, pattern", [
    ([0] * 52, dp.NONE),
    ([0] * 51 + [3], dp.RARE),
    ([2] + [0] * 50 + [3], dp.RARE),
    ([10] * 52, dp.SMOOTH),
    ([1, 30] * 26, dp.ERRATIC),
    ([5, 0, 0, 0] * 13, dp.INTERMITTENT),
    ([1, 0, 0, 0, 40, 0, 0, 0] * 6 + [1, 0, 0, 0], dp.LUMPY),
])
def test_classification(weekly, pattern):
    assert dp.profile_from_daily(_daily_from_weeks(weekly)).pattern == pattern


def test_classification_cut_offs():
    # 40 demand weeks → ADI 1.30 < 1.32; 39 → 1.333 ≥ 1.32
    forty = [4] * 40 + [0] * 12
    thirty_nine = [4] * 39 + [0] * 13
    assert dp.profile_from_daily(_daily_from_weeks(forty)).pattern == dp.SMOOTH
    assert dp.profile_from_daily(_daily_from_weeks(thirty_nine)).pattern == dp.INTERMITTENT
    p = dp.profile_from_daily(_daily_from_weeks([5, 0, 0, 0] * 13))
    assert p.adi == 4.0 and p.cv2 == 0.0 and p.week_share == 13 / 52 and p.mean_size == 5.0


def test_profile_from_movements_and_frame_agree():
    weekly = [0, 3, 0, 0, 4, 0, 3] + [0] * 45
    moves = _moves("M1", weekly) + [
        Movement(material_id="M1", plant="P", movement_type="601", quantity=-99,
                 posting_date=AS_OF + timedelta(days=1)),            # after as-of
        Movement(material_id="M1", plant="P", movement_type="601", quantity=-99,
                 posting_date=AS_OF - timedelta(days=dp.HISTORY_DAYS)),  # before window
    ]
    a = dp.profile_from_movements(moves, AS_OF)
    frame = pd.DataFrame({"material_id": [m.material_id for m in moves],
                          "posting_date": [m.posting_date for m in moves],
                          "quantity": [m.quantity for m in moves]})
    b = dp.profiles_from_frame(frame, AS_OF, ["M1", "M2"])
    assert a.weekly == b["M1"].weekly and a.pattern == b["M1"].pattern == dp.INTERMITTENT
    assert sum(a.weekly) == 10 and b["M2"].pattern == dp.NONE


# ----------------------------------------------------------------------
# 3. Intermittent-demand forecasts
# ----------------------------------------------------------------------
def test_croston_and_sba_by_hand():
    # demands in periods 3 (size 3) and 7 (size 6): z = 3 → 3.3, x = 3 → 3.1
    series = pd.Series([0, 0, 3, 0, 0, 0, 6])
    assert fc.croston(series, 2) == pytest.approx([3.3 / 3.1] * 2)
    assert fc.sba(series, 1)[0] == pytest.approx(3.3 / 3.1 * 0.95)
    assert fc.croston(pd.Series([0, 0, 0]), 1) == [0.0]


def test_tsb_by_hand():
    # p0 = 2/5, z0 = 2; p: .36 → .424 → .3816 → .34344 → .409096; z → 2.2
    assert fc.tsb(pd.Series([0, 2, 0, 0, 4]), 1)[0] == pytest.approx(0.409096 * 2.2)
    assert fc.tsb(pd.Series([0, 0]), 3) == [0.0, 0.0, 0.0]


def test_forecast_dispatcher_spreads_the_weekly_rate_over_days():
    weekly = [5, 0, 0, 0] * 13
    moves = _moves("M1", weekly)
    daily = fc.forecast(moves, horizon_days=10, method="sba", as_of=AS_OF)
    expected = fc.sba(pd.Series(weekly, dtype=float), 1)[0] / 7
    assert daily == pytest.approx([expected] * 10)


# ----------------------------------------------------------------------
# 4. Safety stock
# ----------------------------------------------------------------------
def _poisson_quantile(lam: float, alpha: float) -> int:
    cdf, k, term = 0.0, 0, math.exp(-lam)
    while True:
        cdf += term
        if cdf >= alpha:
            return k
        k += 1
        term *= lam / k


@pytest.mark.parametrize("lam", [0.1, 0.5, 2.0, 7.5])
def test_compound_poisson_with_unit_sizes_is_poisson(lam):
    assert dp.compound_poisson_quantile(lam, [1, 1, 1], 0.98) == _poisson_quantile(lam, 0.98)
    assert dp.compound_poisson_quantile(lam, [2], 0.98) == 2 * _poisson_quantile(lam, 0.98)


def test_compound_poisson_against_simulation():
    rng = np.random.default_rng(42)
    sizes, lam = [1, 1, 3, 6], 0.8
    n = rng.poisson(lam, 200_000)
    draws = np.array([rng.choice(sizes, k).sum() if k else 0 for k in n])
    assert abs(dp.compound_poisson_quantile(lam, sizes, 0.98) - np.quantile(draws, 0.98)) <= 1
    assert dp.compound_poisson_quantile(0.0, sizes, 0.98) == 0.0


def test_safety_stock_per_pattern():
    smooth = dp.profile_from_daily(_daily_from_weeks([10] * 52))
    assert dp.safety_stock_for(smooth, 14, 0.98) == pytest.approx(
        round(dp.z_value(0.98) * smooth.daily_std * math.sqrt(14), 2))
    # 13 of 52 weeks, one unit each, LT 14 days → λ = 0.5: P(≤1) = .9098,
    # P(≤2) = .9856 → s* = 2, SS = 2 − 0.5
    inter = dp.profile_from_daily(_daily_from_weeks([1, 0, 0, 0] * 13))
    assert dp.safety_stock_for(inter, 14, 0.98) == 1.5
    rare = dp.profile_from_daily(_daily_from_weeks([0] * 51 + [1]))
    assert dp.safety_stock_for(rare, 14, 0.98) == 0.0
    assert dp.safety_stock_for(inter, 0, 0.98) == 0.0


def test_expedite_allowed():
    assert dp.expedite_allowed(None, 0.0) and dp.expedite_allowed(dp.SMOOTH, 0.0)
    assert not dp.expedite_allowed(dp.RARE, 1.0) and not dp.expedite_allowed(dp.NONE, 1.0)
    assert dp.expedite_allowed(dp.INTERMITTENT, 0.5)
    assert not dp.expedite_allowed(dp.LUMPY, 0.49)
    inter = dp.profile_from_daily(_daily_from_weeks([1, 0, 0, 0] * 13))
    assert inter.demand_probability(14) == pytest.approx(1 - math.exp(-0.5))


# ----------------------------------------------------------------------
# The agent with DEMAND_POLICY=pattern
# ----------------------------------------------------------------------
@pytest.fixture
def pattern_policy(monkeypatch):
    import src.agent.replenishment as agent_mod
    monkeypatch.setattr(agent_mod, "config", replace(config, demand_policy="pattern"))


def _agent_repo(repo):
    specs = {
        "SMOOTH": ([10] * 52, None),
        "INTER":  ([1, 0, 0, 0] * 13, None),
        "RARE":   ([0] * 50 + [2, 0], None),
        "SAPSS":  ([1, 0, 0, 0] * 13, "MARC.EISBE"),
    }
    for mid, (weekly, src) in specs.items():
        repo.session.add(Material(material_id=mid, lead_time_days=14, standard_cost=1.0,
                                  safety_stock=7.0, moq=1.0, lot_sizing="LFL", abc_class="C",
                                  ss_source=src))
        repo.session.add(Stock(material_id=mid, plant="P", location="L", quantity=0,
                               snapshot_date=AS_OF))
        repo.session.add_all(_moves(mid, weekly))
    repo.commit()


def _run_agent(repo):
    from src.agent.replenishment import ReplenishmentAgent
    from src.mrp.engine import MRPEngine
    from src.rules.engine import RulesEngine
    agent = ReplenishmentAgent(repo, MRPEngine(horizon_days=30), RulesEngine())
    agent.perceive(as_of=AS_OF)
    agent.deliberate(as_of=AS_OF)
    by_mid: dict[str, list] = {}
    for i in agent.intentions:
        by_mid.setdefault(i.material_id, []).append(i)
    return agent, by_mid


def test_agent_policy_per_pattern(in_memory_repo, pattern_policy):
    _agent_repo(in_memory_repo)
    agent, by_mid = _run_agent(in_memory_repo)
    b = agent.beliefs
    assert b.demand_pattern == {"SMOOTH": dp.SMOOTH, "INTER": dp.INTERMITTENT,
                                "RARE": dp.RARE, "SAPSS": dp.INTERMITTENT}
    assert b.safety_stock["INTER"] == 1.5 and b.safety_stock["RARE"] == 0.0
    assert b.safety_stock["SAPSS"] == 7.0                    # SAP value kept
    assert "RARE" not in by_mid                              # bought to order
    assert any(i.expedite for i in by_mid["SMOOTH"])          # stock 0 < 50 % SS
    # λ = 13/52 · 14/7 = 0.5 → P(demand in LT) = 39 % < 50 %: no express order
    assert not any(i.expedite for i in by_mid["INTER"])


def test_agent_legacy_policy_unchanged(in_memory_repo):
    _agent_repo(in_memory_repo)
    agent, by_mid = _run_agent(in_memory_repo)
    assert agent.beliefs.demand_pattern == {} and agent.beliefs.safety_stock == {}
    assert "RARE" in by_mid                                  # SS 7 from the master data
    assert any(i.expedite for i in by_mid["INTER"])


# ----------------------------------------------------------------------
# Enrichment with DEMAND_POLICY=pattern
# ----------------------------------------------------------------------
def test_enrichment_window_statistics(monkeypatch):
    from src.data_layer import master_data_enrichment as enr
    mats = pd.DataFrame({"material_id": ["ONCE", "WEEKLY"], "standard_cost": [10.0, 10.0],
                         "lead_time_days": [14, 14]})
    rows = [("ONCE", AS_OF - timedelta(days=100), -1.0)]
    rows += [("WEEKLY", AS_OF - timedelta(days=7 * k), -2.0) for k in range(52)]
    moves = pd.DataFrame(rows, columns=["material_id", "posting_date", "quantity"])
    moves["movement_type"] = "601"
    moves["posting_date"] = moves["posting_date"].astype(str)

    legacy = enr.enrich_master_data(mats, moves).set_index("material_id")
    assert legacy.loc["ONCE", "safety_stock"] == 7.0         # 1 unit "a day" × 14 × 0.5
    assert "demand_pattern" not in legacy.columns

    monkeypatch.setattr(enr, "config", replace(config, demand_policy="pattern",
                                               as_of_date=AS_OF.isoformat()))
    new = enr.enrich_master_data(mats, moves).set_index("material_id")
    assert new.loc["ONCE", "demand_pattern"] == dp.RARE and new.loc["ONCE", "safety_stock"] == 0.0
    assert new.loc["WEEKLY", "demand_pattern"] == dp.SMOOTH
    assert new.loc["ONCE", "avg_daily_demand"] == pytest.approx(1 / 364)
    assert new.loc["WEEKLY", "avg_daily_demand"] == pytest.approx(104 / 364)
    assert new.loc["ONCE", "ss_source"].startswith("pattern RARE")


# ----------------------------------------------------------------------
# KPIs and backtest
# ----------------------------------------------------------------------
def _kpi(on_demand):
    from src.utils.kpi import KPICalculator
    days = pd.date_range("2026-01-01", periods=4)
    stock = pd.DataFrame({"date": list(days) * 2, "material_id": ["S"] * 4 + ["R"] * 4,
                          "quantity": [5, 5, 0, 5] + [0, 0, 0, 0]})
    demand = pd.DataFrame({"date": [days[2], days[1]], "material_id": ["S", "R"],
                           "requested_qty": [2.0, 3.0], "delivered_qty": [0.0, 0.0]})
    orders = pd.DataFrame(columns=["date", "material_id", "quantity", "unit_cost"])
    mats = pd.DataFrame({"material_id": ["S", "R"], "standard_cost": [10.0, 10.0],
                         "abc_class": ["A", "C"], "demand_pattern": [dp.SMOOTH, dp.RARE]})
    return KPICalculator(stock, demand, orders, mats, on_demand_ids=on_demand, period_days=4)


def test_kpis_treat_to_order_materials_as_backorders():
    before, after = _kpi(None), _kpi({"R"})
    assert before.cycle_service_level() == pytest.approx(3 / 8)
    assert after.cycle_service_level() == pytest.approx(3 / 4)
    assert after.stockout_days() == 1 and before.stockout_days() == 5
    assert after.stockout_cost()["lost_sales"] < before.stockout_cost()["lost_sales"]
    assert after.backorders() == {"lines": 1, "quantity": 3.0, "value_eur": 30.0}
    report = after.report()
    assert report.by_demand_pattern[dp.RARE]["cycle_service_level"] is None
    assert report.by_demand_pattern[dp.RARE]["backorder_lines"] == 1
    assert "backorders" not in report.to_dict() and "by_demand_pattern" not in report.to_dict()


def test_backtest_buys_to_order_for_the_waiting_customer(in_memory_repo, pattern_policy):
    """A rare part asked for in the window with no stock: To-Be buys it for
    the customer, it arrives after the lead time and goes to him, not to
    stock; the shortage is a backorder, not a lost sale."""
    from scripts.run_validation import kpis_from_state, simulate_asis, simulate_tobe
    from src.utils.cost_estimator import get_scenario
    repo = in_memory_repo
    start, end = date(2026, 1, 5), date(2026, 1, 25)
    repo.session.add(Material(material_id="R", lead_time_days=7, standard_cost=10.0,
                              safety_stock=0.0, moq=1.0, lot_sizing="LFL", abc_class="C"))
    repo.session.add(Stock(material_id="R", plant="P", location="L", quantity=0,
                           snapshot_date=start - timedelta(days=1)))
    repo.session.add_all([
        Movement(material_id="R", plant="P", movement_type="601", quantity=-1,
                 posting_date=date(2025, 6, 1)),                 # one sale last year
        Movement(material_id="R", plant="P", movement_type="601", quantity=-2,
                 posting_date=date(2026, 1, 10)),                # asked for in the window
    ])
    repo.commit()
    tobe = simulate_tobe(repo, start, end, by_pattern=True)
    asis = simulate_asis(repo, start, end, by_pattern=True)
    assert tobe.demand_pattern == {"R": dp.RARE} == asis.demand_pattern
    assert tobe.on_demand_ids == {"R"}
    assert [(o["date"], o["quantity"]) for o in tobe.orders_placed] == [(date(2026, 1, 17), 2.0)]
    assert max(r["quantity"] for r in tobe.stock_history) == 0.0
    mats = pd.read_sql("SELECT * FROM materials", repo.session.connection())
    kpi = kpis_from_state(tobe, mats, get_scenario("realistic"), start, end)
    assert kpi.backorders["lines"] == 1 and kpi.lost_sales_eur == 0.0
    # without the evaluation per pattern nothing changes
    plain = simulate_tobe(repo, start, end, by_pattern=False)
    assert plain.orders_placed == [] and plain.on_demand_ids == set()



def test_backorders_zero_when_to_order_demand_was_covered():
    # Material IDs as read from the database (pandas string dtype) and a
    # to-order material whose demand the stock covered: no backorders, and
    # no failure on the empty selection.
    from src.utils.kpi import KPICalculator
    days = pd.date_range("2026-01-01", periods=2)
    stock = pd.DataFrame({"date": days, "material_id": ["R", "R"], "quantity": [5.0, 3.0]})
    demand = pd.DataFrame({"date": [days[1]], "material_id": ["R"],
                           "requested_qty": [2.0], "delivered_qty": [2.0]})
    orders = pd.DataFrame(columns=["date", "material_id", "quantity", "unit_cost"])
    mats = pd.DataFrame({"material_id": ["R"], "standard_cost": [10.0],
                         "abc_class": ["C"], "demand_pattern": [dp.RARE]})
    for df in (stock, demand, mats):
        df["material_id"] = df["material_id"].astype("str")
    k = KPICalculator(stock, demand, orders, mats, on_demand_ids={"R"}, period_days=2)
    assert k.backorders() == {"lines": 0, "quantity": 0.0, "value_eur": 0.0}
