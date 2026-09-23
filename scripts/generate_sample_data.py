"""
Generate realistic, reproducible sample data for the agent — calibrated to the
profile of the case company: a Greek importer / distributor of automotive
spare parts that procures thousands of part numbers per year from suppliers
abroad and sells them to garages and retailers.

What the dataset looks like (thesis §3.6.7):
  • ~150 trading goods (SAP material type HAWA) in four part families —
    service consumables (filters, pads, bulbs, oils …), mechanical wear
    parts (discs, shock absorbers, belts …), electrical parts (sensors,
    batteries, alternators …) and body/cooling parts (radiators, lamps …).
    Each family has its own price band, import lead time, pack size (MOQ)
    and demand pattern.
  • Demand is INTERMITTENT, as for spare parts: a part sells on a random
    subset of working days (Mon–Fri, half on Saturday, never on Sunday)
    in small integer quantities; some families are seasonal (winter:
    batteries, bulbs, wipers, antifreeze; summer: A/C parts). Sales are
    recorded as SAP goods issues for outbound deliveries (movement type 601).
  • ~8 % of the parts are phased out (no sales in the last 180 days, high
    stock → dead-stock candidates) and ~5 % are new introductions (short
    history).
  • Master data is DERIVED FROM THE SIMULATED HISTORY with the same rules
    the agent's master-data enrichment applies to real SAP extracts:
    safety stock SS = z × σ_daily × √LT (z = 2.054, 98 % service), reorder
    point = mean_daily × LT + SS, ABC by Pareto on consumption value and the
    lot-sizing policy from ABC × weekly CV (thesis Table 4.3).
  • The As-Is process is an imperfect human planner (thesis §1.2): weekly
    reviews that are sometimes skipped, late reactions once the reorder
    point is crossed, large "container-filling" batches and occasional
    over-ordering "to be safe"; import lead times slip by a few days now
    and then (customs, consolidation). This yields both stockouts and
    overstock — the two costs the agent is meant to reduce.
  • The dataset is INTERNALLY CONSISTENT: the stock snapshot equals opening
    stock + receipts − sales, and the open purchase orders are exactly the
    planner's orders still in transit at the snapshot date.

Everything is deterministic (seed 42).

Usage:
    python scripts/generate_sample_data.py [--n-materials 150]
                                           [--snapshot-date YYYY-MM-DD|today]
                                           [--seed 42]
"""
from __future__ import annotations

import math
import random
import sys
from datetime import date, timedelta
from pathlib import Path

# Ensure project root is on sys.path (so `from src.x import y` works)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd

from src.config import config
from src.mrp.lot_sizing import select_policy


# Reproducibility
SEED = 42
random.seed(SEED)
np.random.seed(SEED)


# ============================================================
# Configuration
# ============================================================
N_MATERIALS = 150
HISTORY_DAYS = 365
# "Extraction date" of the simulated SAP data. Fixed by default so that the
# generated dataset — and every result derived from it — is bit-for-bit
# reproducible regardless of the day the script runs (the agent anchors
# "today" to the data via AS_OF_DATE=auto, so a fixed date is harmless).
# Override with --snapshot-date YYYY-MM-DD or --snapshot-date today.
DEFAULT_SNAPSHOT_DATE = date(2026, 9, 21)
SNAPSHOT_DATE = DEFAULT_SNAPSHOT_DATE
HISTORY_START = SNAPSHOT_DATE - timedelta(days=HISTORY_DAYS - 1)

Z_98 = 2.054                 # service-level z-score used for safety stock
INACTIVE_SHARE = 0.08        # phased-out parts: no sales in the last 180 days
NEW_ITEM_SHARE = 0.05        # new introductions: only exist for the last ~75 days
PLANT = "P001"               # central warehouse
SALES_MVT = "601"            # SAP goods issue for outbound delivery (sales)
RECEIPT_MVT = "101"          # SAP goods receipt for purchase order


