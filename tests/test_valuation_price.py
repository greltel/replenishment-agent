"""
Material unit cost from the SAP valuation (MBEW) fields of the MARC export
(ZMRP_AGENT_EXPORT v1.2: STPRS, PEINH, VPRSV, VERPR).
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.data_layer.anonymization import (
    anonymize_materials, pseudonymize, unit_cost_from_valuation,
)


def _valuation(rows: list[dict]) -> pd.Series:
    return unit_cost_from_valuation(pd.DataFrame(rows))


def test_standard_price_for_price_control_s():
    cost = _valuation([{"VPRSV": "S", "STPRS": "12.50 ", "VERPR": "9.00 ", "PEINH": "1 "}])
    assert cost.iloc[0] == pytest.approx(12.50)


def test_moving_average_price_for_price_control_v():
    cost = _valuation([{"VPRSV": "V", "STPRS": "12.50 ", "VERPR": "9.00 ", "PEINH": "1 "}])
    assert cost.iloc[0] == pytest.approx(9.00)


def test_price_is_per_price_unit():
    cost = _valuation([{"VPRSV": "V", "STPRS": "0.00 ", "VERPR": "250.00 ", "PEINH": "100 "}])
    assert cost.iloc[0] == pytest.approx(2.50)


def test_falls_back_to_the_other_price_when_zero():
    cost = _valuation([
        {"VPRSV": "S", "STPRS": "0.00 ", "VERPR": "7.00 ", "PEINH": "1 "},
        {"VPRSV": "V", "STPRS": "5.00 ", "VERPR": "0.00 ", "PEINH": "1 "},
    ])
    assert cost.tolist() == pytest.approx([7.00, 5.00])


def test_missing_price_or_price_unit():
    cost = _valuation([
        {"VPRSV": "", "STPRS": "", "VERPR": "", "PEINH": ""},      # no MBEW record
        {"VPRSV": "S", "STPRS": "4.00 ", "VERPR": "", "PEINH": "0 "},
    ])
    assert cost.tolist() == pytest.approx([0.0, 4.00])


def test_old_export_without_valuation_columns():
    cost = _valuation([{"MATNR": "X1", "STPRS": None, "PEINH": None}])
    assert cost.iloc[0] == 0.0


def _write(path, header: str, rows: list[str]) -> None:
    path.write_text("\r\n".join([header, *rows]) + "\r\n", encoding="utf-8")


def test_anonymize_materials_takes_the_mbew_price(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    raw.mkdir(), out.mkdir()
    _write(raw / "MARA_export.csv", "MATNR;MTART;MEINS;MATKL;BRGEW;NTGEW;ERSDA;LAEDA;MAKTX",
           ["PN001;GNEW;ST;GRPA;0.000 ;0.100 ;20240101;20260101;FILTER",
            "PN002;GNEW;ST;GRPA;0.000 ;0.100 ;20240101;20260101;SENSOR",
            "PN003;GNEW;ST;GRPA;0.000 ;0.100 ;20240101;20260101;WASHER"])
    _write(raw / "MARC_export.csv",
           "MATNR;WERKS;DISPO;DISMM;DISLS;BESKZ;PLIFZ;EISBE;MINBE;BSTMI;BSTMA;BSTRF;"
           "STPRS;PEINH;VPRSV;VERPR",
           ["PN001;PL01;;ND;;F;0 ;0.000 ;0.000 ;0.000 ;0.000 ;0.000 ;0.00 ;1 ;V;18.40 ",
            "PN002;PL01;;ND;;F;0 ;0.000 ;0.000 ;0.000 ;0.000 ;0.000 ;120.00 ;10 ;S;0.00 ",
            "PN003;PL01;;ND;;F;0 ;0.000 ;0.000 ;0.000 ;0.000 ;0.000 ;0.00 ;0 ;;0.00 "])

    anonymize_materials(raw, out)

    mats = pd.read_csv(out / "materials.csv").set_index("material_id")
    assert mats.loc[pseudonymize("PN001", "MAT"), "standard_cost"] == pytest.approx(18.40)
    assert mats.loc[pseudonymize("PN002", "MAT"), "standard_cost"] == pytest.approx(12.00)
    assert mats.loc[pseudonymize("PN003", "MAT"), "standard_cost"] == 0.0
