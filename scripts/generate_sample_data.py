"""
Generate realistic sample/mock data for testing the agent without real SAP exports.

Creates ~150 materials with mixed ABC classes, varied lot sizing policies,
realistic stock levels, open POs, and 12 months of consumption history.

Usage:
    python scripts/generate_sample_data.py
"""
from __future__ import annotations

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
random.seed(42)
np.random.seed(42)


# ============================================================
# Configuration
# ============================================================
N_MATERIALS = 150
N_PLANTS = 1
HISTORY_DAYS = 365
SNAPSHOT_DATE = date.today() - timedelta(days=1)


# ============================================================
# Helpers
# ============================================================
def _rand_choice_weighted(values, weights):
    return random.choices(values, weights=weights, k=1)[0]


# ============================================================
# Materials
# ============================================================
def generate_materials() -> pd.DataFrame:
    """~150 materials with realistic distribution."""
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

        # Lot sizing policy mix
        lot_sizing = _rand_choice_weighted(
            ["LFL", "EOQ", "FOQ", "POQ"],
            [0.40, 0.30, 0.20, 0.10],
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

        # Safety stock and MOQ
        safety = round(random.uniform(20, 200), 0)
        moq = random.choice([10, 25, 50, 100])
        fixed_lot = moq * random.choice([1, 2, 5]) if lot_sizing == "FOQ" else 0

        rows.append({
            "material_id":           material_id,
            "material_type":         mtype,
            "uom":                   random.choice(["KG", "PCS", "L"]),
            "abc_class":             abc,
            "mrp_type":              "PD",
            "lot_sizing":            lot_sizing,
            "lead_time_days":        lead_time,
            "safety_stock":          safety,
            "reorder_point":         safety * 1.5,
            "moq":                   moq,
            "fixed_lot_size":        fixed_lot,
            "standard_cost":         cost,
            "preferred_supplier_id": f"SUP{random.randint(1, 30):03d}",
        })

    return pd.DataFrame(rows)


# ============================================================
# Stock snapshot
# ============================================================
def generate_stock(materials: pd.DataFrame) -> pd.DataFrame:
    """One snapshot row per (material, plant) on SNAPSHOT_DATE."""
    rows = []
    for _, mat in materials.iterrows():
        # Quantity: mix of low/normal/high stock relative to safety stock
        regime = _rand_choice_weighted(
            ["critical", "low", "normal", "high"],
            [0.10, 0.20, 0.50, 0.20],
        )
        ss = mat["safety_stock"]
        if regime == "critical":
            qty = round(random.uniform(0, ss * 0.5))
        elif regime == "low":
            qty = round(random.uniform(ss * 0.5, ss))
        elif regime == "normal":
            qty = round(random.uniform(ss, ss * 3))
        else:
            qty = round(random.uniform(ss * 3, ss * 6))

        rows.append({
            "material_id":   mat["material_id"],
            "plant":         "P001",
            "location":      "L01",
            "quantity":      qty,
            "snapshot_date": SNAPSHOT_DATE,
        })
    return pd.DataFrame(rows)


# ============================================================
# Open POs
# ============================================================
def generate_purchase_orders(materials: pd.DataFrame) -> pd.DataFrame:
    """Open POs for ~40% of materials, expected within next 60 days."""
    rows = []
    po_counter = 1
    for _, mat in materials.iterrows():
        if random.random() < 0.40:
            n_pos = random.randint(1, 3)
            for _ in range(n_pos):
                expected_offset = random.randint(1, 60)
                qty = max(mat["moq"], round(random.uniform(50, 500)))
                rows.append({
                    "po_number":     f"PO{po_counter:06d}",
                    "material_id":   mat["material_id"],
                    "supplier_id":   mat["preferred_supplier_id"],
                    "quantity":      qty,
                    "expected_date": SNAPSHOT_DATE + timedelta(days=expected_offset),
                    "status":        "OPEN",
                })
                po_counter += 1
    return pd.DataFrame(rows)


# ============================================================
# Movements (consumption history)
# ============================================================
def generate_movements(materials: pd.DataFrame) -> pd.DataFrame:
    """12 months of consumption (261) + goods receipts (101) movements."""
    rows = []
    for _, mat in materials.iterrows():
        # Daily mean consumption based on safety stock (heuristic)
        daily_mean = max(1, mat["safety_stock"] / 20)

        # Some materials are inactive (last consumption > 180 days ago)
        is_inactive = random.random() < 0.05

        # ----- Consumption movements (261) -----
        for d_offset in range(HISTORY_DAYS):
            posting_date = SNAPSHOT_DATE - timedelta(days=HISTORY_DAYS - d_offset)

            if is_inactive and (SNAPSHOT_DATE - posting_date).days < 180:
                continue  # no movements in last 180 days

            # Not every day has a movement
            if random.random() > 0.40:
                continue

            qty = max(1, int(np.random.normal(daily_mean, daily_mean * 0.3)))
            rows.append({
                "material_id":   mat["material_id"],
                "plant":         "P001",
                "movement_type": "261",
                "quantity":      -qty,  # negative for consumption
                "posting_date":  posting_date,
            })

        # ----- Goods receipts (101) - simulating existing replenishment -----
        if is_inactive:
            continue
        # Roughly one receipt every ~30 days (existing process is reactive)
        n_receipts = HISTORY_DAYS // random.randint(25, 45)
        for _ in range(n_receipts):
            d_offset = random.randint(7, HISTORY_DAYS)
            posting_date = SNAPSHOT_DATE - timedelta(days=d_offset)
            # Receipt size ~ 30 days of consumption (typical existing batch)
            receipt_qty = max(int(daily_mean * random.uniform(20, 40)), int(mat["moq"]))
            rows.append({
                "material_id":   mat["material_id"],
                "plant":         "P001",
                "movement_type": "101",
                "quantity":      receipt_qty,  # positive for receipt
                "posting_date":  posting_date,
            })

    return pd.DataFrame(rows)


# ============================================================
# Main
# ============================================================
def main():
    out = config.data_samples_dir
    out.mkdir(parents=True, exist_ok=True)

    print("Generating sample data...")

    materials = generate_materials()
    materials.to_csv(out / "materials.csv", index=False)
    print(f"  materials.csv         {len(materials):>5} rows")

    stock = generate_stock(materials)
    stock.to_csv(out / "stock.csv", index=False)
    print(f"  stock.csv             {len(stock):>5} rows")

    pos = generate_purchase_orders(materials)
    pos.to_csv(out / "purchase_orders.csv", index=False)
    print(f"  purchase_orders.csv   {len(pos):>5} rows")

    mvts = generate_movements(materials)
    mvts.to_csv(out / "movements.csv", index=False)
    print(f"  movements.csv         {len(mvts):>5} rows")

    # Summary
    abc_counts = materials["abc_class"].value_counts().to_dict()
    print(f"\nSummary:")
    print(f"  ABC distribution: {abc_counts}")
    print(f"  Lot-sizing mix:   {materials['lot_sizing'].value_counts().to_dict()}")
    print(f"  Output dir:       {out}")
    print(f"\nReady. Now run: python scripts/run_etl.py")


if __name__ == "__main__":
    main()