# ============================================================
# Part families (the catalogue of an automotive spare-parts importer)
# ============================================================
# item: (description stem, list of variants, unit of measure, season)
#   season: None, "winter" (Nov–Feb) or "summer" (Jun–Aug)
FAMILIES = {
    "service": {   # fast-moving service consumables, EU suppliers, pack sizes
        "items": [
            ("ΦΙΛΤΡΟ ΛΑΔΙΟΥ", ["M20X1.5", "3/4-16 UNF", "Ø76", "Ø93", "Ø65"], "PC", None),
            ("ΦΙΛΤΡΟ ΑΕΡΑ", ["ΠΑΝΕΛ 280X210", "ΠΑΝΕΛ 320X180", "ΚΥΛΙΝΔΡΙΚΟ Ø120"], "PC", None),
            ("ΦΙΛΤΡΟ ΚΑΜΠΙΝΑΣ", ["ΑΠΛΟ", "ΕΝΕΡΓΟΥ ΑΝΘΡΑΚΑ"], "PC", None),
            ("ΦΙΛΤΡΟ ΚΑΥΣΙΜΟΥ", ["ΒΕΝΖΙΝΗΣ 8MM", "DIESEL ΜΕ ΑΙΣΘΗΤΗΡΑ"], "PC", None),
            ("ΤΑΚΑΚΙΑ ΦΡΕΝΩΝ ΕΜΠΡΟΣ", ["ΣΕΤ 17.0MM", "ΣΕΤ 19.5MM", "ΣΕΤ 20.3MM"], "SET", None),
            ("ΤΑΚΑΚΙΑ ΦΡΕΝΩΝ ΠΙΣΩ", ["ΣΕΤ 15.2MM", "ΣΕΤ 17.2MM"], "SET", None),
            ("ΜΠΟΥΖΙ", ["ΝΙΚΕΛΙΟΥ 14MM", "ΙΡΙΔΙΟΥ 14MM", "ΠΛΑΤΙΝΑΣ 12MM"], "PC", None),
            ("ΛΑΜΠΑ", ["H1 12V 55W", "H4 12V 60/55W", "H7 12V 55W", "W5W 12V", "P21W 12V"], "PC", "winter"),
            ("ΥΑΛΟΚΑΘΑΡΙΣΤΗΡΑΣ", ["400MM", "450MM", "530MM", "600MM", "650MM"], "PC", "winter"),
            ("ΛΑΔΙ ΚΙΝΗΤΗΡΑ", ["5W30 1L", "5W30 5L", "5W40 5L", "10W40 4L"], "L", None),
            ("ΥΓΡΟ ΦΡΕΝΩΝ DOT4", ["500ML", "1L"], "PC", None),
            ("ΑΝΤΙΨΥΚΤΙΚΟ G12", ["1L", "4L"], "PC", "winter"),
        ],
        "cost": (2.0, 45.0), "lead_time": (5, 21), "moq": [6, 10, 12, 24, 50],
        "p_active": (0.55, 0.95), "qty_mean": (2.0, 12.0), "mrp_type": "VV",
    },
    "mechanical": {   # wear parts, EU suppliers, small packs
        "items": [
            ("ΔΙΣΚΟΠΛΑΚΑ ΕΜΠΡΟΣ", ["Ø256", "Ø280", "Ø300", "Ø312"], "PC", None),
            ("ΔΙΣΚΟΠΛΑΚΑ ΠΙΣΩ", ["Ø240", "Ø260", "Ø272"], "PC", None),
            ("ΑΜΟΡΤΙΣΕΡ ΑΕΡΙΟΥ ΕΜΠΡΟΣ", ["ΑΡ", "ΔΕ"], "PC", None),
            ("ΑΜΟΡΤΙΣΕΡ ΑΕΡΙΟΥ ΠΙΣΩ", ["ΑΡ", "ΔΕ"], "PC", None),
            ("ΙΜΑΝΤΑΣ ΠΟΛΥ-V", ["6PK1200", "6PK1420", "5PK1050", "4PK860"], "PC", None),
            ("ΣΕΤ ΙΜΑΝΤΑ ΧΡΟΝΙΣΜΟΥ", ["ΜΕ ΑΝΤΛΙΑ ΝΕΡΟΥ", "ΧΩΡΙΣ ΑΝΤΛΙΑ"], "SET", None),
            ("ΑΝΤΛΙΑ ΝΕΡΟΥ", ["ΜΕ ΦΛΑΝΤΖΑ", "ΜΕ ΤΡΟΧΑΛΙΑ"], "PC", None),
            ("ΡΟΥΛΕΜΑΝ ΤΡΟΧΟΥ", ["ΕΜΠΡΟΣ 42X80X45", "ΠΙΣΩ 30X60X37"], "PC", None),
            ("ΑΚΡΟΜΠΑΡΟ", ["ΑΡ M14", "ΔΕ M14"], "PC", None),
            ("ΨΑΛΙΔΙ ΕΜΠΡΟΣ", ["ΑΡ ΚΑΤΩ", "ΔΕ ΚΑΤΩ"], "PC", None),
            ("ΣΕΤ ΣΥΜΠΛΕΚΤΗ", ["Ø215", "Ø228", "Ø240"], "SET", None),
            ("ΘΕΡΜΟΣΤΑΤΗΣ", ["82°C", "87°C", "92°C"], "PC", None),
            ("ΤΕΝΤΩΤΗΡΑΣ ΙΜΑΝΤΑ", ["ΑΥΤΟΜΑΤΟΣ", "ΜΗΧΑΝΙΚΟΣ"], "PC", None),
        ],
        "cost": (15.0, 260.0), "lead_time": (10, 35), "moq": [1, 2, 4, 6],
        "p_active": (0.20, 0.60), "qty_mean": (1.0, 4.0), "mrp_type": "VM",
    },
    "electrical": {   # electrical parts, partly Far-East suppliers
        "items": [
            ("ΑΙΣΘΗΤΗΡΑΣ ABS", ["ΕΜΠΡΟΣ ΑΡ", "ΕΜΠΡΟΣ ΔΕ", "ΠΙΣΩ"], "PC", None),
            ("ΑΙΣΘΗΤΗΡΑΣ ΛΑΜΔΑ", ["4 ΚΑΛΩΔΙΑ", "5 ΚΑΛΩΔΙΑ"], "PC", None),
            ("ΠΟΛΛΑΠΛΑΣΙΑΣΤΗΣ", ["ΜΟΝΟΣ", "ΤΕΤΡΑΠΛΟΣ"], "PC", None),
            ("ΑΝΤΛΙΑ ΒΕΝΖΙΝΗΣ", ["3.5 BAR", "4.0 BAR"], "PC", None),
            ("ΜΠΑΤΑΡΙΑ 12V", ["45AH 400A", "60AH 540A", "74AH 680A", "95AH 800A"], "PC", "winter"),
            ("ΔΥΝΑΜΟ", ["90A", "120A", "150A"], "PC", None),
            ("ΜΙΖΑ", ["1.4KW", "2.0KW"], "PC", "winter"),
            ("ΑΙΣΘΗΤΗΡΑΣ ΣΤΡΟΦΑΛΟΥ", ["2 ΕΠΑΦΕΣ", "3 ΕΠΑΦΕΣ"], "PC", None),
            ("ΒΑΛΒΙΔΑ EGR", ["ΗΛΕΚΤΡΙΚΗ", "ΠΝΕΥΜΑΤΙΚΗ"], "PC", None),
            ("ΔΙΑΚΟΠΤΗΣ ΦΩΤΩΝ ΦΡΕΝΩΝ", ["2 ΕΠΑΦΕΣ", "4 ΕΠΑΦΕΣ"], "PC", None),
        ],
        "cost": (20.0, 420.0), "lead_time": (14, 45), "moq": [1, 2, 4],
        "p_active": (0.10, 0.50), "qty_mean": (1.0, 3.0), "mrp_type": "VM",
    },
    "body": {   # body, lighting and cooling parts — slow, lumpy, long lead times
        "items": [
            ("ΨΥΓΕΙΟ ΝΕΡΟΥ", ["ΑΛΟΥΜΙΝΙΟΥ 600X400", "ΑΛΟΥΜΙΝΙΟΥ 650X450"], "PC", "summer"),
            ("ΨΥΓΕΙΟ A/C", ["ΜΕ ΑΦΥΓΡΑΝΤΗΡΑ", "ΧΩΡΙΣ ΑΦΥΓΡΑΝΤΗΡΑ"], "PC", "summer"),
            ("ΣΥΜΠΙΕΣΤΗΣ A/C", ["7SEU17", "6SEU14"], "PC", "summer"),
            ("ΒΕΝΤΙΛΑΤΕΡ ΨΥΓΕΙΟΥ", ["ΜΟΝΟ", "ΔΙΠΛΟ"], "PC", "summer"),
            ("ΚΑΘΡΕΠΤΗΣ ΕΞΩΤΕΡΙΚΟΣ", ["ΑΡ ΗΛΕΚΤΡ.", "ΔΕ ΗΛΕΚΤΡ."], "PC", None),
            ("ΦΑΝΑΡΙ ΕΜΠΡΟΣ", ["ΑΡ H7", "ΔΕ H7"], "PC", None),
            ("ΦΑΝΑΡΙ ΠΙΣΩ", ["ΑΡ", "ΔΕ"], "PC", None),
            ("ΠΡΟΦΥΛΑΚΤΗΡΑΣ ΕΜΠΡΟΣ", ["ΒΑΦΟΜΕΝΟΣ"], "PC", None),
            ("ΜΟΤΕΡ ΥΑΛΟΚΑΘΑΡΙΣΤΗΡΩΝ", ["ΕΜΠΡΟΣ", "ΠΙΣΩ"], "PC", "winter"),
        ],
        "cost": (40.0, 380.0), "lead_time": (20, 60), "moq": [1, 2],
        "p_active": (0.05, 0.30), "qty_mean": (1.0, 2.0), "mrp_type": "VB",
    },
}
FAMILY_WEIGHTS = {"service": 0.40, "mechanical": 0.30, "electrical": 0.18, "body": 0.12}
SEASON_MONTHS = {"winter": {11, 12, 1, 2}, "summer": {6, 7, 8}}
SEASON_FACTOR = {"winter": 1.8, "summer": 2.2}
N_SUPPLIERS = 25


