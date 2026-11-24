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
import io
from collections import defaultdict
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
# Pseudonyms lengthened for the values whose short hash collides with the
# one of another value of the same dataset (filled by run_anonymization).
_PSEUDONYM_OVERRIDES: dict[tuple[str, str], str] = {}


def pseudonymize(value, prefix: str, length: int = 8) -> str:
    """Deterministic pseudonym — same input always produces same output.
    Non-reversible (one-way hash). Values whose short hash collides with
    another value of the dataset get a longer one (see unique_pseudonyms)."""
    if pd.isna(value):
        return f"{prefix}NA"
    text = str(value)
    override = _PSEUDONYM_OVERRIDES.get((prefix, text))
    if override is not None:
        return override
    h = hashlib.md5(text.encode()).hexdigest()[:length].upper()
    return f"{prefix}{h}"


def unique_pseudonyms(values, prefix: str, length: int) -> dict[str, str]:
    """Longer pseudonyms for the values whose `length`-character hash
    collides with the hash of another value.

    An 8-character hash has 16^8 ≈ 4.3e9 values: with ~230,000 materials
    about six pairs of different materials share one (birthday problem),
    and the ETL then fails on the duplicate material_id. Every value of a
    colliding group gets `length` + 4 characters (more if still taken);
    all other values keep their usual pseudonym, so the IDs of datasets
    without collisions do not change. Returns {value text: pseudonym}.
    """
    texts = {str(v) for v in values if not pd.isna(v)}
    groups: dict[str, list[str]] = defaultdict(list)
    for text in texts:
        groups[hashlib.md5(text.encode()).hexdigest()[:length]].append(text)
    taken = {prefix + h.upper() for h in groups}
    overrides: dict[str, str] = {}
    for group in groups.values():
        if len(group) < 2:
            continue
        for text in sorted(group):
            digest = hashlib.md5(text.encode()).hexdigest().upper()
            n = length + 4
            candidate = prefix + digest[:n]
            while candidate in taken:
                n += 1
                candidate = (prefix + digest[:n] if n <= len(digest)
                             else f"{prefix}{digest}{n - len(digest)}")
            taken.add(candidate)
            overrides[text] = candidate
    return overrides


# Key columns read as text: a numeric-looking code keeps its leading zeros
# and never becomes 123.0 — the same SAP value then gets the same
# pseudonym in every file, whatever pandas would infer per file.
KEY_TEXT_COLUMNS = ("MATNR", "EBELN", "WERKS")


def _read_any(path: Path) -> pd.DataFrame:
    """Read either xlsx or csv. Auto-detects delimiter for CSVs (handles
    both ',' and ';' — SAP exports typically use ';' as field separator)."""
    if path.suffix in (".xlsx", ".xls"):
        return pd.read_excel(path)
    # Auto-detect delimiter by reading a sample
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        sample = f.readline()
    sep = ";" if sample.count(";") > sample.count(",") else ","
    names = [c.strip() for c in sample.rstrip("\r\n").split(sep)]
    dtype = {c: str for c in KEY_TEXT_COLUMNS if c in names}
    source = _repair_separator_in_key(path, sep, names)
    return pd.read_csv(source, sep=sep, encoding="utf-8", dtype=dtype or None)


def _repair_separator_in_key(path: Path, sep: str, names: list[str],
                             key: str = "MATNR"):
    """The CSV itself, or a repaired copy when material numbers contain the
    field separator.

    ZMRP_AGENT_EXPORT replaces ';' in the description but writes MATNR as
    it is, and SAP allows ';' in a material number (e.g. '1234;5'): such a
    line has more fields than the header and pandas stops. The surplus
    fields of an unquoted line are joined back into the MATNR field, which
    is then quoted. Returns the path unchanged when no line needs it.
    """
    if key not in names:
        return path
    with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as f:
        lines = f.read().split("\n")
    n_sep = len(names) - 1
    pos = names.index(key)
    repaired = 0
    for i in range(1, len(lines)):
        line = lines[i]
        if line.count(sep) <= n_sep or '"' in line:
            continue
        parts = line.rstrip("\r").split(sep)
        extra = len(parts) - len(names)
        merged = sep.join(parts[pos:pos + extra + 1])
        lines[i] = sep.join(parts[:pos] + [f'"{merged}"'] + parts[pos + extra + 1:])
        repaired += 1
    if not repaired:
        return path
    log.warning(f"{path.name}: {repaired} line(s) with '{sep}' inside {key} "
                f"read as one field")
    return io.StringIO("\n".join(lines))


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


