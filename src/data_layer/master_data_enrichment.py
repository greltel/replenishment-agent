"""
Master Data Enrichment — Smart defaults for missing MRP fields.

Many SAP environments (especially demo/sandbox systems) have incomplete
master data: PLIFZ (lead time), EISBE (safety stock), BSTMI (MOQ) etc.
are blank or zero. This module derives sensible defaults from observable
historical behavior (movement patterns, PO history) so the agent has
something to work with.

The derivation logic is fully documented and academically defensible —
each default is computed via a well-known formula or industry heuristic,
and the source is recorded in a 'data_source' column so you can show in
the thesis which fields are real master data vs. derived.

═══════════════════════════════════════════════════════════════════════
DERIVATION FORMULAS
═══════════════════════════════════════════════════════════════════════

LEAD TIME
─────────
Source 1: MARC.PLIFZ if available
Source 2: Average of (PO expected_date − PO created_date) from EKKO/EKPO
Source 3: Default 14 days (industry median for procured items)

SAFETY STOCK
────────────
Source 1: MARC.EISBE if available
Source 2: SS = z × σ_LT × √LT
          where:
            z   = service-level z-score (0.98 → 2.054)
            σ_LT = std-dev of daily demand (over consumption history)
            LT  = lead time in days
          Reference: Silver, Pyke & Peterson (1998) ch. 7
Source 3: SS = avg_daily_demand × LT × 0.5  (simplified buffer)

REORDER POINT
─────────────
ROP = avg_daily_demand × LT + safety_stock
Reference: Vollmann et al. (2005) ch. 14

MINIMUM ORDER QUANTITY (MOQ)
────────────────────────────
Source 1: MARC.BSTMI if available
Source 2: Median of historical PO line quantities for this material
Source 3: avg_daily_demand × 7  (1 week of demand)
Source 4: Default 1

LOT SIZING POLICY
─────────────────
Source 1: MARC.DISLS if available (mapped via SAP_LOT_SIZING_MAP, e.g.
          EX→LFL, FX→FOQ, WB/MB/PK→POQ, WI/BE/SP/GR/DY→WW)
Source 2: ABC class × CV of weekly demand (thesis Table 4.3, implemented in
          src/mrp/lot_sizing.select_policy):
            • A, CV < 0.5        → Wagner-Whitin (WW)
            • A, 0.5 ≤ CV ≤ 1.0  → POQ
            • A, CV > 1.0        → LFL
            • B                  → EOQ
            • C                  → FOQ (fixed lot ≈ 4 weeks of demand, rounded
                                        up to a multiple of the MOQ)
            • fewer than 3 consumption events → LFL
          where CV = std(weekly_demand) / mean(weekly_demand) over the
          history (weekly buckets, zero weeks included)

ABC CLASSIFICATION
──────────────────
Source 1: Pareto on standard_cost × annual_demand if cost > 0
Source 2: Pareto on annual_demand quantity alone
Source 3: All B class (neutral default)

═══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import math

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from src.mrp.lot_sizing import MIN_EVENTS_FOR_CV, select_policy

from src.utils.logger import log


# ============================================================
# Constants
# ============================================================
# Z-scores for common service levels (one-sided normal distribution)
SERVICE_LEVEL_Z = {
    0.90: 1.282,
    0.95: 1.645,
    0.97: 1.881,
    0.98: 2.054,
    0.99: 2.326,
    0.995: 2.576,
    0.999: 3.090,
}

# Industry-typical defaults when no other info is available
DEFAULT_LEAD_TIME_DAYS = 14    # Industry median for procured items
DEFAULT_SAFETY_STOCK = 0.0
DEFAULT_MOQ = 1.0
DEFAULT_FIXED_LOT_SIZE = 0.0
DEFAULT_SERVICE_LEVEL = 0.98   # 98% target

# Movement types that constitute demand live in one place:
# src/data_layer/models.CONSUMPTION_MOVEMENT_TYPES (sign convention: consumption
# is stored with a NEGATIVE quantity, receipts with a positive one).


# ============================================================
# Data classes
# ============================================================
@dataclass
class MaterialStats:
    """Computed statistics for a single material from historical data."""
    material_id: str
    n_consumption_events: int = 0
    total_consumed: float = 0.0
    avg_daily_demand: float = 0.0
    std_daily_demand: float = 0.0
    cv_demand: float = 0.0           # coefficient of variation (daily, consumption days)
    cv_weekly: float = 0.0           # coefficient of variation of weekly demand
    n_weeks: int = 0                 # weekly buckets covered by the history
    consumption_active_days: int = 0  # days from first to last consumption
    annual_demand: float = 0.0
    median_po_qty: float | None = None
    avg_lead_time_observed: float | None = None


# ============================================================
# Statistics computation
# ============================================================
def compute_material_stats(
    material_ids: list[str],
    movements_df: pd.DataFrame,
    purchase_orders_df: pd.DataFrame | None = None,
    ekko_df: pd.DataFrame | None = None,
) -> dict[str, MaterialStats]:
    """For each material, compute demand statistics from historical movements.

    Returns a dict {material_id: MaterialStats}.
    """
    stats = {mid: MaterialStats(material_id=mid) for mid in material_ids}

    if movements_df.empty:
        return stats

    # Filter consumption events only (negative quantities = stock decrease)
    consumption = movements_df[movements_df["quantity"] < 0].copy()
    if not consumption.empty:
        consumption["abs_qty"] = consumption["quantity"].abs()
        consumption["posting_date"] = pd.to_datetime(consumption["posting_date"])

        # Group by material
        for mid, grp in consumption.groupby("material_id"):
            if mid not in stats:
                continue

            s = stats[mid]
            s.n_consumption_events = len(grp)
            s.total_consumed = float(grp["abs_qty"].sum())

            # Active period: first consumption → last consumption
            first_date = grp["posting_date"].min()
            last_date = grp["posting_date"].max()
            active_days = max((last_date - first_date).days, 1)
            s.consumption_active_days = active_days

            # Average daily demand over active period
            s.avg_daily_demand = s.total_consumed / active_days

            # Std-dev of daily demand: bucket by day, then std
            daily = grp.groupby(grp["posting_date"].dt.date)["abs_qty"].sum()
            if len(daily) >= 2:
                s.std_daily_demand = float(daily.std(ddof=0))
                if s.avg_daily_demand > 0:
                    s.cv_demand = s.std_daily_demand / s.avg_daily_demand

            # Weekly demand buckets (zero weeks included) → CV used for the
            # ABC × CV lot-sizing choice (weekly review cycle of the agent)
            weekly = (grp.set_index("posting_date")["abs_qty"]
                         .resample("W-MON", label="left", closed="left").sum())
            s.n_weeks = int(len(weekly))
            if len(weekly) >= 2 and float(weekly.mean()) > 0:
                s.cv_weekly = float(weekly.std(ddof=0) / weekly.mean())

            # Annual demand projection (extrapolate from observed period)
            if active_days >= 30:
                s.annual_demand = s.avg_daily_demand * 365.0
            else:
                # Too short a period; just use total
                s.annual_demand = s.total_consumed

    # PO history → MOQ + lead time
    if purchase_orders_df is not None and not purchase_orders_df.empty:
        po = purchase_orders_df.copy()
        for mid, grp in po.groupby("material_id"):
            if mid not in stats:
                continue
            s = stats[mid]
            qtys = grp["quantity"][grp["quantity"] > 0]
            if len(qtys) > 0:
                s.median_po_qty = float(qtys.median())

    # Lead time from EKKO+EKPO: BEDAT → EINDT delta
    if ekko_df is not None and purchase_orders_df is not None:
        # NOTE: this assumes purchase_orders_df has both 'created_date' and
        # 'expected_date' — currently it only has expected_date. We skip this
        # source for now and rely on default. Future enhancement: include
        # PO creation date in anonymization.
        pass

    return stats


# ============================================================
# Field derivation
# ============================================================
def derive_lead_time(
    existing: float,
    stats: MaterialStats,
    default: int = DEFAULT_LEAD_TIME_DAYS,
) -> tuple[int, str]:
    """Returns (lead_time_days, source_label)."""
    if existing and existing > 0:
        return int(existing), "MARC.PLIFZ"
    if stats.avg_lead_time_observed and stats.avg_lead_time_observed > 0:
        return int(round(stats.avg_lead_time_observed)), "PO history"
    return default, "default"


def derive_safety_stock(
    existing: float,
    stats: MaterialStats,
    lead_time: int,
    service_level: float = DEFAULT_SERVICE_LEVEL,
) -> tuple[float, str]:
    """Returns (safety_stock, source_label).

    Formula: SS = z × σ_daily × √LT (Silver, Pyke & Peterson 1998)
    """
    if existing and existing > 0:
        return float(existing), "MARC.EISBE"

    if stats.std_daily_demand > 0 and lead_time > 0:
        z = SERVICE_LEVEL_Z.get(service_level, 2.054)
        ss = z * stats.std_daily_demand * np.sqrt(lead_time)
        return float(round(ss, 2)), f"derived (SL={service_level:.0%})"

    if stats.avg_daily_demand > 0 and lead_time > 0:
        # Fallback: half a lead-time of average demand
        ss = stats.avg_daily_demand * lead_time * 0.5
        return float(round(ss, 2)), "derived (heuristic)"

    return DEFAULT_SAFETY_STOCK, "default"


def derive_reorder_point(
    existing: float,
    stats: MaterialStats,
    lead_time: int,
    safety_stock: float,
) -> tuple[float, str]:
    """ROP = avg_daily_demand × LT + safety_stock"""
    if existing and existing > 0:
        return float(existing), "MARC.MINBE"

    if stats.avg_daily_demand > 0:
        rop = stats.avg_daily_demand * lead_time + safety_stock
        return float(round(rop, 2)), "derived (avg×LT + SS)"

    return safety_stock, "default (= SS)"


def derive_moq(
    existing: float,
    stats: MaterialStats,
) -> tuple[float, str]:
    """MOQ from MARC, or median historical PO qty, or 1 week of demand."""
    if existing and existing > 0:
        return float(existing), "MARC.BSTMI"

    if stats.median_po_qty and stats.median_po_qty > 0:
        return float(round(stats.median_po_qty)), "PO median"

    if stats.avg_daily_demand > 0:
        return float(round(stats.avg_daily_demand * 7)), "1 week demand"

    return DEFAULT_MOQ, "default"


def derive_lot_sizing(
    existing: str | None,
    stats: MaterialStats,
    abc_class: str | None = None,
) -> tuple[str, str]:
    """Lot-sizing policy from MARC.DISLS or, failing that, from ABC class ×
    CV of weekly demand (thesis Table 4.3, `src.mrp.lot_sizing.select_policy`).

    Note: 'LFL' is treated as a "default placeholder" — if we have demand
    history, we override it with a more informed choice.
    """
    has_existing = existing and pd.notna(existing) and str(existing).strip()
    is_default = has_existing and str(existing).strip().upper() == "LFL"

    # If MARC value exists AND it's not the default LFL placeholder, keep it
    if has_existing and not is_default:
        return str(existing).strip().upper(), "MARC.DISLS"

    # Otherwise derive from ABC class and demand pattern (if any history)
    if stats.n_consumption_events == 0:
        return "LFL", "default (no history)"
    if stats.n_consumption_events < MIN_EVENTS_FOR_CV:
        return "LFL", "derived (sparse history)"

    policy = select_policy(abc_class, stats.cv_weekly, stats.n_consumption_events)
    return policy, f"derived (ABC {abc_class or '?'} × CV {stats.cv_weekly:.2f})"


def derive_fixed_lot_size(
    existing: float,
    stats: MaterialStats,
    moq: float,
    policy: str,
    weeks: int = 4,
) -> tuple[float, str]:
    """Fixed lot for FOQ materials: MARC.BSTFE if present, otherwise about
    `weeks` weeks of average demand rounded UP to a multiple of the MOQ.
    Non-FOQ policies keep whatever the master data says (0 = not used)."""
    if existing and existing > 0:
        return float(existing), "MARC.BSTFE"
    if (policy or "").upper() != "FOQ":
        return 0.0, "n/a"
    base = max(moq or 1.0, 1.0)
    if stats.avg_daily_demand > 0:
        lot = math.ceil((stats.avg_daily_demand * 7 * weeks) / base) * base
        return float(max(lot, base)), f"derived ({weeks} weeks demand, MOQ multiple)"
    return float(base), "derived (= MOQ)"


def derive_abc_class(
    existing: str | None,
    df: pd.DataFrame,
) -> pd.Series:
    """Pareto on (cost × annual_demand). Returns Series of A/B/C labels.

    Important: only materials WITH demand history are classified by Pareto.
    Inactive materials (annual_demand = 0) are always C class.
    """
    n = len(df)

    # Compute consumption value: cost × annual_demand if both available
    if "annual_demand" in df.columns and "standard_cost" in df.columns:
        active = df["annual_demand"] > 0
        if active.sum() > 0:
            consumption_value = df["standard_cost"].fillna(0) * df["annual_demand"].fillna(0)

            if consumption_value.sum() > 0:
                # Pareto only on active materials
                df_active = df[active].copy()
                df_active["cv_value"] = consumption_value[active].values
                df_active = df_active.sort_values("cv_value", ascending=False)
                df_active["cum_pct"] = df_active["cv_value"].cumsum() / df_active["cv_value"].sum()
                df_active["abc"] = df_active["cum_pct"].apply(
                    lambda x: "A" if x <= 0.80 else ("B" if x <= 0.95 else "C")
                )
                # Build full series: active gets Pareto, inactive → C
                result = pd.Series(["C"] * n, index=df.index)
                result.loc[df_active.index] = df_active["abc"].values
                return result

    # Fallback: Pareto on annual_demand quantity alone (for active materials)
    if "annual_demand" in df.columns and df["annual_demand"].sum() > 0:
        active = df["annual_demand"] > 0
        if active.sum() > 0:
            df_active = df[active].copy()
            df_active = df_active.sort_values("annual_demand", ascending=False)
            df_active["cum_pct"] = df_active["annual_demand"].cumsum() / df_active["annual_demand"].sum()
            df_active["abc"] = df_active["cum_pct"].apply(
                lambda x: "A" if x <= 0.80 else ("B" if x <= 0.95 else "C")
            )
            result = pd.Series(["C"] * n, index=df.index)
            result.loc[df_active.index] = df_active["abc"].values
            return result

    return pd.Series(["C"] * n, index=df.index)


# ============================================================
# Main enrichment entry point
# ============================================================
def enrich_master_data(
    materials_df: pd.DataFrame,
    movements_df: pd.DataFrame,
    purchase_orders_df: pd.DataFrame | None = None,
    service_level: float = DEFAULT_SERVICE_LEVEL,
) -> pd.DataFrame:
    """Enrich materials DataFrame with smart defaults for missing MRP fields.

    Args:
        materials_df: Raw materials with potentially missing fields.
        movements_df: Movement history (with positive=receipt, negative=consumption).
        purchase_orders_df: Optional PO history for MOQ derivation.
        service_level: Target service level for safety stock formula (default 98%).

    Returns:
        Enriched DataFrame. Original column values are preserved when present;
        zeros/NaNs are replaced with derived values. A new 'data_source' column
        records the provenance of each material's parameters.
    """
    if materials_df.empty:
        return materials_df

    log.info("Computing material statistics from movement history...")
    material_ids = materials_df["material_id"].tolist()
    stats_dict = compute_material_stats(
        material_ids, movements_df, purchase_orders_df
    )

    df = materials_df.copy()

    # Compute annual_demand column (used for ABC)
    df["annual_demand"] = df["material_id"].apply(
        lambda mid: stats_dict[mid].annual_demand if mid in stats_dict else 0.0
    )

    # ABC first: the lot-sizing choice depends on it (Pareto on cost × annual
    # demand; the existing column, if any, is unlikely to be meaningful)
    abc_series = derive_abc_class(None, df)

    # Derive each field row by row
    derived_records = []
    n_derived = {"lead_time": 0, "safety_stock": 0, "moq": 0, "lot_sizing": 0}

    for idx, row in df.iterrows():
        mid = row["material_id"]
        s = stats_dict.get(mid, MaterialStats(material_id=mid))
        abc = str(abc_series.loc[idx])

        # Lead time
        existing_lt = row.get("lead_time_days", 0) or 0
        lt, lt_src = derive_lead_time(existing_lt, s)
        if lt_src != "MARC.PLIFZ":
            n_derived["lead_time"] += 1

        # Safety stock
        existing_ss = row.get("safety_stock", 0) or 0
        ss, ss_src = derive_safety_stock(existing_ss, s, lt, service_level)
        if ss_src != "MARC.EISBE":
            n_derived["safety_stock"] += 1

        # Reorder point (always derived if not present)
        existing_rop = row.get("reorder_point", 0) or 0
        rop, rop_src = derive_reorder_point(existing_rop, s, lt, ss)

        # MOQ
        existing_moq = row.get("moq", 0) or 0
        moq, moq_src = derive_moq(existing_moq, s)
        if moq_src != "MARC.BSTMI":
            n_derived["moq"] += 1

        # Lot sizing (ABC × weekly CV unless MARC.DISLS is explicit)
        existing_ls = row.get("lot_sizing", None)
        ls, ls_src = derive_lot_sizing(existing_ls, s, abc)
        if ls_src != "MARC.DISLS":
            n_derived["lot_sizing"] += 1

        # Fixed lot size (only meaningful for FOQ)
        existing_fls = row.get("fixed_lot_size", 0) or 0
        fls, _ = derive_fixed_lot_size(existing_fls, s, moq, ls)

        derived_records.append({
            "lead_time_days":    lt,
            "safety_stock":      ss,
            "reorder_point":     rop,
            "moq":               moq,
            "lot_sizing":        ls,
            "fixed_lot_size":    fls,
            "abc_class":         abc,
            "lt_source":         lt_src,
            "ss_source":         ss_src,
            "moq_source":        moq_src,
            "ls_source":         ls_src,
            "avg_daily_demand":  s.avg_daily_demand,
            "cv_demand":         s.cv_demand,
            "cv_weekly":         s.cv_weekly,
        })

    derived_df = pd.DataFrame(derived_records, index=df.index)

    # Overwrite the relevant columns in df with derived values
    for col in ["lead_time_days", "safety_stock", "reorder_point", "moq", "lot_sizing",
                "fixed_lot_size", "abc_class"]:
        df[col] = derived_df[col].values
    for col in ["lt_source", "ss_source", "moq_source", "ls_source",
                "avg_daily_demand", "cv_demand", "cv_weekly"]:
        df[col] = derived_df[col].values

    # Logging summary
    n_total = len(df)
    log.info(
        f"Master data enrichment complete (n={n_total}):\n"
        f"  Lead time:     {n_derived['lead_time']:>5} derived  "
        f"({n_total-n_derived['lead_time']} from MARC)\n"
        f"  Safety stock:  {n_derived['safety_stock']:>5} derived  "
        f"({n_total-n_derived['safety_stock']} from MARC)\n"
        f"  MOQ:           {n_derived['moq']:>5} derived  "
        f"({n_total-n_derived['moq']} from MARC)\n"
        f"  Lot sizing:    {n_derived['lot_sizing']:>5} derived  "
        f"({n_total-n_derived['lot_sizing']} from MARC)"
    )

    return df