# ============================================================
# Helpers
# ============================================================
def _rand_choice_weighted(values, weights):
    return random.choices(values, weights=weights, k=1)[0]


def _oe_code() -> str:
    """Pseudo OE part number, e.g. '1K0615301AA' — realism without brands."""
    digits = "".join(random.choice("0123456789") for _ in range(random.choice([4, 5, 6])))
    letters = "".join(random.choice("ABCDEFGHKLMNPRSTU") for _ in range(random.choice([1, 2])))
    return f"{random.choice('01234567')}{letters[0]}{digits}{letters}"


# ============================================================
# Materials (catalogue)
# ============================================================
def generate_catalogue(n_materials: int) -> pd.DataFrame:
    """Part catalogue with hidden demand-process parameters (columns starting
    with `_`); the MRP master data is derived later from the simulated history."""
    rows = []
    for i in range(1, n_materials + 1):
        material_id = f"MAT{i:05d}"
        family = _rand_choice_weighted(list(FAMILY_WEIGHTS), list(FAMILY_WEIGHTS.values()))
        spec = FAMILIES[family]
        stem, variants, uom, season = random.choice(spec["items"])
        description = f"{stem} {random.choice(variants)} OE {_oe_code()}"

        lead_time = random.randint(*spec["lead_time"])
        lo, hi = spec["cost"]
        cost = round(math.exp(random.uniform(math.log(lo), math.log(hi))), 2)   # log-uniform
        moq = random.choice(spec["moq"])
        # Popularity is heavy-tailed (a few fast movers, a long tail of slow
        # movers — the Pareto shape of a spare-parts catalogue)
        popularity = min(max(random.lognormvariate(0.0, 1.25), 0.15), 12.0)
        p_active = min(random.uniform(*spec["p_active"]) * min(popularity, 1.6), 0.98)
        qty_mean = random.uniform(*spec["qty_mean"]) * popularity     # units per sale day

        profile = _rand_choice_weighted(
            ["normal", "inactive", "new"],
            [1 - INACTIVE_SHARE - NEW_ITEM_SHARE, INACTIVE_SHARE, NEW_ITEM_SHARE])

        rows.append({
            "material_id":           material_id,
            "description":           description[:80],
            "material_type":         "HAWA",             # trading goods
            "uom":                   uom,
            "mrp_type":              spec["mrp_type"],   # consumption-based planning
            "lead_time_days":        lead_time,
            "moq":                   float(moq),
            "standard_cost":         cost,
            "preferred_supplier_id": f"SUP{random.randint(1, N_SUPPLIERS):03d}",
            # hidden simulation parameters
            "_family":     family,
            "_p_active":   p_active,
            "_qty_mean":   qty_mean,
            "_season":     season,
            "_profile":    profile,
        })
    return pd.DataFrame(rows)


