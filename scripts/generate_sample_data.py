"""
Generate realistic sample/mock data for testing the agent without real SAP exports.

Creates ~150 materials with mixed ABC classes, varied lot sizing policies,
12 months of consumption history, the goods receipts of a simulated
"human planner" (the As-Is process), a consistent stock snapshot and the
open purchase orders that are still in transit at the snapshot date.

Design goals (so that a demo tells the same story as the thesis):
  • The dataset is INTERNALLY CONSISTENT: the stock snapshot equals the
    opening stock + all receipts − all consumption, and the open POs are
    exactly the planner's orders that had not arrived by the snapshot date.
  • Safety stock follows the same formula the agent uses
    (SS = z × σ_daily × √LT, z = 2.054 for a 98 % service level), so the
    master data is "reasonable" rather than arbitrary.
  • The As-Is planner is imperfect in the ways §1.2 of the thesis describes:
    reviews happen weekly and are sometimes skipped, orders are placed late,
    batches are large ("order a month's worth"), and A-class items are
    occasionally over-ordered "to be safe". This yields both stockouts and
    overstock — the two costs the agent is meant to reduce.
  • Demand has a weekly pattern (little consumption at weekends), a few
    materials have a seasonal peak, ~5 % are inactive (no consumption in the
    last 180 days → dead-stock candidates) and ~4 % are new (short history).

Everything is deterministic (seed 42).

Usage:
    python scripts/generate_sample_data.py
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
INACTIVE_SHARE = 0.05        # materials with no consumption in the last 180 days
NEW_ITEM_SHARE = 0.04        # materials that only exist for the last ~75 days
SEASONAL_SHARE = 0.15        # materials with a demand peak in one quarter


# ============================================================
# Helpers
# ============================================================
def _rand_choice_weighted(values, weights):
    return random.choices(values, weights=weights, k=1)[0]


# ============================================================
# Description templates per material type
# ============================================================
# Realistic-looking descriptions for mock SAP data.
DESCRIPTION_TEMPLATES = {
    "ROH": {  # Raw materials
        "prefixes": ["Steel", "Aluminum", "Copper", "Brass", "Plastic", "Rubber",
                     "Stainless", "Carbon", "Polyamide", "PVC", "Polypropylene"],
        "items":    ["sheet", "rod", "tube", "wire", "bar", "plate", "ring",
                     "pellet", "powder", "granulate"],
        "specs":    ["2mm", "5mm", "10mm", "20mm", "Ø8", "Ø12", "Ø25", "1.5kg",
                     "grade A", "grade B", "premium", "industrial"],
    },
    "HALB": {  # Semi-finished
        "prefixes": ["Machined", "Welded", "Painted", "Heat-treated", "Coated",
                     "Assembled", "Pre-form", "Cut"],
        "items":    ["bracket", "shaft", "housing", "frame", "plate", "flange",
                     "spacer", "fitting", "subassembly", "module"],
        "specs":    ["v1", "v2", "rev A", "rev B", "type 1", "type 2",
                     "left", "right", "upper", "lower", "small", "medium", "large"],
    },
    "FERT": {  # Finished
        "prefixes": ["Industrial", "Heavy-duty", "Standard", "Premium", "Compact",
                     "Modular", "Universal", "Professional", "Smart"],
        "items":    ["pump", "motor", "valve", "gearbox", "controller", "sensor",
                     "actuator", "drive", "compressor", "regulator", "filter unit"],
        "specs":    ["220V", "380V", "12V", "24V", "Class A", "Class B", "IP65",
                     "IP67", "1HP", "2HP", "5HP", "10kW"],
    },
    "VERP": {  # Packaging
        "prefixes": ["Cardboard", "Wooden", "Plastic", "Foam", "Bubble", "Pallet"],
        "items":    ["box", "crate", "pallet", "wrap", "label", "tape", "insert"],
        "specs":    ["small", "medium", "large", "EUR1", "EUR2", "60x40x40",
                     "120x80x100"],
    },
}


def _generate_description(material_type: str) -> str:
    """Build a realistic-looking description like 'Steel rod Ø12 grade A'."""
    template = DESCRIPTION_TEMPLATES.get(material_type, DESCRIPTION_TEMPLATES["ROH"])
    prefix = random.choice(template["prefixes"])
    item = random.choice(template["items"])
    spec = random.choice(template["specs"])
    return f"{prefix} {item} {spec}"


# ============================================================
# Materials
# ============================================================
def generate_materials() -> pd.DataFrame:
    """~150 materials with realistic distribution.

    Besides the SAP-like master data, a few hidden "demand process"
    parameters are attached (columns starting with `_`) — they drive the
    movement simulation and are dropped before writing materials.csv.
    """
    rows = []
    for i in range(1, N_MATERIALS + 1):
        material_id = f"MAT{i:05d}"

        # ABC: 20% A, 30% B, 50% C
        abc = _rand_choice_weighted(["A", "B", "C"], [0.20, 0.30, 0.50])

        # Material type
        mtype = _rand_choice_weighted(
            ["ROH", "HALB", "FERT", "VERP"],
            [0.50, 0.20, 0.25, 0.05],
        )

        # Lead time depends on type
        if mtype == "ROH":
            lead_time = random.randint(5, 21)
        elif mtype == "HALB":
            lead_time = random.randint(3, 10)
        elif mtype == "FERT":
            lead_time = random.randint(7, 30)
        else:
            lead_time = random.randint(2, 7)

        # Cost depends on ABC class
        if abc == "A":
            cost = round(random.uniform(50, 500), 2)
        elif abc == "B":
            cost = round(random.uniform(10, 80), 2)
        else:
            cost = round(random.uniform(0.5, 20), 2)

        # ---- Hidden demand process (units per active day) ----
        # A items move more volume; C items are slow movers.
        if abc == "A":
            daily_mean = random.uniform(8, 40)
        elif abc == "B":
            daily_mean = random.uniform(4, 20)
        else:
            daily_mean = random.uniform(1, 10)
        active_prob = random.uniform(0.45, 0.85)       # share of weekdays with a movement
        cv = random.uniform(0.25, 0.9)                 # within-day variability
        # σ of DAILY demand (including zero days) for the SS formula
        p = active_prob * 5 / 7
        mean_daily = daily_mean * p
        var_daily = p * (daily_mean ** 2) * (1 + cv ** 2) - mean_daily ** 2
        sigma_daily = math.sqrt(max(var_daily, 0.0))

        # Safety stock = z × σ × √LT (same formula the agent's enrichment uses)
        safety = max(5.0, round(Z_98 * sigma_daily * math.sqrt(lead_time)))
        reorder_point = round(mean_daily * lead_time + safety)

        moq = random.choice([10, 25, 50, 100])

        # Lot-sizing policy, assigned with the same rule the agent's master-
        # data enrichment applies (thesis Table 4.3), using the coefficient
        # of variation of daily demand (CV ≈ within-day cv / share of active
        # days, because zero-demand days inflate the variability):
        #   CV > 1.0            → WW  (Wagner-Whitin, erratic demand)
        #   0.5 < CV ≤ 1.0      → POQ (period order quantity)
        #   CV ≤ 0.5            → EOQ (stable demand, cost known)
        #   packaging (VERP)    → FOQ (fixed crates / pallets)
        cv_daily = cv / p
        if mtype == "VERP":
            lot_sizing = "FOQ"
        elif cv_daily > 1.0:
            lot_sizing = "WW"
        elif cv_daily > 0.5:
            lot_sizing = "POQ"
        else:
            lot_sizing = "EOQ"
        fixed_lot = moq * random.choice([2, 4, 6]) if lot_sizing == "FOQ" else 0

        rows.append({
            "material_id":           material_id,
            "description":           _generate_description(mtype),
            "material_type":         mtype,
            "uom":                   random.choice(["KG", "PCS", "L"]),
            "abc_class":             abc,
            "mrp_type":              "PD",
            "lot_sizing":            lot_sizing,
            "lead_time_days":        lead_time,
            "safety_stock":          float(safety),
            "reorder_point":         float(reorder_point),
            "moq":                   moq,
            "fixed_lot_size":        fixed_lot,
            "standard_cost":         cost,
            "preferred_supplier_id": f"SUP{random.randint(1, 30):03d}",
            # hidden simulation parameters
            "_daily_mean":   daily_mean,
            "_active_prob":  active_prob,
            "_cv":           cv,
            "_mean_daily":   mean_daily,
            "_profile":      _rand_choice_weighted(
                ["normal", "inactive", "new", "seasonal"],
                [1 - INACTIVE_SHARE - NEW_ITEM_SHARE - SEASONAL_SHARE,
                 INACTIVE_SHARE, NEW_ITEM_SHARE, SEASONAL_SHARE]),
            "_peak_month":   random.randint(1, 12),
        })

    df = pd.DataFrame(rows)
    # A brand-new item has too little history for a CV-based choice → LFL
    df.loc[df["_profile"] == "new", "lot_sizing"] = "LFL"
    df.loc[df["_profile"] == "new", "fixed_lot_size"] = 0
    return df


# ============================================================
# Demand + As-Is planner simulation
# ============================================================
def _daily_demand(mat: pd.Series, d: date, first_day: date | None) -> float:
    """Demand of material `mat` on day `d` (0 if none)."""
    profile = mat["_profile"]
    if profile == "inactive" and (SNAPSHOT_DATE - d).days < 180:
        return 0.0                     # nothing consumed in the last 6 months
    if profile == "new" and first_day is not None and d < first_day:
        return 0.0                     # item did not exist yet

    # Weekly pattern: factories consume little at weekends
    if d.weekday() >= 5:
        prob = mat["_active_prob"] * 0.15
    else:
        prob = mat["_active_prob"]
    if random.random() > prob:
        return 0.0

    mean = mat["_daily_mean"]
    if profile == "seasonal" and d.month == mat["_peak_month"]:
        mean *= 2.2                    # seasonal peak
    qty = np.random.normal(mean, mean * mat["_cv"])
    return float(max(1, int(round(qty))))


def simulate_history(materials: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Simulate 12 months of consumption (261) and the As-Is planner's
    goods receipts (101). Returns (movements, stock_snapshot, open_pos)."""
    movement_rows = []
    stock_rows = []
    po_rows = []
    po_counter = 1

    for _, mat in materials.iterrows():
        mid = mat["material_id"]
        lt = int(mat["lead_time_days"])
        ss = float(mat["safety_stock"])
        rop = float(mat["reorder_point"])
        mean_daily = float(mat["_mean_daily"])
        profile = mat["_profile"]

        first_day = None
        if profile == "new":
            first_day = SNAPSHOT_DATE - timedelta(days=random.randint(60, 90))

        # Opening stock at the start of the history
        stock = rop + random.uniform(0.5, 2.0) * max(mean_daily * 30, 1)
        if profile == "inactive":
            stock *= 2.5               # the classic overstocked dead item
        pending: list[tuple[date, float]] = []   # (arrival_date, qty)

        # Human planner characteristics for this material (thesis §1.2):
        # cheap C items are ordered in big batches ("it's cheap, take a lot"),
        # A items are watched more closely but still suffer from late
        # reactions; a share of items is simply neglected.
        abc = mat["abc_class"]
        review_weekday = random.randint(0, 4)
        neglected = random.random() < 0.20
        skip_prob = 0.35 if neglected else 0.10        # forgets the weekly review
        delay_days = random.randint(0, 7)              # reacts late once ROP is crossed
        batch_days = {"A": random.uniform(35, 70),     # orders this many days of demand
                      "B": random.uniform(60, 110),
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
                        "material_id": mid, "plant": "P001",
                        "movement_type": "101", "quantity": qty,
                        "posting_date": arrival,
                    })
                else:
                    still.append((arrival, qty))
            pending = still

            # 2. consumption
            demand = _daily_demand(mat, d, first_day)
            if demand > 0:
                consumed = min(demand, stock)       # lost sales if short
                if consumed > 0:
                    stock -= consumed
                    movement_rows.append({
                        "material_id": mid, "plant": "P001",
                        "movement_type": "261", "quantity": -consumed,
                        "posting_date": d,
                    })

            # 3. the human planner
            if profile == "inactive" and (SNAPSHOT_DATE - d).days < 180:
                continue                # nobody orders a dead item
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
                qty = max(mean_daily * batch_days, float(mat["moq"]))
                if random.random() < over_order_prob:
                    qty *= 2.0          # "to be safe"
                qty = float(math.ceil(qty / mat["moq"]) * mat["moq"])
                arrival = d + timedelta(days=lt + random.choice([0, 0, 0, 2, 5]))
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
            "plant":         "P001",
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

    print(f"Generating sample data (seed {args.seed}, snapshot {SNAPSHOT_DATE})...")

    materials = generate_materials()
    mvts, stock, pos = simulate_history(materials)

    public_cols = [c for c in materials.columns if not c.startswith("_")]
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
    n_short = int((stock["quantity"] < materials["safety_stock"]).sum())
    print(f"\nSummary:")
    print(f"  ABC distribution: {abc_counts}")
    print(f"  Lot-sizing mix:   {materials['lot_sizing'].value_counts().to_dict()}")
    print(f"  Demand profiles:  {profiles}")
    print(f"  History:          {HISTORY_START} → {SNAPSHOT_DATE} ({HISTORY_DAYS} days)")
    print(f"  Materials below safety stock at snapshot: {n_short}")
    print(f"  Output dir:       {out}")
    print(f"\nReady. Now run: python scripts/run_etl.py")


if __name__ == "__main__":
    main()
