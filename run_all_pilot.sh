#!/usr/bin/env bash
# Replenishment Agent - pipeline on the REAL pilot data (macOS / Linux).
# See run_all_pilot.bat for details.
#   ./run_all_pilot.sh          agent + 60-day backtest
#   ./run_all_pilot.sh --full   + scenarios, sensitivity, bootstrap, ablation, forecast
set -e
cd "$(dirname "$0")"
export DATA_RAW_DIR=data/pilot
export DATA_SOURCE=anonymized
export DATABASE_URL=sqlite:///replenishment_pilot.db
export REPORTS_DIR=reports/pilot
# Settings of this dataset (as-of date, movement types, stock types, material
# scope): data/pilot/dataset.env, one KEY=value per line (CR of a Windows
# checkout removed)
load_dataset_env() {
  [ -f data/pilot/dataset.env ] || return 0
  while IFS='=' read -r key value || [ -n "$key" ]; do
    key=${key%$'\r'}
    case "$key" in ''|\#*) continue ;; esac
    export "$key=${value%$'\r'}"
  done < data/pilot/dataset.env
}
load_dataset_env
echo "Dataset settings: AS_OF_DATE=$AS_OF_DATE GR_MOVEMENT_TYPES=$GR_MOVEMENT_TYPES DEMAND_MOVEMENT_TYPES=$DEMAND_MOVEMENT_TYPES STOCK_COLUMNS=$STOCK_COLUMNS MATERIAL_SCOPE=$MATERIAL_SCOPE DEMAND_POLICY=$DEMAND_POLICY SERVICE_LEVEL_BY_ABC=${SERVICE_LEVEL_BY_ABC:-}"
if [ ! -f .venv/bin/activate ]; then
  echo "[!] No virtual environment found - creating .venv and installing requirements (once) ..."
  python3 -m venv .venv
fi
source .venv/bin/activate
python -c "import sqlalchemy, pandas, numpy, scipy, streamlit, plotly" 2>/dev/null || pip install -r requirements.txt
[ -f data/pilot/MARA_export.csv ] || { echo "[X] data/pilot/MARA_export.csv not found"; exit 1; }
rm -rf "$REPORTS_DIR" && mkdir -p "$REPORTS_DIR"
python -m src.data_layer.anonymization
python scripts/run_etl.py
python scripts/run_agent.py
python scripts/run_validation.py --out "$REPORTS_DIR/validation_report.csv"
if [ "$1" = "--full" ]; then
  python scripts/run_validation.py --all-scenarios --out "$REPORTS_DIR/validation_report.csv"
  python scripts/run_validation.py --sensitivity --out "$REPORTS_DIR/validation_report.csv"
  python scripts/run_bootstrap.py --out "$REPORTS_DIR/bootstrap_report.csv"
  python scripts/run_rule_ablation.py --stress-test --out "$REPORTS_DIR/ablation_report.csv"
  python scripts/run_forecast_eval.py --out "$REPORTS_DIR/forecast_report.csv"
fi
echo "Done (pilot data). Start the dashboard with:"
echo "  DATASET=pilot DATABASE_URL=sqlite:///replenishment_pilot.db REPORTS_DIR=reports/pilot AS_OF_DATE=$AS_OF_DATE DEMAND_MOVEMENT_TYPES=$DEMAND_MOVEMENT_TYPES DEMAND_POLICY=$DEMAND_POLICY streamlit run dashboard/app.py --server.port 8502"
