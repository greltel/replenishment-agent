"""
ETL pipeline — loads CSVs into SQLite.

Source priority:
  1. data/anonymized/  (real, anonymized SAP exports)
  2. data/samples/     (mock data for testing)
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from src.config import config
from src.data_layer.models import (
    Material, Stock, PurchaseOrder, Movement, DemandForecast
)
from src.data_layer.repository import Repository
from src.data_layer.sap_parsers import parse_sap_number, parse_sap_int
from src.utils.logger import log


# Expected CSV files (these column names are the contract!)
EXPECTED_FILES = {
    "materials": [
        "material_id", "material_type", "uom", "abc_class", "mrp_type",
        "lot_sizing", "lead_time_days", "safety_stock", "reorder_point",
        "moq", "fixed_lot_size", "standard_cost", "preferred_supplier_id",
    ],
    "stock": [
        "material_id", "plant", "location", "quantity", "snapshot_date",
    ],
    "purchase_orders": [
        "po_number", "material_id", "supplier_id", "quantity",
        "expected_date", "status",
    ],
    "movements": [
        "material_id", "plant", "movement_type", "quantity", "posting_date",
    ],
}


def _resolve_data_dir() -> Path:
    """Return whichever data dir has the most CSV files, preferring anonymized."""
    anon = config.data_anonymized_dir
    samp = config.data_samples_dir

    n_anon = len(list(anon.glob("*.csv")))
    n_samp = len(list(samp.glob("*.csv")))

    if n_anon >= 4:
        log.info(f"Using anonymized data from {anon}")
        return anon
    elif n_samp >= 4:
        log.info(f"Using sample data from {samp}")
        return samp
    else:
        raise FileNotFoundError(
            f"No CSV data found. Expected at least 4 CSVs in either "
            f"{anon} or {samp}. Run scripts/generate_sample_data.py first."
        )


def load_materials(data_dir: Path, repo: Repository) -> int:
    df = pd.read_csv(data_dir / "materials.csv")
    df = df.dropna(subset=["material_id"])

    # Defaults for any missing optional columns
    defaults = {
        "material_type": "ROH", "uom": "PCS", "abc_class": "C",
        "mrp_type": "PD", "lot_sizing": "LFL", "lead_time_days": 7,
        "safety_stock": 0.0, "reorder_point": 0.0, "moq": 1.0,
        "fixed_lot_size": 0.0, "standard_cost": 0.0,
        "preferred_supplier_id": None,
    }
    for col, val in defaults.items():
        if col not in df.columns:
            df[col] = val

    objects = []
    for _, row in df.iterrows():
        objects.append(Material(
            material_id=str(row["material_id"]),
            description=str(row.get("description", "") or "")[:80],
            material_type=row.get("material_type"),
            uom=row.get("uom"),
            abc_class=row.get("abc_class"),
            mrp_type=row.get("mrp_type"),
            lot_sizing=row.get("lot_sizing"),
            lead_time_days=parse_sap_int(row.get("lead_time_days", 7), default=7),
            safety_stock=parse_sap_number(row.get("safety_stock", 0)),
            reorder_point=parse_sap_number(row.get("reorder_point", 0)),
            moq=parse_sap_number(row.get("moq", 1), default=1),
            fixed_lot_size=parse_sap_number(row.get("fixed_lot_size", 0)),
            standard_cost=parse_sap_number(row.get("standard_cost", 0)),
            preferred_supplier_id=row.get("preferred_supplier_id"),
        ))

    repo.session.add_all(objects)
    repo.commit()
    log.info(f"Loaded {len(objects)} materials")
    return len(objects)


def load_stock(data_dir: Path, repo: Repository) -> int:
    df = pd.read_csv(data_dir / "stock.csv", parse_dates=["snapshot_date"])

    objects = []
    for _, row in df.iterrows():
        qty = parse_sap_number(row["quantity"])
        if qty < 0:    # drop negative stock
            continue
        objects.append(Stock(
            material_id=str(row["material_id"]),
            plant=str(row.get("plant", "P001")),
            location=str(row.get("location", "L01")),
            quantity=qty,
            snapshot_date=row["snapshot_date"].date(),
        ))
    repo.session.add_all(objects)
    repo.commit()
    log.info(f"Loaded {len(objects)} stock records")
    return len(objects)


def load_purchase_orders(data_dir: Path, repo: Repository) -> int:
    path = data_dir / "purchase_orders.csv"
    if not path.exists():
        log.warning("purchase_orders.csv not found, skipping")
        return 0

    df = pd.read_csv(path, parse_dates=["expected_date"])

    objects = [
        PurchaseOrder(
            po_number=str(row["po_number"]),
            material_id=str(row["material_id"]),
            supplier_id=str(row.get("supplier_id", "SUP000")),
            quantity=parse_sap_number(row["quantity"]),
            expected_date=row["expected_date"].date(),
            status=str(row.get("status", "OPEN")),
        )
        for _, row in df.iterrows()
    ]
    repo.session.add_all(objects)
    repo.commit()
    log.info(f"Loaded {len(objects)} purchase orders")
    return len(objects)


def load_movements(data_dir: Path, repo: Repository) -> int:
    path = data_dir / "movements.csv"
    if not path.exists():
        log.warning("movements.csv not found, skipping")
        return 0

    df = pd.read_csv(path, parse_dates=["posting_date"])

    objects = [
        Movement(
            material_id=str(row["material_id"]),
            plant=str(row.get("plant", "P001")),
            movement_type=str(row.get("movement_type", "261")),
            quantity=parse_sap_number(row["quantity"]),
            posting_date=row["posting_date"].date(),
        )
        for _, row in df.iterrows()
    ]
    repo.session.add_all(objects)
    repo.commit()
    log.info(f"Loaded {len(objects)} movements")
    return len(objects)


def load_demand_forecast(data_dir: Path, repo: Repository) -> int:
    path = data_dir / "demand_forecast.csv"
    if not path.exists():
        log.info("demand_forecast.csv not provided (optional)")
        return 0

    df = pd.read_csv(path, parse_dates=["period"])
    objects = [
        DemandForecast(
            material_id=str(row["material_id"]),
            period=row["period"].date(),
            quantity=parse_sap_number(row["quantity"]),
            source=str(row.get("source", "manual")),
        )
        for _, row in df.iterrows()
    ]
    repo.session.add_all(objects)
    repo.commit()
    log.info(f"Loaded {len(objects)} forecast records")
    return len(objects)


def run_etl(drop_existing: bool = True,
            data_dir: Optional[Path] = None) -> dict:
    """Run full ETL pipeline. Returns counts per table."""
    log.info("=== ETL Pipeline ===")

    if data_dir is None:
        data_dir = _resolve_data_dir()

    repo = Repository()
    repo.init_schema(drop_existing=drop_existing)

    counts = {
        "materials":       load_materials(data_dir, repo),
        "stock":           load_stock(data_dir, repo),
        "purchase_orders": load_purchase_orders(data_dir, repo),
        "movements":       load_movements(data_dir, repo),
        "forecast":        load_demand_forecast(data_dir, repo),
    }
    repo.close()

    log.success("ETL complete!")
    return counts


if __name__ == "__main__":
    run_etl()
