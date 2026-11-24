"""
End-to-end run on a small SAP export in the ZMRP_AGENT_EXPORT v1.3 format:
anonymization → ETL → agent → backtest, in an isolated temp environment.

The export mimics a company whose goods receipts are NOT posted with 101
(here a custom type Z01) and which moves stock between storage locations
(311 pairs) — the cases v1.3 was made for.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
START = date(2026, 1, 1)
DAYS = 200
SNAPSHOT = START + timedelta(days=DAYS)          # MARD extraction date


def _d(day: date) -> str:
    return day.strftime("%Y%m%d")


def _write(path: Path, header: str, rows: list[str]) -> None:
    path.write_text("\r\n".join([header, *rows]) + "\r\n", encoding="utf-8")


def _make_export(raw: Path) -> None:
    raw.mkdir(parents=True)
    mats = ["PN001", "PN002", "PN003"]
    _write(raw / "MARA_export.csv", "MATNR;MTART;MEINS;MATKL;BRGEW;NTGEW;ERSDA;LAEDA;MAKTX",
           [f"{m};GNEW;ST;GRPA;0.000 ;0.100 ;20240101;20260101;PART {m}" for m in mats])
    _write(raw / "MARC_export.csv",
           "MATNR;WERKS;DISPO;DISMM;DISLS;BESKZ;PLIFZ;EISBE;MINBE;BSTMI;BSTMA;BSTRF;"
           "STPRS;PEINH;VPRSV;VERPR",
           ["PN001;PL01;;ND;;F;0 ;0.000 ;0.000 ;0.000 ;0.000 ;0.000 ;0.00 ;1 ;V;25.00 ",
            "PN002;PL01;;ND;;F;0 ;0.000 ;0.000 ;0.000 ;0.000 ;0.000 ;80.00 ;1 ;S;0.00 ",
            "PN003;PL01;;ND;;F;0 ;0.000 ;0.000 ;0.000 ;0.000 ;0.000 ;0.00 ;0 ;;0.00 "])
    _write(raw / "MARD_export.csv", "MATNR;WERKS;LGORT;LABST;INSME;EINME;ERSDA",
           [f"PN001;PL01;SL01;12.000 ;0.000 ;0.000 ;{_d(SNAPSHOT)}",
            f"PN002;PL01;SL01;3.000 ;0.000 ;0.000 ;{_d(SNAPSHOT)}",
            f"PN003;PL01;SL01;0.000 ;0.000 ;0.000 ;{_d(SNAPSHOT)}"])

    # Movements: daily sales (601) of PN001/PN002, weekly receipts with a
    # custom movement type, a 311 transfer pair, one inventory write-off
    rows, doc = [], 4900000000
    for i in range(DAYS):
        day = START + timedelta(days=i)
        for m, qty in (("PN001", 2 + i % 3), ("PN002", 1 if i % 2 else 0)):
            if qty:
                doc += 1
                rows.append(f"{doc};2026;0001;{m};PL01;SL01;601;-{qty};ST;{_d(day)};H;")
        if i % 7 == 0:
            for m, qty in (("PN001", 18), ("PN002", 4)):
                doc += 1
                rows.append(f"{doc};2026;0001;{m};PL01;SL01;Z01;{qty};ST;{_d(day)};S;")
    doc += 1
    rows.append(f"{doc};2026;0001;PN001;PL01;SL01;311;-5;ST;{_d(START + timedelta(days=40))};H;")
    rows.append(f"{doc};2026;0002;PN001;PL01;SL02;311;5;ST;{_d(START + timedelta(days=40))};S;")
    doc += 1
    rows.append(f"{doc};2026;0001;PN001;PL01;SL01;702;-1;ST;{_d(START + timedelta(days=60))};H;")
    _write(raw / "MB51_export.csv",
           "MBLNR;MJAHR;ZEILE;MATNR;WERKS;LGORT;BWART;MENGE;MEINS;BUDAT;SHKZG;SOBKZ", rows)

    # POs: completed history (lead time 30 / 45 days) + one open, partly received
    _write(raw / "EKKO_export.csv", "EBELN;BSART;LIFNR;EKORG;BEDAT;WAERS",
           [f"450000000{k};NB;0000012345;1000;{_d(START + timedelta(days=20 * k))};EUR"
            for k in range(1, 6)])
    ekpo = []
    for k in range(1, 5):
        bedat = START + timedelta(days=20 * k)
        ekpo.append(f"450000000{k};00010;PN001;PL01;100;ST;20.00 ;"
                    f"{_d(bedat + timedelta(days=30))};X;;{_d(bedat)};100;00000000")
        ekpo.append(f"450000000{k};00020;PN002;PL01;20;ST;70.00 ;"
                    f"{_d(bedat + timedelta(days=45))};;;{_d(bedat)};20;00000000")
    bedat = START + timedelta(days=100)
    due = _d(SNAPSHOT + timedelta(days=10))
    ekpo.append(f"4500000005;00010;PN001;PL01;100;ST;20.00 ;{due};;;{_d(bedat)};40;{due}")
    _write(raw / "EKPO_export.csv",
           "EBELN;EBELP;MATNR;WERKS;MENGE;MEINS;NETPR;EINDT;ELIKZ;LOEKZ;BEDAT;WEMNG;EINDT_OPEN",
           ekpo)


@pytest.fixture(scope="module")
def v13_environment(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("v13")
    _make_export(tmp / "raw")
    env = os.environ.copy()
    env.update({
        "DATABASE_URL":        f"sqlite:///{tmp}/test.db",
        "DATA_RAW_DIR":        str(tmp / "raw"),
        "DATA_ANONYMIZED_DIR": str(tmp / "anonymized"),
        "DATA_SAMPLES_DIR":    str(tmp / "samples"),
        "DATA_SOURCE":         "anonymized",
        "LOG_DIR":             str(tmp / "logs"),
    })
    return env, tmp


def _run(env, *args) -> subprocess.CompletedProcess:
    result = subprocess.run([sys.executable, *args], env=env, cwd=PROJECT_ROOT,
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, f"{args} failed:\n{result.stdout}\n{result.stderr}"
    return result


@pytest.mark.integration
def test_v13_export_end_to_end(v13_environment):
    env, tmp = v13_environment

    _run(env, "-m", "src.data_layer.anonymization")
    anon = tmp / "anonymized"

    mv = pd.read_csv(anon / "movements.csv", dtype={"movement_type": str})
    assert {"Z01", "311", "702", "601"} <= set(mv["movement_type"])
    assert mv.loc[mv["movement_type"] == "311", "quantity"].sum() == 0
    assert (mv.loc[mv["movement_type"] == "Z01", "quantity"] > 0).all()

    po = pd.read_csv(anon / "purchase_orders.csv")
    assert (po["status"] == "OPEN").sum() == 1
    assert po.loc[po["status"] == "OPEN", "quantity"].tolist() == [60]

    mats = pd.read_csv(anon / "materials.csv").set_index("material_id")
    from src.data_layer.anonymization import pseudonymize
    m1, m2, m3 = (pseudonymize(m, "MAT") for m in ("PN001", "PN002", "PN003"))
    assert mats.loc[m1, "lead_time_days"] == 30 and mats.loc[m1, "lt_source"] == "PO history"
    assert mats.loc[m2, "lead_time_days"] == 45
    assert mats.loc[m3, "lt_source"] == "default"
    assert mats.loc[m1, "standard_cost"] == 25.0       # VERPR (price control V)
    assert mats.loc[m2, "standard_cost"] == 80.0       # STPRS (price control S)
    # demand = 601 only: PN001 sells 2–4 a day → about 3/day, not inflated
    # by the 311 / 702 issues
    assert 2.5 < mats.loc[m1, "avg_daily_demand"] < 3.5

    result = _run(env, "scripts/run_etl.py")
    assert "Using anonymized data" in result.stderr + result.stdout
    _run(env, "scripts/run_agent.py")

    # Backtest: with the default receipt type (101) the Z01 receipts are
    # only stock adjustments; GR_MOVEMENT_TYPES=Z01 makes them the As-Is
    # purchase receipts (orders, ordering cost, inherited pipeline)
    def as_is_orders(extra_env: dict, name: str) -> float:
        out = tmp / name
        _run({**env, **extra_env}, "scripts/run_validation.py",
             "--window-days", "60", "--out", str(out))
        report = pd.read_csv(out).set_index("metric")
        return float(report.loc["n_orders", "as_is"])

    assert as_is_orders({}, "validation_default.csv") == 0
    assert as_is_orders({"GR_MOVEMENT_TYPES": "101,Z01"}, "validation_z01.csv") > 0

    from sqlalchemy import create_engine, text
    engine = create_engine(f"sqlite:///{tmp}/test.db")
    with engine.connect() as conn:
        n_po = conn.execute(text("SELECT COUNT(*) FROM purchase_orders")).scalar()
        n_open = conn.execute(text(
            "SELECT COUNT(*) FROM purchase_orders WHERE status = 'OPEN'")).scalar()
    assert (n_po, n_open) == (9, 1)
