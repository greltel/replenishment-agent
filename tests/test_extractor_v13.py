"""
ZMRP_AGENT_EXPORT v1.3 exports and the matching Python side:
  • movement sign (SHKZG / signed export / movement type for unsigned)
  • PO status and open quantity (ELIKZ, LOEKZ, MENGE − WEMNG), PO date
  • demand = consumption movement types only; lead time from PO history
Older export formats must give the same result as before.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.data_layer.anonymization import (
    _movement_quantity, anonymize_movements, anonymize_purchase_orders,
    pseudonymize,
)
from src.data_layer.etl import load_purchase_orders
from src.data_layer.master_data_enrichment import (
    compute_material_stats, derive_lead_time, derive_moq,
)


def _write(path, header: str, rows: list[str]) -> None:
    path.write_text("\r\n".join([header, *rows]) + "\r\n", encoding="utf-8")


def _qty(df: pd.DataFrame) -> tuple[list[float], str]:
    raw = pd.to_numeric(df["MENGE"]).astype(float)
    quantity, source = _movement_quantity(df, raw, df["BWART"].astype(str))
    return quantity.tolist(), source


# ─────────────────────────── movement sign ───────────────────────────
def test_sign_from_shkzg():
    df = pd.DataFrame({"BWART": ["311", "311", "601", "Z01"],
                       "MENGE": ["-5", "5", "-2", "10"],
                       "SHKZG": ["H", "S", "H", "S"]})
    qty, source = _qty(df)
    assert source == "SHKZG"
    assert qty == [-5, 5, -2, 10]
    assert sum(qty[:2]) == 0            # a transfer between storage locations nets to 0


def test_signed_export_is_trusted():
    # v1.1/v1.2: MENGE already signed by SHKZG, no SHKZG column
    df = pd.DataFrame({"BWART": ["301", "301", "311", "311", "641", "601", "602"],
                       "MENGE": ["-4", "3", "-5", "5", "7", "-2", "2"]})
    qty, source = _qty(df)
    assert source == "signed export"
    # 301 issuing line stays an outflow, the 311 pair nets to 0, a 641
    # receiving line stays positive (the movement-type rule flipped all three)
    assert qty == [-4, 3, -5, 5, 7, -2, 2]


def test_unsigned_export_uses_movement_type():
    # e.g. SE16N on MSEG: every quantity positive
    df = pd.DataFrame({"BWART": ["101", "601", "702", "Z01"],
                       "MENGE": ["10", "2", "1", "3"]})
    qty, source = _qty(df)
    assert source.startswith("movement type")
    assert qty == [10, -2, -1, 3]       # unknown type keeps the exported sign


def test_all_negative_v10_export_uses_movement_type():
    df = pd.DataFrame({"BWART": ["101", "601", "651"],
                       "MENGE": ["-10", "-2", "-1"]})
    qty, _ = _qty(df)
    assert qty == [10, -2, 1]


def test_anonymize_movements_v13_file(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    raw.mkdir(), out.mkdir()
    _write(raw / "MB51_export.csv",
           "MBLNR;MJAHR;ZEILE;MATNR;WERKS;LGORT;BWART;MENGE;MEINS;BUDAT;SHKZG;SOBKZ",
           ["4900000001;2026;0001;PN001;PL01;SL01;Z01;20;ST;20260105;S;",
            "4900000002;2026;0001;PN001;PL01;SL01;311;-5;ST;20260106;H;",
            "4900000002;2026;0002;PN001;PL01;SL02;311;5;ST;20260106;S;",
            "4900000003;2026;0001;PN001;PL01;SL01;601;-3;ST;20260107;H;"])
    anonymize_movements(raw, out)
    mv = pd.read_csv(out / "movements.csv", dtype={"movement_type": str})
    assert mv["movement_type"].tolist() == ["Z01", "311", "311", "601"]
    assert mv["quantity"].tolist() == [20, -5, 5, -3]
    assert set(mv.columns) == {"material_id", "plant", "movement_type",
                               "quantity", "posting_date"}


def test_gr_blocked_stock_left_out_special_stock_kept(tmp_path):
    """103 → 105 is ONE receipt into the warehouse. Special-stock lines
    (SOBKZ) stay: a sale from consignment stock is still demand."""
    raw, out = tmp_path / "raw", tmp_path / "out"
    raw.mkdir(), out.mkdir()
    _write(raw / "MB51_export.csv",
           "MBLNR;MJAHR;ZEILE;MATNR;WERKS;LGORT;BWART;MENGE;MEINS;BUDAT;SHKZG;SOBKZ",
           ["5000000001;2026;0001;PN001;PL01;SL01;103;10;ST;20260105;S;",
            "5000000002;2026;0001;PN001;PL01;SL01;105;10;ST;20260107;S;",
            "5000000003;2026;0001;PN001;PL01;SL01;101;4;ST;20260108;S;K",
            "5000000004;2026;0001;PN001;PL01;SL01;411;-4;ST;20260109;H;K",
            "5000000004;2026;0002;PN001;PL01;SL01;411;4;ST;20260109;S;",
            "5000000005;2026;0001;PN001;PL01;SL01;601;-3;ST;20260110;H;",
            "5000000006;2026;0001;PN001;PL01;SL01;601;-2;ST;20260111;H;K"])
    anonymize_movements(raw, out)
    mv = pd.read_csv(out / "movements.csv", dtype={"movement_type": str})
    assert mv["movement_type"].tolist() == ["105", "101", "411", "411", "601", "601"]
    assert mv.loc[mv["movement_type"] == "105", "quantity"].sum() == 10   # receipt once
    assert mv.loc[mv["movement_type"] == "601", "quantity"].sum() == -5   # both sales


def test_older_export_keeps_every_line(tmp_path):
    """No SOBKZ column and none of the GR-blocked types: nothing left out."""
    raw, out = tmp_path / "raw", tmp_path / "out"
    raw.mkdir(), out.mkdir()
    _write(raw / "MB51_export.csv", "MBLNR;MJAHR;ZEILE;MATNR;WERKS;LGORT;BWART;MENGE;MEINS;BUDAT",
           ["1;2026;0001;PN001;PL01;SL01;101;5;ST;20260105",
            "2;2026;0001;PN001;PL01;SL01;601;-2;ST;20260106"])
    anonymize_movements(raw, out)
    assert len(pd.read_csv(out / "movements.csv")) == 2


# ─────────────────────────── purchase orders ───────────────────────────
EKKO_HEADER = "EBELN;BSART;LIFNR;EKORG;BEDAT;WAERS"
EKPO_V12 = "EBELN;EBELP;MATNR;WERKS;MENGE;MEINS;NETPR;EINDT;ELIKZ;LOEKZ"
EKPO_V13 = EKPO_V12 + ";BEDAT;WEMNG"


def _pos(raw, out) -> pd.DataFrame:
    anonymize_purchase_orders(raw, out)
    return pd.read_csv(out / "purchase_orders.csv")


def test_po_status_and_open_quantity_v13(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    raw.mkdir(), out.mkdir()
    _write(raw / "EKKO_export.csv", EKKO_HEADER,
           ["4500000001;NB;0000012345;1000;20260110;EUR"])
    _write(raw / "EKPO_export.csv", EKPO_V13,
           ["4500000001;00010;PN001;PL01;10;ST;5.00 ;20260210;;;20260110;4",   # partly received
            "4500000001;00020;PN002;PL01;6;ST;5.00 ;20260210;;;20260110;6",    # fully received
            "4500000001;00030;PN003;PL01;8;ST;5.00 ;20260210;X;;20260110;5",   # delivery completed
            "4500000001;00040;PN004;PL01;9;ST;5.00 ;20260210;;L;20260110;0",   # deleted
            "4500000001;00050;PN005;PL01;3;ST;5.00 ;20260301;;;20260110;0"])   # untouched
    po = _pos(raw, out)
    assert po["status"].tolist() == ["OPEN", "RECEIVED", "RECEIVED", "CANCELLED", "OPEN"]
    assert po["quantity"].tolist() == [6, 6, 8, 9, 3]
    assert po["ordered_quantity"].tolist() == [10, 6, 8, 9, 3]
    assert po["created_date"].tolist() == ["2026-01-10"] * 5
    assert po["supplier_id"].nunique() == 1
    assert po["supplier_id"].iloc[0] != pseudonymize("UNK", "SUP")


def test_split_delivery_open_quantity_due_at_open_schedule_line(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    raw.mkdir(), out.mkdir()
    _write(raw / "EKKO_export.csv", EKKO_HEADER,
           ["4500000001;NB;0000012345;1000;20260110;EUR"])
    _write(raw / "EKPO_export.csv", EKPO_V13 + ";EINDT_OPEN",
           # 2 schedule lines: 10 due 10.02 (received), 10 due 10.04 (open)
           ["4500000001;00010;PN001;PL01;20;ST;5.00 ;20260210;;;20260110;10;20260410",
            "4500000001;00020;PN002;PL01;5;ST;5.00 ;20260210;;;20260110;5;00000000"])
    po = _pos(raw, out)
    assert po["status"].tolist() == ["OPEN", "RECEIVED"]
    assert po["quantity"].tolist() == [10, 5]
    assert po["expected_date"].tolist() == ["2026-04-10", "2026-02-10"]
    assert po["planned_delivery_date"].tolist() == ["2026-02-10", "2026-02-10"]


def test_implausible_po_dates_become_blank(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    raw.mkdir(), out.mkdir()
    _write(raw / "EKKO_export.csv", EKKO_HEADER,
           ["4500000001;NB;0000012345;1000;50170705;EUR"])
    _write(raw / "EKPO_export.csv", EKPO_V12,
           ["4500000001;00010;PN001;PL01;10;ST;5.00 ;99991231;;",
            "4500000001;00020;PN002;PL01;4;ST;5.00 ;20260301;;"])
    po = _pos(raw, out)
    assert po["created_date"].isna().all()
    assert pd.isna(po["expected_date"].iloc[0])
    assert po["expected_date"].iloc[1] == "2026-03-01"


def test_po_older_export_without_ekko(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    raw.mkdir(), out.mkdir()
    _write(raw / "EKPO_export.csv", EKPO_V12,
           ["4500000001;00010;PN001;PL01;10;ST;5.00 ;20260210;;"])
    po = _pos(raw, out)
    assert po["status"].tolist() == ["OPEN"] and po["quantity"].tolist() == [10]
    assert po["created_date"].isna().all()
    assert po["supplier_id"].iloc[0] == pseudonymize("UNK", "SUP")


def test_po_older_export_unchanged(tmp_path):
    """v1.2 file: open items only, no WEMNG/BEDAT columns → every line OPEN
    with the full quantity, as before; the PO date comes from EKKO."""
    raw, out = tmp_path / "raw", tmp_path / "out"
    raw.mkdir(), out.mkdir()
    _write(raw / "EKKO_export.csv", EKKO_HEADER,
           ["4500000001;NB;0000012345;1000;20260110;EUR",
            "GR0001;GR;;1000;20260115;EUR"])
    _write(raw / "EKPO_export.csv", EKPO_V12,
           ["4500000001;00010;PN001;PL01;10;ST;5.00 ;20260210;;",
            "GR0001;00010;PN002;PL01;4;ST;5.00 ;20260301;;"])
    po = _pos(raw, out)
    assert po["status"].tolist() == ["OPEN", "OPEN"]
    assert po["quantity"].tolist() == [10, 4]
    assert po["created_date"].tolist() == ["2026-01-10", "2026-01-15"]
    assert list(po.columns[:6]) == ["po_number", "material_id", "supplier_id",
                                    "quantity", "expected_date", "status"]


def test_po_numbers_match_across_number_types(tmp_path):
    """EKKO read with numeric PO numbers, EKPO with mixed ones: the supplier
    and PO date are still found."""
    raw, out = tmp_path / "raw", tmp_path / "out"
    raw.mkdir(), out.mkdir()
    _write(raw / "EKKO_export.csv", EKKO_HEADER,
           ["4500000001;NB;0000012345;1000;20260110;EUR"])
    _write(raw / "EKPO_export.csv", EKPO_V12,
           ["4500000001;00010;PN001;PL01;10;ST;5.00 ;20260210;;",
            "GR0001;00010;PN002;PL01;4;ST;5.00 ;20260301;;"])
    po = _pos(raw, out)
    assert po["supplier_id"].iloc[0] != pseudonymize("UNK", "SUP")
    assert po["created_date"].iloc[0] == "2026-01-10"
    assert pd.isna(po["created_date"].iloc[1])           # no EKKO header


def test_etl_loads_only_open_lines_as_supply(tmp_path, in_memory_repo):
    pd.DataFrame({
        "po_number": ["PO1", "PO1", "PO1"], "material_id": ["M1", "M1", "M1"],
        "supplier_id": ["S1"] * 3, "quantity": [6.0, 6.0, 9.0],
        "expected_date": ["2026-02-10"] * 3,
        "status": ["OPEN", "RECEIVED", "CANCELLED"],
        "ordered_quantity": [10.0, 6.0, 9.0], "created_date": ["2026-01-10"] * 3,
    }).to_csv(tmp_path / "purchase_orders.csv", index=False)
    assert load_purchase_orders(tmp_path, in_memory_repo) == 3
    open_pos = in_memory_repo.get_open_pos("M1")
    assert [(p.quantity, p.status) for p in open_pos] == [(6.0, "OPEN")]


def test_etl_survives_a_po_line_without_delivery_date(tmp_path, in_memory_repo):
    """One blank/out-of-range EINDT used to abort the whole ETL."""
    pd.DataFrame({
        "po_number": ["PO1", "PO2"], "material_id": ["M1", "M1"],
        "supplier_id": ["S1", "S1"], "quantity": [5.0, 3.0],
        "expected_date": ["2026-02-10", ""], "status": ["OPEN", "RECEIVED"],
    }).to_csv(tmp_path / "purchase_orders.csv", index=False)
    assert load_purchase_orders(tmp_path, in_memory_repo) == 2
    assert [p.expected_date for p in in_memory_repo.get_open_pos("M1")] == [date(2026, 2, 10)]


# ─────────────────────────── enrichment ───────────────────────────
def _movements(rows):
    return pd.DataFrame(rows, columns=["material_id", "movement_type",
                                       "quantity", "posting_date"])


def test_demand_counts_consumption_types_only():
    mv = _movements([
        ["M1", 601, -2, "2026-01-05"], ["M1", 601, -4, "2026-01-12"],
        ["M1", 702, -50, "2026-01-06"],          # inventory write-off
        ["M1", 311, -5, "2026-01-07"],           # transfer out
        ["M1", 641, -9, "2026-01-08"],           # stock transport order
        ["M1", "Z01", 30, "2026-01-02"],         # receipt
    ])
    s = compute_material_stats(["M1"], mv)["M1"]
    assert s.n_consumption_events == 2
    assert s.total_consumed == 6


def test_demand_without_movement_type_keeps_previous_rule():
    mv = pd.DataFrame({"material_id": ["M1", "M1", "M1"],
                       "quantity": [-2, -3, 10],
                       "posting_date": ["2026-01-05", "2026-01-06", "2026-01-07"]})
    s = compute_material_stats(["M1"], mv)["M1"]
    assert s.total_consumed == 5


def test_lead_time_and_moq_from_po_history():
    mv = _movements([["M1", 601, -1, "2026-01-05"]])
    po = pd.DataFrame({
        "material_id": ["M1", "M1", "M1", "M1", "M2"],
        "quantity": [5, 0, 20, 7, 3],
        "ordered_quantity": [10, 20, 20, 40, 3],
        "status": ["OPEN", "RECEIVED", "RECEIVED", "CANCELLED", "OPEN"],
        "created_date": ["2026-01-01", "2026-01-01", "2026-01-01", "2026-01-01", "2026-01-01"],
        "expected_date": ["2026-02-15", "2026-02-10", "5017-07-05", "2026-03-01", "2026-01-01"],
    })
    stats = compute_material_stats(["M1", "M2"], mv, po)
    # 45 and 40 days kept (the year-5017 date is dropped); cancelled line ignored
    assert stats["M1"].avg_lead_time_observed == pytest.approx(42.5)
    assert derive_lead_time(0, stats["M1"]) == (42, "PO history")
    assert derive_lead_time(30, stats["M1"]) == (30, "MARC.PLIFZ")
    # same-day delivery → at least 1 day
    assert derive_lead_time(0, stats["M2"]) == (1, "PO history")
    # MOQ: median of the ordered quantities of the non-cancelled lines
    assert derive_moq(0, stats["M1"]) == (20.0, "PO median")


def test_lead_time_uses_first_delivery_date_of_split_deliveries():
    mv = _movements([["M1", 601, -1, "2026-01-05"]])
    po = pd.DataFrame({
        "material_id": ["M1"], "quantity": [10], "ordered_quantity": [20],
        "status": ["OPEN"], "created_date": ["2026-01-10"],
        "expected_date": ["2026-04-10"],           # open schedule line
        "planned_delivery_date": ["2026-02-10"],   # first schedule line
    })
    stats = compute_material_stats(["M1"], mv, po)
    assert stats["M1"].avg_lead_time_observed == 31


def test_po_history_without_dates_keeps_default_lead_time():
    mv = _movements([["M1", 601, -1, "2026-01-05"]])
    po = pd.DataFrame({"material_id": ["M1"], "quantity": [8],
                       "expected_date": ["2026-02-15"]})
    stats = compute_material_stats(["M1"], mv, po)
    assert stats["M1"].avg_lead_time_observed is None
    assert derive_lead_time(0, stats["M1"]) == (14, "default")
    assert derive_moq(0, stats["M1"]) == (8.0, "PO median")