# SAP lot-sizing procedure (MARC-DISLS, customizing table T439A) → internal
# policy. Static procedures map to LFL/FOQ/POQ; the "optimum" procedures
# (least unit cost, part-period balancing, Groff, dynamic lot size) all
# pursue the same cost trade-off as Wagner-Whitin, so they map to WW.
SAP_LOT_SIZING_MAP: dict[str, str] = {
    "EX": "LFL",   # lot-for-lot (exact)
    "TB": "LFL",   # daily lot size
    "FX": "FOQ",   # fixed order quantity
    "HB": "FOQ",   # replenish up to maximum stock level (fixed target)
    "WB": "POQ",   # weekly lot size
    "MB": "POQ",   # monthly lot size
    "PK": "POQ",   # period lot size per planning calendar
    "WI": "WW",    # least unit cost procedure
    "BE": "WW",    # part-period balancing
    "SP": "WW",    # Groff / dynamic lot size creation
    "GR": "WW",    # Groff reorder procedure
    "DY": "WW",    # dynamic lot size
    "EOQ": "EOQ", "LFL": "LFL", "FOQ": "FOQ", "POQ": "POQ", "WW": "WW",
}


def unit_cost_from_valuation(df: pd.DataFrame) -> pd.Series:
    """Cost per base unit from the SAP valuation fields (MBEW, carried in the
    MARC export since ZMRP_AGENT_EXPORT v1.2).

    Price control VPRSV = 'S' → standard price STPRS, 'V' → moving average
    price VERPR; if that price is 0, the other one is used. Both are per
    PEINH units (price unit, usually 1). Returns 0 where no price exists —
    the cost estimator then imputes a benchmark cost.
    """
    def _num(col: str) -> pd.Series:
        if col in df.columns:
            return parse_sap_number_series(df[col])
        return pd.Series(0.0, index=df.index)

    stprs, verpr, peinh = _num("STPRS"), _num("VERPR"), _num("PEINH")
    vprsv = (df["VPRSV"].fillna("").astype(str).str.strip().str.upper()
             if "VPRSV" in df.columns else pd.Series("", index=df.index))

    moving_avg = vprsv == "V"
    primary = verpr.where(moving_avg, stprs)
    secondary = stprs.where(moving_avg, verpr)
    price = primary.where(primary > 0, secondary)
    return (price / peinh.where(peinh > 0, 1.0)).clip(lower=0.0).round(4)


