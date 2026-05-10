"""
Anonymization pipeline.

Reads raw SAP exports from data/raw/ and produces anonymized CSVs in
data/anonymized/, ready to be ingested by the ETL.

Maps SAP table column names to our internal schema:
  MARA + MARC + MARD → materials.csv
  MARD             → stock.csv (alternative if separate)
  EKKO + EKPO       → purchase_orders.csv
  MB51              → movements.csv

USAGE:
  Place SAP exports (Excel or CSV) in data/raw/ named:
    MARA_export.xlsx, MARC_export.xlsx, MARD_export.xlsx,
    EKKO_export.xlsx, EKPO_export.xlsx, MB51_export.xlsx
  Then:
    python -m src.data_layer.anonymization
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from src.config import config
from src.data_layer.sap_parsers import (
    parse_sap_date, parse_sap_number_series
)
from src.data_layer.master_data_enrichment import enrich_master_data
from src.utils.logger import log


# ============================================================
# Pseudonymization
# ============================================================
def pseudonymize(value, prefix: str, length: int = 8) -> str:
    """Deterministic pseudonym — same input always produces same output.
    Non-reversible (one-way hash)."""
    if pd.isna(value):
        return f"{prefix}NA"
    h = hashlib.md5(str(value).encode()).hexdigest()[:length].upper()
    return f"{prefix}{h}"


def _read_any(path: Path) -> pd.DataFrame:
    """Read either xlsx or csv. Auto-detects delimiter for CSVs (handles
    both ',' and ';' — SAP exports typically use ';' as field separator)."""
    if path.suffix in (".xlsx", ".xls"):
        return pd.read_excel(path)
    # Auto-detect delimiter by reading a sample
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        sample = f.readline()
    sep = ";" if sample.count(";") > sample.count(",") else ","
    return pd.read_csv(path, sep=sep, encoding="utf-8")


def _find_export(raw_dir: Path, base_name: str) -> Path | None:
    """Find an SAP export file by base name. Tries .xlsx, .xls, .csv in
    that order. Returns None if nothing found.

    Example: _find_export(raw_dir, 'MARA_export') will look for:
        MARA_export.xlsx, MARA_export.xls, MARA_export.csv
    """
    for ext in (".xlsx", ".xls", ".csv"):
        candidate = raw_dir / f"{base_name}{ext}"
        if candidate.exists():
            return candidate
    return None


# Re-export with old name for backward compatibility
_parse_sap_date = parse_sap_date


# ============================================================
# Per-table anonymization
# ============================================================
def anonymize_materials(
    raw_dir: Path,
    out_dir: Path,
    enrich_with: Path | None = None,
    include_descriptions: bool = True,
) -> None:
    """Combine MARA + MARC + MARD-derived data into materials.csv.

    Args:
        raw_dir: Source folder with SAP exports.
        out_dir: Destination folder for anonymized CSVs.
        enrich_with: If provided, look in this folder for already-anonymized
            movements.csv and purchase_orders.csv to compute smart defaults
            for missing MRP fields (lead_time, safety_stock, MOQ, lot_sizing,
            ABC class).
        include_descriptions: If True, copy MAKT descriptions verbatim. If
            False, drop them entirely. Set to False if descriptions contain
            sensitive product codes/trademarks that could deanonymize the
            company. Default: True (descriptions are usually safe).
    """
    mara_path = _find_export(raw_dir, "MARA_export")
    marc_path = _find_export(raw_dir, "MARC_export")

    if mara_path is None:
        log.warning("MARA_export.* not found in raw dir")
        return

    mara = _read_any(mara_path)
    marc = _read_any(marc_path) if marc_path is not None else pd.DataFrame()

    # Pseudonymize material codes
    mara["material_id"] = mara["MATNR"].apply(lambda x: pseudonymize(x, "MAT"))

    # Build base record
    df = pd.DataFrame({
        "material_id":   mara["material_id"],
        "material_type": mara.get("MTART", "ROH"),
        "uom":           mara.get("MEINS", "PCS"),
        "standard_cost": parse_sap_number_series(mara["STPRS"]) if "STPRS" in mara.columns else 0,
    })

    # Material description (from MAKT.MAKTX joined in ABAP)
    if include_descriptions and "MAKTX" in mara.columns:
        df["description"] = mara["MAKTX"].fillna("").astype(str).str.strip()
    else:
        df["description"] = ""

    # Join MARC fields if available
    if not marc.empty and "MATNR" in marc.columns:
        marc["material_id"] = marc["MATNR"].apply(lambda x: pseudonymize(x, "MAT"))
        # Keep first record per material (assuming single plant)
        marc_first = marc.drop_duplicates(subset=["material_id"], keep="first")

        df = df.merge(marc_first[[
            "material_id", "DISMM", "DISLS", "PLIFZ", "EISBE", "MINBE", "BSTMI"
        ]].rename(columns={
            "DISMM": "mrp_type",
            "DISLS": "lot_sizing_raw",
            "PLIFZ": "lead_time_days",
            "EISBE": "safety_stock",
            "MINBE": "reorder_point",
            "BSTMI": "moq",
        }), on="material_id", how="left")

        # Parse numeric fields robustly (handles SAP trailing-minus, '1.234,56' etc.)
        for col in ("lead_time_days", "safety_stock", "reorder_point", "moq"):
            if col in df.columns:
                df[col] = parse_sap_number_series(df[col])

        # Map SAP lot-sizing codes to our internal codes
        lot_map = {"EX": "LFL", "FX": "FOQ", "WB": "EOQ", "PK": "POQ"}
        df["lot_sizing"] = df["lot_sizing_raw"].map(lot_map).fillna("LFL")
        df = df.drop(columns=["lot_sizing_raw"])

    # ABC classification (if not present, derive from cost × frequency proxy)
    if "abc_class" not in df.columns:
        if "standard_cost" in df.columns and df["standard_cost"].sum() > 0:
            df = df.sort_values("standard_cost", ascending=False)
            df["cum_pct"] = df["standard_cost"].cumsum() / df["standard_cost"].sum()
            df["abc_class"] = df["cum_pct"].apply(
                lambda x: "A" if x <= 0.80 else ("B" if x <= 0.95 else "C")
            )
            df = df.drop(columns=["cum_pct"])
        else:
            df["abc_class"] = "B"

    # Fill remaining defaults
    for col, val in [
        ("lead_time_days", 7), ("safety_stock", 0.0), ("reorder_point", 0.0),
        ("moq", 1.0), ("fixed_lot_size", 0.0),
    ]:
        if col not in df.columns:
            df[col] = val
        else:
            df[col] = df[col].fillna(val)

    # ─────────────────────────────────────────────────────────────────
    # Smart defaults: derive missing MRP parameters from history
    # ─────────────────────────────────────────────────────────────────
    if enrich_with is not None:
        movements_path = enrich_with / "movements.csv"
        po_path = enrich_with / "purchase_orders.csv"

        movements_df = pd.read_csv(movements_path) if movements_path.exists() else pd.DataFrame()
        po_df = pd.read_csv(po_path) if po_path.exists() else pd.DataFrame()

        if not movements_df.empty:
            df = enrich_master_data(df, movements_df, po_df)
        else:
            log.warning(
                "Cannot enrich materials: movements.csv not found. "
                "Materials will use raw MARC defaults (likely zeros)."
            )

    df.to_csv(out_dir / "materials.csv", index=False)
    log.success(f"Wrote materials.csv ({len(df)} rows)")


def anonymize_stock(raw_dir: Path, out_dir: Path) -> None:
    """Anonymize MARD → stock.csv."""
    path = _find_export(raw_dir, "MARD_export")
    if path is None:
        log.warning("MARD_export.* not found in raw dir")
        return

    df = _read_any(path)
    out = pd.DataFrame({
        "material_id":   df["MATNR"].apply(lambda x: pseudonymize(x, "MAT")),
        "plant":         df.get("WERKS", "P001").apply(lambda x: pseudonymize(x, "PLT", 4))
                          if "WERKS" in df.columns else "P001",
        "location":      df.get("LGORT", "L01"),
        "quantity":      parse_sap_number_series(df["LABST"]) if "LABST" in df.columns else 0,
        "snapshot_date": pd.Timestamp.today().normalize().date()
                          if "ERSDA" not in df.columns
                          else _parse_sap_date(df["ERSDA"]).dt.date,
    })

    out.to_csv(out_dir / "stock.csv", index=False)
    log.success(f"Wrote stock.csv ({len(out)} rows)")


def anonymize_purchase_orders(raw_dir: Path, out_dir: Path) -> None:
    """Combine EKKO + EKPO → purchase_orders.csv."""
    ekko_path = _find_export(raw_dir, "EKKO_export")
    ekpo_path = _find_export(raw_dir, "EKPO_export")

    if ekpo_path is None:
        log.warning("EKPO_export.* not found in raw dir")
        return

    ekpo = _read_any(ekpo_path)

    # If EKKO available, get LIFNR (supplier) from there
    supplier_map = {}
    if ekko_path is not None:
        ekko = _read_any(ekko_path)
        if "EBELN" in ekko.columns and "LIFNR" in ekko.columns:
            supplier_map = dict(zip(ekko["EBELN"], ekko["LIFNR"]))

    out = pd.DataFrame({
        "po_number":     ekpo["EBELN"].apply(lambda x: pseudonymize(x, "PO", 6)),
        "material_id":   ekpo["MATNR"].apply(lambda x: pseudonymize(x, "MAT")),
        "supplier_id":   ekpo["EBELN"].map(supplier_map).fillna("UNK")
                          .apply(lambda x: pseudonymize(x, "SUP")),
        "quantity":      parse_sap_number_series(ekpo["MENGE"]) if "MENGE" in ekpo.columns else 0,
        "expected_date": _parse_sap_date(ekpo.get("EINDT")).dt.date,
        "status":        "OPEN",
    })

    out.to_csv(out_dir / "purchase_orders.csv", index=False)
    log.success(f"Wrote purchase_orders.csv ({len(out)} rows)")


def anonymize_movements(raw_dir: Path, out_dir: Path) -> None:
    """Anonymize MB51 → movements.csv.

    Sign convention enforced HERE based on SAP BWART semantics:
        Receipts (positive stock change):
            101, 102 cancel, 301, 309, 311, 321, 651
        Issues (negative stock change):
            201, 202 cancel, 261, 262 cancel, 281, 282 cancel, 302, 310,
            312, 322, 601, 602 cancel, 641, 642 cancel, 701, 702

    This sign correction protects against ABAP exports that may not have
    applied SHKZG-based sign logic correctly.
    """
    path = _find_export(raw_dir, "MB51_export")
    if path is None:
        log.warning("MB51_export.* not found in raw dir")
        return

    df = _read_any(path)

    # Movement types that result in stock INCREASE (receipts)
    RECEIPT_TYPES = {
        "101",  # Goods receipt for PO
        "102",  # Reversal of goods receipt   (cancels a receipt → issue)
        "301",  # Plant-to-plant transfer (receiving plant)
        "309",  # Material-to-material transfer (target)
        "311",  # Storage location transfer (target)
        "321",  # Quality stock to unrestricted
        "601",  # Goods issue for delivery (NOTE: SAP records this as negative; we flip below)
        "651",  # Returns from customer (receipt for returning company)
        "701",  # Inventory diff (positive count)
    }
    # Movement types that result in stock DECREASE (issues/consumption)
    ISSUE_TYPES = {
        "201", "202",  # GI for cost center (and reversal)
        "261", "262",  # GI for production order (and reversal)
        "281", "282",  # GI for network (and reversal)
        "302",         # Plant-to-plant transfer (issuing plant)
        "310",         # Material-to-material transfer (source)
        "312",         # Storage location transfer (source)
        "322",         # Unrestricted to quality stock
        "602",         # Cancellation of GI for delivery
        "641", "642",  # Stock transfer order
        "652",         # Cancellation of customer return
        "702",         # Inventory diff (negative count)
    }

    # Parse the raw quantity (handles trailing minus, whitespace, etc.)
    raw_qty = parse_sap_number_series(df["MENGE"]) if "MENGE" in df.columns else 0

    # Apply sign correction: take ABS, then assign sign based on movement type
    # This is robust against either correctly-signed input OR all-negative ABAP bug
    bwart = df.get("BWART", "261").astype(str).str.strip()

    def _signed_qty(bwart_val: str, qty: float) -> float:
        abs_qty = abs(qty)
        if bwart_val in RECEIPT_TYPES:
            # Special case: 102 reverses a receipt → becomes negative
            if bwart_val == "102":
                return -abs_qty
            return abs_qty
        if bwart_val in ISSUE_TYPES:
            # Special cases: '202', '262', '282' are reversals of issues → become positive
            if bwart_val in ("202", "262", "282", "602", "652"):
                return abs_qty
            return -abs_qty
        # Unknown movement type — preserve original sign
        return qty

    quantity = pd.Series([
        _signed_qty(b, q) for b, q in zip(bwart, raw_qty)
    ])

    out = pd.DataFrame({
        "material_id":   df["MATNR"].apply(lambda x: pseudonymize(x, "MAT")),
        "plant":         df.get("WERKS", "P001").apply(lambda x: pseudonymize(x, "PLT", 4))
                          if "WERKS" in df.columns else "P001",
        "movement_type": bwart,
        "quantity":      quantity,
        "posting_date":  _parse_sap_date(df.get("BUDAT")).dt.date,
    })

    out.to_csv(out_dir / "movements.csv", index=False)
    log.success(f"Wrote movements.csv ({len(out)} rows)")


def run_anonymization() -> None:
    """Run the full anonymization pipeline.

    Order matters: we anonymize movements & POs first, then use them to
    enrich materials with smart defaults for missing MRP fields.
    """
    log.info("=== Anonymization Pipeline ===")
    raw_dir = config.data_raw_dir
    out_dir = config.data_anonymized_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Stock, POs and movements first (they don't depend on each other)
    anonymize_stock(raw_dir, out_dir)
    anonymize_purchase_orders(raw_dir, out_dir)
    anonymize_movements(raw_dir, out_dir)

    # Step 2: Materials, enriched with stats from movements & POs
    anonymize_materials(raw_dir, out_dir, enrich_with=out_dir)

    log.success("Anonymization complete!")
    log.info(f"Output: {out_dir}")
    log.warning(
        "REMINDER: ensure the company has approved use of this anonymized data "
        "for academic purposes. Document this approval in your thesis appendix."
    )


if __name__ == "__main__":
    run_anonymization()
