"""
Central configuration for the replenishment agent.
Loads from environment variables with sensible defaults.
"""
from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass

# Load .env if exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# Project root (parent of src/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    """Application configuration."""

    # Database
    database_url: str = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{PROJECT_ROOT / 'replenishment.db'}",
    )

    # Data paths
    data_raw_dir: Path = PROJECT_ROOT / os.getenv("DATA_RAW_DIR", "data/raw")
    data_anonymized_dir: Path = PROJECT_ROOT / os.getenv(
        "DATA_ANONYMIZED_DIR", "data/anonymized"
    )
    data_samples_dir: Path = PROJECT_ROOT / os.getenv(
        "DATA_SAMPLES_DIR", "data/samples"
    )
    # Which prepared dataset the ETL loads: 'samples', 'anonymized', or
    # 'auto' (anonymized if it holds the CSVs, otherwise samples).
    data_source: str = os.getenv("DATA_SOURCE", "auto")
    # Folder of the evaluation reports read by the dashboard. The default
    # (project root) keeps the sample-data reports where they always were;
    # run_all_pilot.bat uses reports/pilot so the two datasets never mix.
    reports_dir: Path = PROJECT_ROOT / os.getenv("REPORTS_DIR", ".")

    # Agent / planning
    planning_horizon_days: int = int(os.getenv("PLANNING_HORIZON_DAYS", "60"))
    default_holding_rate: float = float(os.getenv("DEFAULT_HOLDING_RATE", "0.20"))
    default_ordering_cost: float = float(os.getenv("DEFAULT_ORDERING_COST", "50.0"))
    default_service_level: float = float(os.getenv("DEFAULT_SERVICE_LEVEL", "0.98"))
    # Target service level per ABC class, e.g. "A=0.98,B=0.95,C=0.90"
    # (src/mrp/service_level.py). Empty or "uniform" = 98 % for every material.
    service_level_by_abc: str = os.getenv("SERVICE_LEVEL_BY_ABC", "").strip()

    # Rule thresholds
    dead_stock_threshold_days: int = int(os.getenv("DEAD_STOCK_THRESHOLD_DAYS", "365"))

    # Movement types that are goods receipts in the backtest: the As-Is
    # purchase receipts and the in-transit orders the To-Be run inherits.
    # Comma-separated, e.g. GR_MOVEMENT_TYPES=101,105 for a company that
    # receives into GR blocked stock (103) and releases with 105.
    goods_receipt_movement_types: tuple[str, ...] = tuple(
        t.strip() for t in os.getenv("GR_MOVEMENT_TYPES", "101").split(",") if t.strip()
    )

    # Movement types that are DEMAND (goods issues to customers or to
    # consumption) — see models.CONSUMPTION_MOVEMENT_TYPES. Comma-separated;
    # a company's own issue types (e.g. 9xx) can be added per dataset.
    demand_movement_types: tuple[str, ...] = tuple(
        t.strip() for t in os.getenv(
            "DEMAND_MOVEMENT_TYPES", "601,251,261,201,281").split(",") if t.strip()
    )

    # MARD stock types that make up the stock on hand (summed per line):
    # LABST unrestricted, UMLME in transfer, INSME quality inspection, EINME
    # restricted, SPEME blocked, RETME blocked returns. Default unrestricted
    # only; a dataset whose receipts pass through blocked stock needs SPEME
    # (see anonymization._stock_quantity).
    stock_columns: tuple[str, ...] = tuple(
        t.strip().upper() for t in os.getenv("STOCK_COLUMNS", "LABST").split(",") if t.strip()
    )

    # Replenishment policy: 'legacy' (every material as continuous demand —
    # the thesis evaluation on the sample data) or 'pattern' (forecast,
    # safety stock and expedite per demand pattern: smooth / erratic /
    # intermittent / lumpy / rare — src/mrp/demand_pattern.py).
    demand_policy: str = os.getenv("DEMAND_POLICY", "legacy").strip().lower()

    # Materials kept by the anonymization: 'all', or 'active' = with a
    # movement, stock or an open purchase order (large SAP catalogues).
    material_scope: str = os.getenv("MATERIAL_SCOPE", "all")

    # Materials left out of the dataset by the anonymization, e.g. parts of
    # another business that share the material type: material groups
    # (MARA-MATKL) and material numbers (MATNR), comma-separated. Empty =
    # none (the default).
    exclude_material_groups: tuple[str, ...] = tuple(
        t.strip().upper() for t in os.getenv("EXCLUDE_MATERIAL_GROUPS", "").split(",") if t.strip()
    )
    exclude_materials: tuple[str, ...] = tuple(
        t.strip() for t in os.getenv("EXCLUDE_MATERIALS", "").split(",") if t.strip()
    )

    # As-of date — used to anchor "today" relative to the dataset.
    # Useful for: (a) backtest in historical data, (b) static datasets where
    # the most recent movement is older than the real "today".
    # Format: 'YYYY-MM-DD' or 'auto' (use latest movement date in the data).
    # Empty = use today's real date.
    as_of_date: str = os.getenv("AS_OF_DATE", "auto")

    # Logging
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    log_dir: Path = PROJECT_ROOT / os.getenv("LOG_DIR", "logs")

    def ensure_directories(self) -> None:
        """Create directories that should exist."""
        for d in [
            self.data_raw_dir,
            self.data_anonymized_dir,
            self.data_samples_dir,
            self.log_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)


# Singleton instance
config = Config()
config.ensure_directories()