# ============================================================
# Demand simulation (independent of inventory)
# ============================================================
def _daily_demand(mat: pd.Series, d: date, first_day: date | None) -> float:
    """Sales of part `mat` on day `d` (0 if none)."""
    profile = mat["_profile"]
    if profile == "inactive" and (SNAPSHOT_DATE - d).days < 180:
        return 0.0                     # phased-out: nothing sold in 6 months
    if profile == "new" and first_day is not None and d < first_day:
        return 0.0                     # part did not exist yet

    # Working-week pattern of a B2B distributor
    wd = d.weekday()
    if wd == 6:
        return 0.0
    prob = mat["_p_active"] * (0.5 if wd == 5 else 1.0)
    if random.random() > prob:
        return 0.0

    mean = mat["_qty_mean"]
    season = mat["_season"]
    if isinstance(season, str) and d.month in SEASON_MONTHS[season]:
        mean *= SEASON_FACTOR[season]
    qty = 1 + np.random.poisson(max(mean - 1.0, 0.05))
    return float(qty)


def simulate_demand(catalogue: pd.DataFrame) -> tuple[dict[str, np.ndarray], dict[str, date | None]]:
    """Daily demand series per material over the history (HISTORY_DAYS values)."""
    series: dict[str, np.ndarray] = {}
    first_days: dict[str, date | None] = {}
    for _, mat in catalogue.iterrows():
        first_day = None
        if mat["_profile"] == "new":
            first_day = SNAPSHOT_DATE - timedelta(days=random.randint(60, 90))
        first_days[mat["material_id"]] = first_day
        arr = np.zeros(HISTORY_DAYS)
        for offset in range(HISTORY_DAYS):
            arr[offset] = _daily_demand(mat, HISTORY_START + timedelta(days=offset), first_day)
        series[mat["material_id"]] = arr
    return series, first_days


