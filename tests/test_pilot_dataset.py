"""
Pilot dataset of a large SAP catalogue taken from a system copy: material
numbers with ';', colliding pseudonyms, receipts into blocked stock, an
as-of date before the stock snapshot, test orders created after it and a
catalogue where most materials never move.
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from src.config import config
from src.data_layer import anonymization as anon
from src.data_layer import etl
from src.data_layer.models import Material, Movement, PurchaseOrder, Stock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Two different codes whose 8-character MD5 prefix is the same (d5cb1cd4)
COLLIDING = ("TESTMAT019430", "TESTMAT124841")


def _write(path: Path, header: str, rows: list[str]) -> None:
    path.write_text("\r\n".join([header, *rows]) + "\r\n", encoding="utf-8")


# ----------------------------------------------------------------------
# Reading the CSV exports
# ----------------------------------------------------------------------
def test_separator_inside_material_number_is_read_as_one_field(tmp_path):
    path = tmp_path / "MARD_export.csv"
    _write(path, "MATNR;WERKS;LGORT;LABST;INSME;EINME;ERSDA", [
        "A1;PL01;SL01;5.000 ;0.000 ;0.000 ;20261106",
        "1234;5;PL01;SL01;2.000 ;0.000 ;0.000 ;20261106",
        "B2;PL01;SL01;1.000 ;0.000 ;0.000 ;20261106",
    ])
    df = anon._read_any(path)
    assert df["MATNR"].tolist() == ["A1", "1234;5", "B2"]
    assert df["WERKS"].tolist() == ["PL01"] * 3
    assert df["LABST"].tolist() == [5.0, 2.0, 1.0]


def test_file_without_bad_lines_is_read_as_before(tmp_path):
    path = tmp_path / "MB51_export.csv"
    _write(path, "MBLNR;MATNR;BWART;MENGE;BUDAT", ["4900000001;A1;601;-2;20260105"])
    assert anon._repair_separator_in_key(path, ";", ["MBLNR", "MATNR", "BWART", "MENGE", "BUDAT"]) == path
    df = anon._read_any(path)
    assert df.loc[0, "MENGE"] == -2 and df.loc[0, "BUDAT"] == 20260105


def test_numeric_material_numbers_keep_leading_zeros(tmp_path):
    path = tmp_path / "EKPO_export.csv"
    _write(path, "EBELN;EBELP;MATNR;WERKS", ["4500000001;00010;0012345;1000"])
    df = anon._read_any(path)
    assert df.loc[0, "MATNR"] == "0012345"
    assert df.loc[0, "WERKS"] == "1000" and df.loc[0, "EBELN"] == "4500000001"


# ----------------------------------------------------------------------
# Pseudonyms
# ----------------------------------------------------------------------
def test_colliding_pseudonyms_are_lengthened_others_unchanged():
    values = [f"M{i}" for i in range(300)]
    overrides = anon.unique_pseudonyms(values, "MAT", 2)       # 256 buckets
    assert overrides                                           # collisions exist
    ids = {v: overrides.get(v, "MAT" + __import__("hashlib").md5(v.encode()).hexdigest()[:2].upper())
           for v in values}
    assert len(set(ids.values())) == len(values)
    assert all(len(p) == len("MAT") + 6 for p in overrides.values())


def test_real_8_character_collision():
    assert anon.pseudonymize(COLLIDING[0], "MAT") == anon.pseudonymize(COLLIDING[1], "MAT")
    overrides = anon.unique_pseudonyms([*COLLIDING, "OTHER"], "MAT", 8)
    assert set(overrides) == set(COLLIDING)
    assert overrides[COLLIDING[0]] != overrides[COLLIDING[1]]


def test_prepare_unique_pseudonyms_applies_to_every_file(tmp_path):
    _write(tmp_path / "MARA_export.csv", "MATNR;MTART;MAKTX", [f"{m};ZMAT;X" for m in COLLIDING])
    _write(tmp_path / "MB51_export.csv", "MBLNR;MATNR;WERKS;BWART;MENGE;BUDAT",
           [f"1;{COLLIDING[1]};PL01;601;-1;20260105"])
    try:
        counts = anon.prepare_unique_pseudonyms(tmp_path)
        assert counts == {"MAT": 2}
        a, b = (anon.pseudonymize(m, "MAT") for m in COLLIDING)
        assert a != b and len(a) == len("MAT") + 12
        assert anon.pseudonymize("OTHER", "MAT") == "MAT" + __import__("hashlib").md5(b"OTHER").hexdigest()[:8].upper()
    finally:
        anon._PSEUDONYM_OVERRIDES.clear()


# ----------------------------------------------------------------------
# Stock types, movement type texts, material scope
# ----------------------------------------------------------------------
def test_stock_is_labst_by_default_and_sums_the_configured_types(monkeypatch):
    df = pd.DataFrame({"LABST": [5.0], "SPEME": [3.0], "INSME": [1.0]})   # as read from the CSV
    assert anon._stock_quantity(df).tolist() == [5.0]
    monkeypatch.setattr(anon, "config", replace(config, stock_columns=("LABST", "SPEME", "RETME")))
    assert anon._stock_quantity(df).tolist() == [8.0]          # RETME not exported → skipped


def test_movement_type_texts_prefer_the_general_text(tmp_path):
    _write(tmp_path / "T156T_export.csv", "SPRAS;BWART;SOBKZ;KZBEW;KZZUG;KZVBR;BTEXT", [
        "E;901;K;;;;GR consignment",
        "E;901;;;;;GR blocked stock",
        "E;601;;L;;;GD goods issue:delvy",
    ])
    texts = anon._movement_type_texts(tmp_path)
    assert texts == {"901": "GR blocked stock", "601": "GD goods issue:delvy"}
    assert anon._movement_type_texts(tmp_path / "missing") == {}


def test_restrict_to_active_materials(tmp_path):
    pd.DataFrame({"material_id": ["A", "B", "C", "D"], "quantity": [0, 4, 0, 0],
                  "snapshot_date": ["2026-11-06"] * 4}).to_csv(tmp_path / "stock.csv", index=False)
    pd.DataFrame({"material_id": ["C", "D"], "status": ["OPEN", "RECEIVED"],
                  "quantity": [10, 5]}).to_csv(tmp_path / "purchase_orders.csv", index=False)
    pd.DataFrame({"material_id": ["A", "A"], "movement_type": ["601", "901"],
                  "quantity": [-1.0, 1.0], "posting_date": ["2026-01-05", "2026-01-06"]}
                 ).to_csv(tmp_path / "movements.csv", index=False)
    active = anon.restrict_to_active_materials(tmp_path)
    assert active == {"A", "B", "C"}                        # D: no movement, stock or open PO
    assert set(pd.read_csv(tmp_path / "stock.csv")["material_id"]) == {"A", "B", "C"}
    assert set(pd.read_csv(tmp_path / "purchase_orders.csv")["material_id"]) == {"C"}
    assert len(pd.read_csv(tmp_path / "movements.csv")) == 2


# ----------------------------------------------------------------------
# Repository: stock and open orders at the as-of date
# ----------------------------------------------------------------------
SNAP = date(2026, 11, 6)
AS_OF = date(2026, 2, 6)


@pytest.fixture
def pilot_repo(in_memory_repo):
    repo = in_memory_repo
    for mid in ("M1", "M2", "M3"):
        repo.session.add(Material(material_id=mid, lead_time_days=10, standard_cost=2.0))
    repo.session.add_all([
        # M1: two storage locations, one later snapshot
        Stock(material_id="M1", plant="P", location="SL01", quantity=7, snapshot_date=SNAP),
        Stock(material_id="M1", plant="P", location="CSL3", quantity=3, snapshot_date=SNAP),
        # M2: an earlier and a later snapshot
        Stock(material_id="M2", plant="P", location="SL01", quantity=4, snapshot_date=date(2026, 1, 1)),
        Stock(material_id="M2", plant="P", location="SL01", quantity=9, snapshot_date=SNAP),
        # M3: roll-back below zero (incomplete history)
        Stock(material_id="M3", plant="P", location="SL01", quantity=1, snapshot_date=SNAP),
    ])
    repo.session.add_all([
        Movement(material_id="M1", plant="P", movement_type="301", quantity=-5, posting_date=date(2026, 10, 1)),
        Movement(material_id="M1", plant="P", movement_type="601", quantity=-2, posting_date=AS_OF),
        Movement(material_id="M3", plant="P", movement_type="901", quantity=6, posting_date=date(2026, 7, 8)),
    ])
    repo.session.add_all([
        PurchaseOrder(po_number="PO1", material_id="M1", quantity=5, status="OPEN",
                      expected_date=date(2026, 2, 20), created_date=date(2026, 1, 20)),
        PurchaseOrder(po_number="PO2", material_id="M1", quantity=8, status="OPEN",
                      expected_date=date(2026, 7, 20), created_date=date(2026, 7, 1)),
        PurchaseOrder(po_number="PO3", material_id="M1", quantity=2, status="OPEN",
                      expected_date=date(2026, 3, 1), created_date=None),
    ])
    repo.commit()
    return repo


def test_current_stock_sums_storage_locations(pilot_repo):
    assert pilot_repo.get_current_stock("M1") == 10.0
    assert pilot_repo.get_current_stock("M2") == 9.0


def test_current_stock_at_an_earlier_date_rolls_back(pilot_repo):
    # 10 at the snapshot, 5 moved out on 1 Oct → 15 at the end of 6 Feb
    # (the 601 on 6 Feb itself is already in the stock of that day)
    assert pilot_repo.get_current_stock("M1", as_of=AS_OF) == 15.0
    assert pilot_repo.get_stock_at("M1", AS_OF) == (15.0, "rollback")
    assert pilot_repo.get_current_stock("M2", as_of=AS_OF) == 4.0        # earlier snapshot
    assert pilot_repo.get_stock_at("M3", AS_OF) == (-5.0, "rollback")    # raw for the backtest
    assert pilot_repo.get_current_stock("M3", as_of=AS_OF) == 0.0       # never negative
    assert pilot_repo.get_current_stock("NOPE", as_of=AS_OF) == 0.0


@pytest.mark.parametrize("as_of", [None, date(2025, 12, 31), AS_OF, date(2026, 10, 1), SNAP,
                                   date(2027, 1, 1)])
def test_bulk_stock_levels_equal_the_per_material_lookup(pilot_repo, as_of):
    levels = pilot_repo.get_stock_levels(as_of)
    for mid in ("M1", "M2", "M3"):
        assert levels.get(mid, 0.0) == pilot_repo.get_current_stock(mid, as_of=as_of), (mid, as_of)


def test_open_orders_created_after_the_as_of_date_are_not_supply(pilot_repo):
    assert {p.po_number for p in pilot_repo.get_open_pos("M1")} == {"PO1", "PO2", "PO3"}
    assert {p.po_number for p in pilot_repo.get_open_pos("M1", as_of=AS_OF)} == {"PO1", "PO3"}
    summary = pilot_repo.get_dataset_summary(as_of=AS_OF)
    assert summary["n_open_pos"] == 2
    assert pilot_repo.get_dataset_summary()["n_open_pos"] == 3


def test_perception_sees_the_stock_and_orders_of_the_as_of_date(pilot_repo):
    from src.agent.perception import PerceptionModule
    beliefs = PerceptionModule(pilot_repo).perceive(as_of=AS_OF)
    assert beliefs.current_stock == {"M1": 15.0, "M2": 4.0, "M3": 0.0}
    assert {p.po_number for p in beliefs.open_orders["M1"]} == {"PO1", "PO3"}


# ----------------------------------------------------------------------
# ETL
# ----------------------------------------------------------------------
def test_etl_blank_description_and_po_date(tmp_path, in_memory_repo):
    pd.DataFrame({"material_id": ["M1", "M2"], "description": ["BATTERY", None]}
                 ).to_csv(tmp_path / "materials.csv", index=False)
    pd.DataFrame({"po_number": ["PO1", "PO2"], "material_id": ["M1", "M2"],
                  "supplier_id": ["S", "S"], "quantity": [1, 2],
                  "expected_date": ["2026-02-20", ""], "status": ["OPEN", "OPEN"],
                  "created_date": ["2026-01-20", ""]}).to_csv(tmp_path / "purchase_orders.csv", index=False)
    etl.load_materials(tmp_path, in_memory_repo)
    etl.load_purchase_orders(tmp_path, in_memory_repo)
    assert in_memory_repo.get_material("M2").description == ""
    created = {p.po_number: p.created_date for p in in_memory_repo.session.query(PurchaseOrder)}
    assert created == {"PO1": date(2026, 1, 20), "PO2": None}


def test_demand_movement_types_setting():
    code = ("from src.data_layer.models import CONSUMPTION_MOVEMENT_TYPES as c; "
            "from src.config import config; print(','.join(c), config.stock_columns, config.material_scope)")
    env = {k: v for k, v in os.environ.items()
           if k not in ("DEMAND_MOVEMENT_TYPES", "STOCK_COLUMNS", "MATERIAL_SCOPE")}
    default = subprocess.run([sys.executable, "-c", code], env=env, cwd=PROJECT_ROOT,
                             capture_output=True, text=True, check=True).stdout.strip()
    assert default == "601,251,261,201,281 ('LABST',) all"
    custom = subprocess.run([sys.executable, "-c", code],
                            env={**env, "DEMAND_MOVEMENT_TYPES": "601, 903",
                                 "STOCK_COLUMNS": "labst,speme", "MATERIAL_SCOPE": "active"},
                            cwd=PROJECT_ROOT, capture_output=True, text=True, check=True).stdout.strip()
    assert custom == "601,903 ('LABST', 'SPEME') active"


# ----------------------------------------------------------------------
# End to end: anonymization → ETL → agent → backtest
# ----------------------------------------------------------------------
def _d(day: date) -> str:
    return day.strftime("%Y%m%d")


def _make_export(raw: Path) -> None:
    raw.mkdir(parents=True)
    sold = ["PN001", "1234;5", *COLLIDING]                 # move every day
    dormant = [f"DORMANT{i}" for i in range(5)]            # never move, no stock
    mats = [*sold, "STOCKONLY", "OPENPO", *dormant]
    _write(raw / "MARA_export.csv", "MATNR;MTART;MEINS;MATKL;BRGEW;NTGEW;ERSDA;LAEDA;MAKTX",
           # the description is sanitized by the ABAP (';' → ','), MATNR is not
           [f"{m};ZMAT;ST;GRPA;0.000 ;0.000 ;20200101;20260101;PART {m.replace(';', ',')}"
            for m in mats])
    _write(raw / "MARC_export.csv",
           "MATNR;WERKS;DISPO;DISMM;DISLS;BESKZ;PLIFZ;EISBE;MINBE;BSTMI;BSTMA;BSTRF;STPRS;PEINH;VPRSV;VERPR",
           [f"{m};PL01;;ND;;F;0 ;0.000 ;0.000 ;0.000 ;0.000 ;0.000 ;0.00 ;1 ;V;10.00" for m in mats])
    # Snapshot long after the as-of date; PN001 has 4 units waiting in
    # blocked stock (received, not yet released)
    _write(raw / "MARD_export.csv", "MATNR;WERKS;LGORT;LABST;INSME;EINME;ERSDA;UMLME;SPEME;RETME",
           [f"{m};PL01;SL01;{'20.000' if m != 'STOCKONLY' else '7.000'} ;0.000 ;0.000 ;{_d(SNAP)};"
            f"0.000 ;{'4.000' if m == 'PN001' else '0.000'} ;0.000 "
            for m in [*sold, "STOCKONLY"]]
           + [f"{m};PL01;SL01;0.000 ;0.000 ;0.000 ;{_d(SNAP)};0.000 ;0.000 ;0.000 " for m in ["OPENPO", *dormant]])
    rows, n = [], 0
    for i in range(120):
        day = AS_OF - timedelta(days=119 - i)
        for m in sold:
            n += 1
            rows.append(f"49{n:08d};{day.year};0001;{m};PL01;SL01;601;-1;ST;{_d(day)};H;")
    # receipts into blocked stock (901) and their release (343 pair)
    for k, day in enumerate([AS_OF - timedelta(days=60), AS_OF - timedelta(days=30)]):
        for m in sold:
            n += 1
            rows.append(f"50{n:08d};{day.year};0001;{m};PL01;SL01;901;30;ST;{_d(day)};S;")
            rows += [f"51{n:08d};{day.year};0001;{m};PL01;SL01;343;30;ST;{_d(day)};H;",
                     f"51{n:08d};{day.year};0002;{m};PL01;SL01;343;30;ST;{_d(day)};S;"]
    # test postings of the development system after the as-of date
    rows.append(f"5999999999;2026;0001;PN001;PL01;SL01;301;5;ST;{_d(date(2026, 10, 1))};H;")
    _write(raw / "MB51_export.csv",
           "MBLNR;MJAHR;ZEILE;MATNR;WERKS;LGORT;BWART;MENGE;MEINS;BUDAT;SHKZG;SOBKZ", rows)
    _write(raw / "EKKO_export.csv", "EBELN;BSART;LIFNR;EKORG;BEDAT;WAERS",
           ["4500000001;NB;0000000001;PO01;20260120;EUR", "4500000002;NB;0000000001;PO01;20260701;EUR"])
    _write(raw / "EKPO_export.csv",
           "EBELN;EBELP;MATNR;WERKS;MENGE;MEINS;NETPR;EINDT;ELIKZ;LOEKZ;BEDAT;WEMNG;EINDT_OPEN",
           ["4500000001;00010;OPENPO;PL01;12;ST;10.00 ;20260220;;;20260120;0;20260220",
            "4500000002;00010;PN001;PL01;50;ST;10.00 ;20260720;;;20260701;0;20260720"])
    _write(raw / "T156T_export.csv", "SPRAS;BWART;SOBKZ;KZBEW;KZZUG;KZVBR;BTEXT",
           ["E;901;;;;;GR blocked stock", "E;601;;L;;;GD goods issue:delvy"])


@pytest.fixture
def pilot_environment(tmp_path):
    _make_export(tmp_path / "raw")
    env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "REPORTS_DIR")}
    env.update({
        "DATABASE_URL":        f"sqlite:///{tmp_path}/test.db",
        "DATA_RAW_DIR":        str(tmp_path / "raw"),
        "DATA_ANONYMIZED_DIR": str(tmp_path / "anonymized"),
        "DATA_SAMPLES_DIR":    str(tmp_path / "samples"),
        "DATA_SOURCE":         "anonymized",
        "LOG_DIR":             str(tmp_path / "logs"),
        # as in data/pilot/dataset.env
        "AS_OF_DATE":            AS_OF.isoformat(),
        "GR_MOVEMENT_TYPES":     "901",
        "DEMAND_MOVEMENT_TYPES": "601",
        "STOCK_COLUMNS":         "LABST,UMLME,INSME,EINME,SPEME,RETME",
        "MATERIAL_SCOPE":        "active",
    })
    return env, tmp_path


def _run(env, *args) -> subprocess.CompletedProcess:
    result = subprocess.run([sys.executable, *args], env=env, cwd=PROJECT_ROOT,
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, f"{args} failed:\n{result.stdout}\n{result.stderr}"
    return result


@pytest.mark.integration
def test_pilot_dataset_end_to_end(pilot_environment):
    env, tmp = pilot_environment
    result = _run(env, "-m", "src.data_layer.anonymization")
    log_text = result.stdout + result.stderr
    assert "line(s) with ';' inside MATNR" in log_text
    assert "Pseudonyms lengthened to stay unique: MAT 2" in log_text
    assert "'GR blocked stock'" in log_text
    assert "Material scope 'active': 6 materials" in log_text

    out = tmp / "anonymized"
    mats = pd.read_csv(out / "materials.csv")
    ids = {m: anon.pseudonymize(m, "MAT", 8) for m in ["PN001", "1234;5", "STOCKONLY", "OPENPO", "DORMANT0"]}
    assert set(mats["material_id"]) >= {ids["PN001"], ids["1234;5"], ids["STOCKONLY"], ids["OPENPO"]}
    assert ids["DORMANT0"] not in set(mats["material_id"]) and len(mats) == 6
    assert mats["material_id"].is_unique
    stock = pd.read_csv(out / "stock.csv").set_index("material_id")
    assert stock.loc[ids["PN001"], "quantity"] == 24.0          # LABST 20 + SPEME 4

    _run(env, "scripts/run_etl.py")
    _run(env, "scripts/run_agent.py")

    from src.data_layer.repository import Repository
    repo = Repository(db_url=env["DATABASE_URL"])
    try:
        # PN001: 24 at the snapshot, 5 moved out on 1 Oct → 29 on 6 Feb
        assert repo.get_current_stock(ids["PN001"], as_of=AS_OF) == 29.0
        assert [p.quantity for p in repo.get_open_pos(ids["PN001"], as_of=AS_OF)] == []
        assert [p.quantity for p in repo.get_open_pos(ids["OPENPO"], as_of=AS_OF)] == [12.0]
        summary = repo.get_dataset_summary(as_of=AS_OF)
        assert summary["n_materials"] == 6 and summary["n_open_pos"] == 1
    finally:
        repo.close()

    report = tmp / "validation.csv"
    _run(env, "scripts/run_validation.py", "--window-days", "60", "--out", str(report))
    as_is_orders = float(pd.read_csv(report).set_index("metric").loc["n_orders", "as_is"])
    assert as_is_orders > 0                                     # 901 = purchase receipts


# ----------------------------------------------------------------------
# Backtest: movements that are neither demand nor purchase receipts
# ----------------------------------------------------------------------
def test_other_movements_hit_as_is_and_to_be_alike(in_memory_repo):
    """A year-end write-off (945) lowers both stocks on the same day; the two
    lines of a 343 release cancel out instead of the issuing line being cut
    at zero stock (which used to create stock out of nothing in As-Is)."""
    from scripts.run_validation import simulate_asis, simulate_tobe
    repo = in_memory_repo
    start, end = date(2025, 12, 29), date(2026, 1, 2)
    repo.session.add(Material(material_id="M1", lead_time_days=30, standard_cost=1.0,
                              safety_stock=0.0, moq=1.0, lot_sizing="LFL", abc_class="C"))
    repo.session.add(Stock(material_id="M1", plant="P", location="SL01", quantity=10,
                           snapshot_date=start - timedelta(days=1)))
    repo.session.add_all([
        # release of goods received into blocked stock: issuing line first
        Movement(material_id="M1", plant="P", movement_type="343", quantity=-30,
                 posting_date=date(2025, 12, 30)),
        Movement(material_id="M1", plant="P", movement_type="343", quantity=30,
                 posting_date=date(2025, 12, 30)),
        # inventory write-off
        Movement(material_id="M1", plant="P", movement_type="945", quantity=-4,
                 posting_date=date(2025, 12, 31)),
    ])
    repo.commit()

    def stock_by_day(state):
        return {r["date"]: r["quantity"] for r in state.stock_history if r["material_id"] == "M1"}

    as_is = stock_by_day(simulate_asis(repo, start, end))
    to_be = stock_by_day(simulate_tobe(repo, start, end))
    assert as_is[date(2025, 12, 30)] == 10.0          # not 30
    assert as_is[date(2025, 12, 31)] == 6.0
    assert to_be == as_is                              # no demand, no orders


# ----------------------------------------------------------------------
# Materials of another business: EXCLUDE_MATERIAL_GROUPS / EXCLUDE_MATERIALS
# ----------------------------------------------------------------------
def _mara(path: Path, rows: list[tuple[str, str]], with_matkl: bool = True) -> None:
    head = "MATNR;MTART;MEINS;MATKL;MAKTX" if with_matkl else "MATNR;MTART;MEINS;MAKTX"
    _write(path / "MARA_export.csv", head,
           [f"{m};ZMAT;ST;{g};PART {m}" if with_matkl else f"{m};ZMAT;ST;PART {m}"
            for m, g in rows])


def test_excluded_material_ids_by_group_and_number(tmp_path):
    _mara(tmp_path, [("X1", "GRPX"), ("X2", "GRPA"), ("X3", "GRPA"), ("X4", "grpx")])
    ids = anon.excluded_material_ids(tmp_path, groups=["grpx"], numbers=["X3", "NOTTHERE"])
    assert ids == {anon.pseudonymize(m, "MAT") for m in ("X1", "X3", "X4")}


def test_no_exclusion_by_default(tmp_path):
    _mara(tmp_path, [("X1", "GRPX")])
    assert config.exclude_material_groups == () and config.exclude_materials == ()
    assert anon.excluded_material_ids(tmp_path) == set()


def test_group_exclusion_needs_matkl(tmp_path):
    _mara(tmp_path, [("X1", "")], with_matkl=False)
    with pytest.raises(ValueError, match="MATKL"):
        anon.excluded_material_ids(tmp_path, groups=["GRPX"], numbers=[])
    assert anon.excluded_material_ids(tmp_path, groups=[], numbers=["X1"]) == {anon.pseudonymize("X1", "MAT")}


def test_drop_materials(tmp_path):
    pd.DataFrame({"material_id": ["A", "B"], "quantity": [1, 2]}).to_csv(tmp_path / "stock.csv", index=False)
    pd.DataFrame({"material_id": ["A", "A", "B"], "movement_type": ["601", "903", "601"]}
                 ).to_csv(tmp_path / "movements.csv", index=False)
    removed = anon.drop_materials(tmp_path, {"A"})
    assert removed == {"stock.csv": 1, "movements.csv": 2}
    assert list(pd.read_csv(tmp_path / "stock.csv")["material_id"]) == ["B"]
    assert list(pd.read_csv(tmp_path / "movements.csv")["material_id"]) == ["B"]


@pytest.mark.integration
def test_excluded_materials_leave_every_file(pilot_environment):
    env, tmp = pilot_environment
    env = {**env, "EXCLUDE_MATERIALS": "STOCKONLY,PN001"}
    result = _run(env, "-m", "src.data_layer.anonymization")
    log_text = result.stdout + result.stderr
    assert "Excluded 2 materials" in log_text
    assert "Material scope 'active': 4 materials" in log_text
    out = tmp / "anonymized"
    gone = {anon.pseudonymize(m, "MAT", 8) for m in ("STOCKONLY", "PN001")}
    for name in ("materials.csv", "stock.csv", "movements.csv", "purchase_orders.csv"):
        assert not gone & set(pd.read_csv(out / name)["material_id"]), name
