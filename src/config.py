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

    # Agent / planning
    planning_horizon_days: int = int(os.getenv("PLANNING_HORIZON_DAYS", "60"))
    default_holding_rate: float = float(os.getenv("DEFAULT_HOLDING_RATE", "0.20"))
    default_ordering_cost: float = float(os.getenv("DEFAULT_ORDERING_COST", "50.0"))
    default_service_level: float = float(os.getenv("DEFAULT_SERVICE_LEVEL", "0.98"))

    # Rule thresholds
    dead_stock_threshold_days: int = int(os.getenv("DEAD_STOCK_THRESHOLD_DAYS", "365"))

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