# ============================================================
# Master data derived from the history (same rules as the enrichment)
# ============================================================
def derive_master_data(catalogue: pd.DataFrame, series: dict[str, np.ndarray],
                       first_days: dict[str, date | None]) -> pd.DataFrame:
    df = catalogue.copy()
    ss_list, rop_list, mean_list, cvw_list, annual_list, n_ev = [], [], [], [], [], []
    for _, mat in df.iterrows():
        mid = mat["material_id"]
        arr = series[mid]
        first_day = first_days[mid]
        # statistics over the period the part existed (last 365 days at most)
        if first_day is not None:
            arr_eff = arr[(first_day - HISTORY_START).days:]
        else:
            arr_eff = arr
        mean_daily = float(arr_eff.mean()) if len(arr_eff) else 0.0
        sigma_daily = float(arr_eff.std(ddof=0)) if len(arr_eff) else 0.0
        weeks = [arr_eff[k:k + 7].sum() for k in range(0, len(arr_eff), 7)]
        cv_w = (float(np.std(weeks, ddof=0) / np.mean(weeks))
                if len(weeks) >= 2 and np.mean(weeks) > 0 else 0.0)
        lt = int(mat["lead_time_days"])
        safety = max(1.0, float(round(Z_98 * sigma_daily * math.sqrt(lt)))) if mean_daily > 0 else 0.0
        rop = float(round(mean_daily * lt + safety))
        ss_list.append(safety); rop_list.append(rop); mean_list.append(mean_daily)
        cvw_list.append(cv_w); annual_list.append(mean_daily * 365.0)
        n_ev.append(int((arr_eff > 0).sum()))
    df["safety_stock"] = ss_list
    df["reorder_point"] = rop_list
    df["_mean_daily"] = mean_list
    df["_cv_weekly"] = cvw_list
    df["annual_demand"] = annual_list
    df["_n_events"] = n_ev

    # ABC: Pareto on consumption value (A ≤ 80 %, B ≤ 95 %, C rest); inactive → C
    value = df["standard_cost"] * df["annual_demand"]
    order = value.sort_values(ascending=False).index
    cum = value.loc[order].cumsum() / max(value.sum(), 1e-9)
    abc = pd.Series("C", index=df.index)
    abc.loc[order] = ["A" if c <= 0.80 else ("B" if c <= 0.95 else "C") for c in cum]
    abc[df["annual_demand"] <= 0] = "C"
    df["abc_class"] = abc

    # Lot-sizing policy: ABC × weekly CV (thesis Table 4.3); fixed lot for FOQ
    policies, fixed = [], []
    for _, m in df.iterrows():
        pol = select_policy(m["abc_class"], m["_cv_weekly"], m["_n_events"])
        policies.append(pol)
        if pol == "FOQ":
            base = max(float(m["moq"]), 1.0)
            lot = math.ceil((m["_mean_daily"] * 28.0) / base) * base if m["_mean_daily"] > 0 else base
            fixed.append(float(max(lot, base)))
        else:
            fixed.append(0.0)
    df["lot_sizing"] = policies
    df["fixed_lot_size"] = fixed
    return df


