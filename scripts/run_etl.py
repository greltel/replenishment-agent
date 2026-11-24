"""Entry point: load data into SQLite."""
import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_layer.etl import run_etl


def main():
    counts = run_etl(drop_existing=True)

    print("\n=== ETL Summary ===")
    for table, n in counts.items():
        print(f"  {table:20s}  {n:>6} rows")

    if counts["materials"] > 0:
        print("\nNext: python scripts/run_agent.py")
    else:
        print("\nERROR: No materials loaded. Check your data files.")


if __name__ == "__main__":
    main()
