"""Window selection and summary of scripts/run_pilot_windows.py."""
from datetime import date

import pandas as pd

from scripts.run_pilot_windows import excluded_by, parse_dates, summarize, windows_back


def test_windows_back_are_consecutive_and_need_full_history():
    w = windows_back(date(2026, 2, 6), 60, earliest_start=date(2024, 11, 7))
    assert w[0] == (date(2025, 12, 9), date(2026, 2, 6))        # the main backtest window
    for (s1, e1), (s0, e0) in zip(w, w[1:]):
        assert (e1 - s1).days == 59
        assert (s1 - e0).days == 1                                 # no gap, no overlap
    assert all(s >= date(2024, 11, 7) for s, _ in w)
    assert len(w) == 7


def test_windows_back_none_when_history_is_too_short():
    assert windows_back(date(2026, 2, 6), 60, earliest_start=date(2026, 1, 1)) == []


def test_exclusion_dates():
    dates = parse_dates(" 2024-12-30, 2025-12-31 ,")
    assert dates == [date(2024, 12, 30), date(2025, 12, 31)]
    assert parse_dates("") == [] and parse_dates(None) == []
    assert excluded_by(date(2024, 12, 14), date(2025, 2, 11), dates) == [date(2024, 12, 30)]
    assert excluded_by(date(2025, 2, 12), date(2025, 4, 12), dates) == []


def test_summary_counts_only_included_windows():
    df = pd.DataFrame({
        "window_start": [date(2025, 12, 9), date(2025, 10, 10), date(2025, 8, 11), date(2024, 12, 14)],
        "window_end":   [date(2026, 2, 6), date(2025, 12, 8), date(2025, 10, 9), date(2025, 2, 11)],
        "asis_tco_eur": [100.0, 100.0, 100.0, 500.0],
        "tobe_tco_eur": [90.0, 95.0, 104.0, 100.0],
        "asis_cycle_service_pct": [92.0, 93.0, 94.0, 90.0],
        "tobe_cycle_service_pct": [97.0, 97.0, 96.0, 97.0],
        "included": [True, True, True, False],
    })
    df["savings_eur"] = df["asis_tco_eur"] - df["tobe_tco_eur"]
    df["savings_pct"] = df["savings_eur"] / df["asis_tco_eur"] * 100
    s = dict(summarize(df).itertuples(index=False))
    assert s["windows_run"] == 4 and s["windows_included"] == 3
    assert s["windows_tobe_cheaper"] == 2
    assert abs(s["savings_mean_eur"] - 11 / 3) < 1e-9
    assert s["savings_min_eur"] == -4.0 and s["savings_max_eur"] == 10.0
    assert abs(s["service_lift_mean_pp"] - 11 / 3) < 1e-9
    assert s["service_lift_min_pp"] == 2.0