# ============================================================
# Per-table anonymization
# ============================================================
def anonymize_materials(
    raw_dir: Path,
    out_dir: Path,
    enrich_with: Path | None = None,
    include_descriptions: bool = True,
    keep: set[str] | None = None,
    exclude: set[str] | None = None,
) -> None:
    """Combine MARA + MARC + MARD-derived data into materials.csv.

    Args:
        raw_dir: Source folder with SAP exports.
        out_dir: Destination folder for anonymized CSVs.
        enrich_with: If provided, look in this folder for already-anonymized
            movements.csv and purchase_orders.csv to compute smart defaults
            for missing MRP fields (lead_time, safety_stock, MOQ, lot_sizing,
            ABC class).
        keep: If given, only these material_ids are written (MATERIAL_SCOPE
            = active, see restrict_to_active_materials).
        exclude: material_ids never written (EXCLUDE_MATERIAL_GROUPS /
            EXCLUDE_MATERIALS, see excluded_material_ids).
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
        marc_first = marc.drop_duplicates(subset=["material_id"], keep="first").copy()
        # Valuation price (MBEW via the MARC export, ZMRP_AGENT_EXPORT v1.2)
        marc_first["valuation_cost"] = unit_cost_from_valuation(marc_first)

        df = df.merge(marc_first[[
            "material_id", "DISMM", "DISLS", "PLIFZ", "EISBE", "MINBE", "BSTMI",
            "valuation_cost",
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

        # Map SAP lot-sizing procedures (MARC-DISLS) to our internal codes
        # Unknown / blank procedures stay blank so that the enrichment can
        # choose a policy from ABC × CV (an explicit "EX" stays lot-for-lot).
        df["lot_sizing"] = (df["lot_sizing_raw"].astype(str).str.strip().str.upper()
                            .map(SAP_LOT_SIZING_MAP).fillna(""))
        df = df.drop(columns=["lot_sizing_raw"])

        # Unit cost: MBEW price from the MARC export; MARA-STPRS (manual
        # SE16N exports) stays the fallback. Zero → imputed by cost_estimator.
        valuation = df["valuation_cost"].fillna(0.0)
        df["standard_cost"] = valuation.where(valuation > 0, df["standard_cost"])
        df = df.drop(columns=["valuation_cost"])
        log.info(f"Valuation price (MBEW) for {int((valuation > 0).sum())} "
                 f"of {len(df)} materials")

    if keep is not None:
        df = df[df["material_id"].isin(keep)].reset_index(drop=True)
    if exclude:
        df = df[~df["material_id"].isin(exclude)].reset_index(drop=True)

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


def _stock_quantity(df: pd.DataFrame):
    """Stock per MARD line: the sum of the stock types of
    config.stock_columns (env STOCK_COLUMNS, default LABST = unrestricted).

    The movement history (MB51) holds the postings into and out of every
    stock type, so the stock roll-back to an earlier date is exact only if
    the snapshot counts the same types: a company that receives into
    blocked stock (SPEME) and releases it later has goods in the warehouse
    that LABST alone does not show. Columns missing from the export
    (older ZMRP_AGENT_EXPORT versions) are left out.
    """
    present = [c for c in config.stock_columns if c in df.columns]
    missing = [c for c in config.stock_columns if c not in df.columns]
    if tuple(present) != ("LABST",) or missing:
        log.info(f"Stock = {' + '.join(present) or '0'}"
                 + (f" (not in the export: {', '.join(missing)})" if missing else ""))
    if not present:
        return 0
    total = parse_sap_number_series(df[present[0]])
    for col in present[1:]:
        total = total + parse_sap_number_series(df[col])
    return total


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
        "quantity":      _stock_quantity(df),
        "snapshot_date": pd.Timestamp.today().normalize().date()
                          if "ERSDA" not in df.columns
                          else _parse_sap_date(df["ERSDA"]).dt.date,
    })

    out.to_csv(out_dir / "stock.csv", index=False)
    log.success(f"Wrote stock.csv ({len(out)} rows)")


def anonymize_purchase_orders(raw_dir: Path, out_dir: Path) -> None:
    """Combine EKKO + EKPO → purchase_orders.csv.

    Columns: po_number, material_id, supplier_id, quantity, expected_date,
    status (the ETL contract) + ordered_quantity, created_date,
    planned_delivery_date.

    status / quantity:
      • CANCELLED — LOEKZ set; RECEIVED — ELIKZ set or nothing left to
        receive; both keep the ordered quantity and are never supply.
      • OPEN — the rest; quantity = still to be received. With
        ZMRP_AGENT_EXPORT v1.3 (column WEMNG) that is MENGE − WEMNG; older
        exports held open items only, without receipts, so MENGE.
    expected_date = when the quantity is due: for OPEN lines of v1.3
    exports the first schedule line not fully received (EINDT_OPEN), else
    the first schedule line (EINDT).
    created_date = PO date (EKPO-BEDAT from v1.3, else EKKO-BEDAT) and
    planned_delivery_date = EINDT give the planned lead time
    (master_data_enrichment).
    """
    ekko_path = _find_export(raw_dir, "EKKO_export")
    ekpo_path = _find_export(raw_dir, "EKPO_export")

    if ekpo_path is None:
        log.warning("EKPO_export.* not found in raw dir")
        return

    ekpo = _read_any(ekpo_path)
    ebeln = ekpo["EBELN"].astype(str).str.strip()

    # If EKKO available, get LIFNR (supplier) and BEDAT (PO date) from there
    supplier_map: dict = {}
    po_date_map: dict = {}
    if ekko_path is not None:
        ekko = _read_any(ekko_path)
        if "EBELN" in ekko.columns:
            ekko_keys = ekko["EBELN"].astype(str).str.strip()
            if "LIFNR" in ekko.columns:
                supplier_map = dict(zip(ekko_keys, ekko["LIFNR"]))
            if "BEDAT" in ekko.columns:
                po_date_map = dict(zip(ekko_keys, _sap_date_text(ekko["BEDAT"])))

    ordered = (parse_sap_number_series(ekpo["MENGE"]) if "MENGE" in ekpo.columns
               else pd.Series(0.0, index=ekpo.index))
    cancelled = _flag_set(ekpo, "LOEKZ")
    received = _flag_set(ekpo, "ELIKZ")
    if "WEMNG" in ekpo.columns:      # v1.3: every item of the period + receipts
        open_qty = (ordered - parse_sap_number_series(ekpo["WEMNG"])).clip(lower=0.0)
        received = received | (open_qty <= 0)
    else:                            # up to v1.2: open items only, no receipts
        open_qty = ordered
    status = pd.Series("OPEN", index=ekpo.index)
    status[received] = "RECEIVED"
    status[cancelled] = "CANCELLED"

    if "BEDAT" in ekpo.columns:
        po_date = _po_date(ekpo["BEDAT"])
    else:
        po_date = _po_date(ebeln.map(po_date_map))

    first_delivery = _po_date(ekpo.get("EINDT"))
    expected = first_delivery
    if "EINDT_OPEN" in ekpo.columns:   # v1.3: split deliveries
        open_due = _po_date(ekpo["EINDT_OPEN"])
        open_due = open_due.where(open_due.notna(), first_delivery)
        expected = open_due.where(status == "OPEN", first_delivery)

    out = pd.DataFrame({
        "po_number":     ekpo["EBELN"].apply(lambda x: pseudonymize(x, "PO", 6)),
        "material_id":   ekpo["MATNR"].apply(lambda x: pseudonymize(x, "MAT")),
        "supplier_id":   ebeln.map(supplier_map).astype(object).fillna("UNK")
                          .apply(lambda x: pseudonymize(x, "SUP")),
        "quantity":      open_qty.where(status == "OPEN", ordered),
        "expected_date": expected.dt.date,
        "status":        status,
        "ordered_quantity": ordered,
        "created_date":  po_date.dt.date,
        "planned_delivery_date": first_delivery.dt.date,
    })

    out.to_csv(out_dir / "purchase_orders.csv", index=False)
    log.success(f"Wrote purchase_orders.csv ({len(out)} rows, "
                f"{int((status == 'OPEN').sum())} open)")


# Movement types that INCREASE stock / DECREASE stock — used only for
# unsigned exports (see _movement_quantity, rule 3).
RECEIPT_TYPES = {
    "101",  # Goods receipt for PO
    "301",  # Plant-to-plant transfer (receiving plant)
    "309",  # Material-to-material transfer (target)
    "311",  # Storage location transfer (target)
    "321",  # Quality stock to unrestricted
    "651",  # Returns from customer
    "701",  # Inventory diff (positive count)
    # Reversals of ISSUES put the stock back → positive
    "202",  # reversal of 201
    "262",  # reversal of 261
    "282",  # reversal of 281
    "602",  # reversal of 601 (delivery cancelled)
    "642",  # reversal of 641
}
ISSUE_TYPES = {
    "201",         # GI for cost center
    "261",         # GI for production order
    "281",         # GI for network / project
    "302",         # Plant-to-plant transfer (issuing plant)
    "310",         # Material-to-material transfer (source)
    "312",         # Storage location transfer (source)
    "322",         # Unrestricted to quality stock
    "601",         # GI for customer delivery (sales) — a stock DECREASE
    "641",         # Stock transfer order (issuing plant)
    "702",         # Inventory diff (negative count)
    # Reversals of RECEIPTS take the stock out again → negative
    "102",         # reversal of 101
    "652",         # reversal of 651 (customer return cancelled)
}


def _movement_quantity(df: pd.DataFrame, raw_qty: pd.Series,
                       bwart: pd.Series) -> tuple[pd.Series, str]:
    """Signed stock change of every MB51 line (receipt +, issue −).

    The sign is taken, in this order, from:
      1. the debit/credit indicator SHKZG (ZMRP_AGENT_EXPORT v1.3):
         S → +, H → −;
      2. the quantity itself when the export is already signed (both signs
         present — ZMRP_AGENT_EXPORT v1.1/v1.2, MB51 list export);
      3. the movement type (RECEIPT_TYPES / ISSUE_TYPES) for unsigned or
         all-negative exports (ZMRP_AGENT_EXPORT v1.0, SE16N on MSEG).

    Rule 3 cannot tell the two lines of a transfer apart (a 301 or 311
    document has an issuing AND a receiving line with the same movement
    type), so it is only the last resort; SHKZG and signed quantities are
    exact for every movement type.
    """
    if "SHKZG" in df.columns:
        shkzg = df["SHKZG"].map(lambda v: "" if pd.isna(v) else str(v).strip().upper())
        magnitude = raw_qty.abs()
        quantity = raw_qty.copy()
        quantity[shkzg == "S"] = magnitude[shkzg == "S"]
        quantity[shkzg == "H"] = -magnitude[shkzg == "H"]
        return quantity, "SHKZG"

    if (raw_qty > 0).any() and (raw_qty < 0).any():
        return raw_qty.copy(), "signed export"

    def _by_type(bwart_val: str, qty: float) -> float:
        if bwart_val in RECEIPT_TYPES:
            return abs(qty)
        if bwart_val in ISSUE_TYPES:
            return -abs(qty)
        return qty   # unknown movement type: keep the exported sign

    quantity = pd.Series([_by_type(b, q) for b, q in zip(bwart, raw_qty)],
                         index=raw_qty.index, dtype=float)
    return quantity, "movement type (unsigned export)"


# Movement types that do not touch the own warehouse stock in MARD: goods
# receipt into (valuated) GR blocked stock, their reversals and returns.
# The stock enters the warehouse with 105 / 109, which stay in.
NON_STOCK_MOVEMENT_TYPES = {"103", "104", "107", "108", "124", "125"}


def _code_text(series: pd.Series) -> pd.Series:
    """SAP code column as text ('601'), also when pandas read it as float
    because of blanks ('601.0')."""
    return (series.astype(str).str.strip()
            .str.replace(r"^(\d+)\.0$", r"\1", regex=True))


def _sap_date_text(series: pd.Series | None) -> pd.Series | None:
    """YYYYMMDD text of an SAP date column that pandas may have read as a
    number — as float (20251105.0) when the column has blanks."""
    if series is None:
        return None
    if pd.api.types.is_numeric_dtype(series):
        return series.map(lambda v: "" if pd.isna(v) else str(int(v)))
    return series.astype(str)


def _po_date(series: pd.Series | None) -> pd.Series:
    """PO date column → datetime; blanks, '00000000' and implausible years
    (e.g. 50170705 or 99991231, which newer pandas would accept) → NaT."""
    dates = _parse_sap_date(_sap_date_text(series))
    years = dates.dt.year
    return dates.where((years >= 1990) & (years <= 2100))


def _flag_set(df: pd.DataFrame, col: str) -> pd.Series:
    """True where an SAP indicator field (ELIKZ, LOEKZ, …) is set."""
    if col not in df.columns:
        return pd.Series(False, index=df.index)
    text = df[col].map(lambda v: "" if pd.isna(v) else str(v).strip())
    return ~text.isin(["", "nan", "None"])


def _movement_type_texts(raw_dir: Path) -> dict[str, str]:
    """Movement type → text from T156T_export (ZMRP_AGENT_EXPORT v1.8), to
    tell the company's own types (9xx, Z..) apart in the log. A type has
    one text per special stock / movement indicator; the general one (all
    indicators blank) is preferred. Empty when the file is not there."""
    path = _find_export(raw_dir, "T156T_export")
    if path is None:
        return {}
    df = _read_any(path)
    if not {"BWART", "BTEXT"} <= set(df.columns):
        return {}
    df = df.assign(BWART=_code_text(df["BWART"]))
    indicators = [c for c in ("SOBKZ", "KZBEW", "KZZUG", "KZVBR") if c in df.columns]
    blanks = sum(df[c].isna().astype(int) for c in indicators) if indicators else 0
    df = df.assign(_blank=blanks).sort_values(["BWART", "_blank"], ascending=[True, False])
    first = df.drop_duplicates("BWART")
    return {b: str(t).strip() for b, t in zip(first["BWART"], first["BTEXT"]) if pd.notna(t)}


def anonymize_movements(raw_dir: Path, out_dir: Path) -> None:
    """Anonymize MB51 → movements.csv (quantity: receipt +, issue −).

    The sign comes from SHKZG, from the export's own sign or, for unsigned
    exports only, from the movement type — see _movement_quantity.
    """
    path = _find_export(raw_dir, "MB51_export")
    if path is None:
        log.warning("MB51_export.* not found in raw dir")
        return

    df = _read_any(path)

    # Parse the raw quantity (handles trailing minus, whitespace, etc.)
    raw_qty = (parse_sap_number_series(df["MENGE"]) if "MENGE" in df.columns
               else pd.Series(0.0, index=df.index))
    bwart = (_code_text(df["BWART"]) if "BWART" in df.columns
             else pd.Series("261", index=df.index))

    quantity, sign_source = _movement_quantity(df, raw_qty, bwart)
    log.info(f"Movement sign taken from: {sign_source}")

    # GR blocked stock never reaches the warehouse stock (MARD): the stock
    # roll-back and the As-Is replay add up every line, so a receipt posted
    # as 103 and then released with 105 would count twice. Special-stock
    # lines (SOBKZ) stay in: they can be real demand (e.g. 601 from
    # consignment stock); the column is exported for later analysis.
    own_stock = ~bwart.isin(NON_STOCK_MOVEMENT_TYPES)
    if (~own_stock).any():
        log.info(f"Left out {int((~own_stock).sum())} GR blocked stock lines "
                 f"({', '.join(sorted(NON_STOCK_MOVEMENT_TYPES))})")

    out = pd.DataFrame({
        "material_id":   df["MATNR"].apply(lambda x: pseudonymize(x, "MAT")),
        "plant":         df.get("WERKS", "P001").apply(lambda x: pseudonymize(x, "PLT", 4))
                          if "WERKS" in df.columns else "P001",
        "movement_type": bwart,
        "quantity":      quantity,
        "posting_date":  _parse_sap_date(df.get("BUDAT")).dt.date,
    })[own_stock]

    # Which movement types the company uses (lines, net quantity) — shows
    # e.g. how goods receipts are posted (see GR_MOVEMENT_TYPES in config)
    by_type = (out.groupby("movement_type")["quantity"].agg(["count", "sum"])
                  .sort_values("count", ascending=False))
    texts = _movement_type_texts(raw_dir)
    log.info("Movement types (lines, net qty): " + ", ".join(
        f"{t} ({int(r['count'])}, {r['sum']:+.0f})"
        + (f" {texts[t]!r}" if t in texts else "")
        for t, r in by_type.head(20).iterrows()))

    out.to_csv(out_dir / "movements.csv", index=False)
    log.success(f"Wrote movements.csv ({len(out)} rows)")


# Which raw columns feed which pseudonym (prefix, hash length) — the same
# calls as in the anonymize_* functions above.
_PSEUDONYM_SOURCES: dict[tuple[str, int], list[tuple[str, str]]] = {
    ("MAT", 8): [("MARA_export", "MATNR"), ("MARC_export", "MATNR"),
                 ("MARD_export", "MATNR"), ("EKPO_export", "MATNR"),
                 ("MB51_export", "MATNR")],
    ("PO", 6):  [("EKPO_export", "EBELN")],
    ("SUP", 8): [("EKKO_export", "LIFNR")],
    ("PLT", 4): [("MARD_export", "WERKS"), ("MB51_export", "WERKS")],
}


def prepare_unique_pseudonyms(raw_dir: Path) -> dict[str, int]:
    """Find the colliding pseudonyms of this dataset before anything is
    written, so that every file uses the same (unique) IDs. The files are
    read exactly as by the anonymize_* functions. Returns the number of
    lengthened pseudonyms per prefix."""
    _PSEUDONYM_OVERRIDES.clear()
    values: dict[tuple[str, int], set] = defaultdict(set)
    values[("SUP", 8)].add("UNK")          # supplier of a PO without EKKO
    for base in {b for sources in _PSEUDONYM_SOURCES.values() for b, _ in sources}:
        path = _find_export(raw_dir, base)
        if path is None:
            continue
        df = _read_any(path)
        for key, sources in _PSEUDONYM_SOURCES.items():
            for b, col in sources:
                if b == base and col in df.columns:
                    values[key].update(df[col].dropna().tolist())
    counts: dict[str, int] = {}
    for (prefix, length), vals in values.items():
        overrides = unique_pseudonyms(vals, prefix, length)
        for text, pseudo in overrides.items():
            _PSEUDONYM_OVERRIDES[(prefix, text)] = pseudo
        if overrides:
            counts[prefix] = len(overrides)
    if counts:
        log.info("Pseudonyms lengthened to stay unique: " + ", ".join(
            f"{p} {n}" for p, n in counts.items()))
    return counts


def restrict_to_active_materials(out_dir: Path) -> set[str]:
    """MATERIAL_SCOPE=active: keep only the materials with a movement in the
    export, stock or an open purchase order, and drop the rest from
    stock.csv, purchase_orders.csv and movements.csv (the files are
    rewritten with their text unchanged). A material without any of the
    three has no demand, no stock and no supply to plan — a large SAP
    catalogue (e.g. 230,000 spare parts of which ~40,000 move) would
    otherwise make the agent and the backtest many times slower.
    Returns the material_ids kept."""
    def _read(name: str) -> pd.DataFrame:
        path = out_dir / name
        if not path.exists():
            return pd.DataFrame(columns=["material_id"])
        return pd.read_csv(path, dtype=str, keep_default_na=False)

    stock, pos, moves = _read("stock.csv"), _read("purchase_orders.csv"), _read("movements.csv")
    active = set(moves["material_id"])
    if "quantity" in stock.columns:
        active |= set(stock.loc[pd.to_numeric(stock["quantity"], errors="coerce") > 0,
                                "material_id"])
    if "status" in pos.columns:
        active |= set(pos.loc[pos["status"] == "OPEN", "material_id"])
    for name, df in (("stock.csv", stock), ("purchase_orders.csv", pos),
                     ("movements.csv", moves)):
        if (out_dir / name).exists():
            df[df["material_id"].isin(active)].to_csv(out_dir / name, index=False)
    return active


def excluded_material_ids(raw_dir: Path, groups=None, numbers=None) -> set[str]:
    """EXCLUDE_MATERIAL_GROUPS / EXCLUDE_MATERIALS: the material_ids of the
    MARA materials whose material group (MATKL) or material number (MATNR)
    is listed — e.g. parts of another business that were created with the
    same material type. Empty lists (the default) → an empty set.
    A group list with a MARA export without MATKL is an error: the
    exclusion would silently do nothing."""
    groups = {g.strip().upper() for g in (config.exclude_material_groups
                                          if groups is None else groups) if g.strip()}
    numbers = {n.strip() for n in (config.exclude_materials
                                   if numbers is None else numbers) if n.strip()}
    if not groups and not numbers:
        return set()
    mara_path = _find_export(raw_dir, "MARA_export")
    if mara_path is None:
        return set()
    mara = _read_any(mara_path)
    matnr = mara["MATNR"].astype(str).str.strip()
    mask = matnr.isin(numbers)
    if groups:
        if "MATKL" not in mara.columns:
            raise ValueError("EXCLUDE_MATERIAL_GROUPS is set but MARA_export has no MATKL column")
        mask |= mara["MATKL"].fillna("").astype(str).str.strip().str.upper().isin(groups)
    missing = numbers - set(matnr)
    if missing:
        log.warning(f"EXCLUDE_MATERIALS: {len(missing)} material number(s) not in MARA_export")
    return set(mara.loc[mask, "MATNR"].apply(lambda x: pseudonymize(x, "MAT")))


def drop_materials(out_dir: Path, material_ids: set[str]) -> dict[str, int]:
    """Remove the given materials from stock.csv, purchase_orders.csv and
    movements.csv (rewritten with their text unchanged). Returns the
    number of rows removed per file."""
    removed = {}
    for name in ("stock.csv", "purchase_orders.csv", "movements.csv"):
        path = out_dir / name
        if not path.exists():
            continue
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        drop = df["material_id"].isin(material_ids)
        removed[name] = int(drop.sum())
        if removed[name]:
            df[~drop].to_csv(path, index=False)
    return removed


def run_anonymization() -> None:
    """Run the full anonymization pipeline.

    Order matters: we anonymize movements & POs first, then use them to
    enrich materials with smart defaults for missing MRP fields.
    """
    log.info("=== Anonymization Pipeline ===")
    raw_dir = config.data_raw_dir
    out_dir = config.data_anonymized_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    scope = (config.material_scope or "all").strip().lower()
    if scope not in ("all", "active"):
        raise ValueError(f"MATERIAL_SCOPE must be 'all' or 'active' (got {config.material_scope!r})")

    # Step 0: unique pseudonyms for this dataset
    prepare_unique_pseudonyms(raw_dir)

    # Step 1: Stock, POs and movements first (they don't depend on each other)
    anonymize_stock(raw_dir, out_dir)
    anonymize_purchase_orders(raw_dir, out_dir)
    anonymize_movements(raw_dir, out_dir)

    # Materials of another business (EXCLUDE_MATERIAL_GROUPS / _MATERIALS)
    # are removed before the scope is drawn: they are neither planned nor
    # part of the As-Is.
    excluded = excluded_material_ids(raw_dir)
    if excluded:
        removed = drop_materials(out_dir, excluded)
        log.info(f"Excluded {len(excluded)} materials (groups "
                 f"{','.join(config.exclude_material_groups) or '-'}, "
                 f"{len(config.exclude_materials)} material numbers); rows removed: "
                 + ", ".join(f"{k} {v}" for k, v in removed.items()))

    keep = None
    if scope == "active":
        keep = restrict_to_active_materials(out_dir)
        log.info(f"Material scope 'active': {len(keep)} materials with a movement, "
                 f"stock or an open purchase order")

    # Step 2: Materials, enriched with stats from movements & POs
    anonymize_materials(raw_dir, out_dir, enrich_with=out_dir, keep=keep,
                        exclude=excluded or None)

    log.success("Anonymization complete!")
    log.info(f"Output: {out_dir}")
    log.warning(
        "REMINDER: ensure the company has approved use of this anonymized data "
        "for academic purposes. Document this approval in your thesis appendix."
    )


if __name__ == "__main__":
    run_anonymization()