# ============================================================
# As-Is planner + inventory simulation
# ============================================================
def simulate_history(materials: pd.DataFrame, series: dict[str, np.ndarray],
                     first_days: dict[str, date | None]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Replay the demand against the As-Is planner's ordering behaviour.
    Returns (movements, stock_snapshot, open_pos)."""
    movement_rows, stock_rows, po_rows = [], [], []
    po_counter = 1

    for _, mat in materials.iterrows():
        mid = mat["material_id"]
        lt = int(mat["lead_time_days"])
        rop = float(mat["reorder_point"])
        mean_daily = float(mat["_mean_daily"])
        moq = float(mat["moq"])
        profile = mat["_profile"]
        first_day = first_days[mid]
        arr = series[mid]

        # Opening stock at the start of the history
        stock = rop + random.uniform(0.5, 2.0) * max(mean_daily * 30, 1)
        if profile == "inactive":
            stock *= 2.5               # the classic overstocked phased-out part
        stock = float(math.ceil(stock))
        pending: list[tuple[date, float]] = []   # (arrival_date, qty)

        # Human planner characteristics for this part (thesis §1.2)
        abc = mat["abc_class"]
        review_weekday = random.randint(0, 4)
        neglected = random.random() < 0.20
        skip_prob = 0.35 if neglected else 0.10        # forgets the weekly review
        delay_days = random.randint(0, 7)              # reacts late once ROP is crossed
        batch_days = {"A": random.uniform(30, 60),     # orders this many days of demand
                      "B": random.uniform(45, 90),     # (container / pallet filling)
                      "C": random.uniform(90, 180)}[abc]
        trigger_factor = random.uniform(1.2, 2.2)      # "nervous" early trigger vs ROP
        over_order_prob = {"A": 0.15, "B": 0.20, "C": 0.30}[abc]
        below_rop_since: date | None = None

        for offset in range(HISTORY_DAYS):
            d = HISTORY_START + timedelta(days=offset)

            # 1. receipts arriving today
            still = []
            for arrival, qty in pending:
                if arrival <= d:
                    stock += qty
                    movement_rows.append({
                        "material_id": mid, "plant": PLANT,
                        "movement_type": RECEIPT_MVT, "quantity": qty,
                        "posting_date": arrival,
                    })
                else:
                    still.append((arrival, qty))
            pending = still

            # 2. sales (lost sales if short)
            demand = float(arr[offset])
            if demand > 0:
                sold = min(demand, stock)
                if sold > 0:
                    stock -= sold
                    movement_rows.append({
                        "material_id": mid, "plant": PLANT,
                        "movement_type": SALES_MVT, "quantity": -sold,
                        "posting_date": d,
                    })

            # 3. the human planner
            if profile == "inactive" and (SNAPSHOT_DATE - d).days < 180:
                continue                # nobody re-orders a phased-out part
            if profile == "new" and first_day is not None and d < first_day:
                continue

            on_order = sum(q for _, q in pending)
            if stock + on_order < rop * trigger_factor:
                below_rop_since = below_rop_since or d
            else:
                below_rop_since = None

            if d.weekday() == review_weekday and below_rop_since is not None:
                if random.random() < skip_prob:
                    continue            # skipped this week's review
                if (d - below_rop_since).days < delay_days:
                    continue            # noticed, but hasn't acted yet
                qty = max(mean_daily * batch_days, moq)
                if random.random() < over_order_prob:
                    qty *= 2.0          # "to be safe"
                qty = float(math.ceil(qty / moq) * moq)
                # import lead times slip now and then (customs, consolidation)
                arrival = d + timedelta(days=lt + random.choice([0, 0, 0, 3, 7]))
                pending.append((arrival, qty))
                if arrival > SNAPSHOT_DATE:
                    po_rows.append({
                        "po_number":     f"PO{po_counter:06d}",
                        "material_id":   mid,
                        "supplier_id":   mat["preferred_supplier_id"],
                        "quantity":      qty,
                        "expected_date": arrival,
                        "status":        "OPEN",
                    })
                    po_counter += 1
                below_rop_since = None

        stock_rows.append({
            "material_id":   mid,
            "plant":         PLANT,
            "location":      "L01",
            "quantity":      round(stock),
            "snapshot_date": SNAPSHOT_DATE,
        })

    movements = pd.DataFrame(movement_rows).sort_values(["posting_date", "material_id"])
    movements = movements[movements["posting_date"] <= SNAPSHOT_DATE]
    return movements.reset_index(drop=True), pd.DataFrame(stock_rows), pd.DataFrame(po_rows)


# ============================================================
# Main
# ============================================================
def _parse_args():
    import argparse
    parser = argparse.ArgumentParser(description="Generate reproducible mock SAP data.")
    parser.add_argument("--n-materials", type=int, default=N_MATERIALS,
                        help=f"Number of part numbers (default {N_MATERIALS})")
    parser.add_argument("--snapshot-date", default=None,
                        help="Extraction date of the dataset: YYYY-MM-DD or 'today' "
                             f"(default {DEFAULT_SNAPSHOT_DATE.isoformat()})")
    parser.add_argument("--seed", type=int, default=SEED, help="Random seed (default 42)")
    return parser.parse_args()


def main():
    global SNAPSHOT_DATE, HISTORY_START
    args = _parse_args()
    if args.snapshot_date:
        SNAPSHOT_DATE = (date.today() - timedelta(days=1) if args.snapshot_date == "today"
                         else date.fromisoformat(args.snapshot_date))
        HISTORY_START = SNAPSHOT_DATE - timedelta(days=HISTORY_DAYS - 1)
    random.seed(args.seed)
    np.random.seed(args.seed)

    out = config.data_samples_dir
    out.mkdir(parents=True, exist_ok=True)

    print(f"Generating sample data (seed {args.seed}, snapshot {SNAPSHOT_DATE}, "
          f"{args.n_materials} parts)...")

    catalogue = generate_catalogue(args.n_materials)
    series, first_days = simulate_demand(catalogue)
    materials = derive_master_data(catalogue, series, first_days)
    mvts, stock, pos = simulate_history(materials, series, first_days)

    public_cols = ["material_id", "description", "material_type", "uom", "abc_class",
                   "mrp_type", "lot_sizing", "lead_time_days", "safety_stock",
                   "reorder_point", "moq", "fixed_lot_size", "standard_cost",
                   "preferred_supplier_id"]
    materials[public_cols].to_csv(out / "materials.csv", index=False)
    print(f"  materials.csv         {len(materials):>5} rows")

    stock.to_csv(out / "stock.csv", index=False)
    print(f"  stock.csv             {len(stock):>5} rows")

    pos.to_csv(out / "purchase_orders.csv", index=False)
    print(f"  purchase_orders.csv   {len(pos):>5} rows")

    mvts.to_csv(out / "movements.csv", index=False)
    print(f"  movements.csv         {len(mvts):>5} rows")

    # Summary
    abc_counts = materials["abc_class"].value_counts().to_dict()
    profiles = materials["_profile"].value_counts().to_dict()
    families = materials["_family"].value_counts().to_dict()
    n_short = int((stock["quantity"] < materials["safety_stock"]).sum())
    inv_value = float((stock["quantity"] * materials["standard_cost"]).sum())
    print("\nSummary:")
    print(f"  Part families:    {families}")
    print(f"  ABC distribution: {abc_counts}")
    print(f"  Lot-sizing mix:   {materials['lot_sizing'].value_counts().to_dict()}")
    print(f"  Demand profiles:  {profiles}")
    print(f"  History:          {HISTORY_START} → {SNAPSHOT_DATE} ({HISTORY_DAYS} days)")
    print(f"  Parts below safety stock at snapshot: {n_short}")
    print(f"  Stock value at snapshot: €{inv_value:,.0f}")
    print(f"  Output dir:       {out}")
    print("\nReady. Now run: python scripts/run_etl.py")


if __name__ == "__main__":
    main()
