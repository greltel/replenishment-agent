#!/usr/bin/env bash
# Replenishment Agent - every pilot result reported in the thesis, with one
# command (macOS / Linux). See run_pilot_thesis.bat for details.
#   ./run_pilot_thesis.sh      about 4 hours on ~50k materials (2 cores, ~8 GB RAM)
set -e
cd "$(dirname "$0")"
export DATA_RAW_DIR=data/pilot
export DATA_SOURCE=anonymized
load_dataset_env() {
  [ -f data/pilot/dataset.env ] || return 0
  while IFS='=' read -r key value || [ -n "$key" ]; do
    key=${key%$'\r'}
    case "$key" in ''|\#*) continue ;; esac
    export "$key=${value%$'\r'}"
  done < data/pilot/dataset.env
}
load_dataset_env
if [ ! -f .venv/bin/activate ]; then
  echo "[!] No virtual environment found - creating .venv and installing requirements (once) ..."
  python3 -m venv .venv
fi
source .venv/bin/activate
python -c "import sqlalchemy, pandas, numpy, scipy, streamlit, plotly" 2>/dev/null || pip install -r requirements.txt
[ -f data/pilot/MARA_export.csv ] || { echo "[X] data/pilot/MARA_export.csv not found"; exit 1; }
echo "Dataset settings: AS_OF_DATE=$AS_OF_DATE GR_MOVEMENT_TYPES=$GR_MOVEMENT_TYPES DEMAND_MOVEMENT_TYPES=$DEMAND_MOVEMENT_TYPES STOCK_COLUMNS=$STOCK_COLUMNS MATERIAL_SCOPE=$MATERIAL_SCOPE DEMAND_POLICY=$DEMAND_POLICY SERVICE_LEVEL_BY_ABC=${SERVICE_LEVEL_BY_ABC:-}"

# A. The pilot policy of dataset.env (as run_all_pilot.sh) ------------------
export DATA_ANONYMIZED_DIR=data/anonymized
export DATABASE_URL=sqlite:///replenishment_pilot.db
export REPORTS_DIR=reports/pilot
rm -rf "$REPORTS_DIR" && mkdir -p "$REPORTS_DIR"
echo "[1/10] Anonymizing the SAP exports ..."
python -m src.data_layer.anonymization
echo "[2/10] Loading data into SQLite (replenishment_pilot.db) ..."
python scripts/run_etl.py
echo "[3/10] Running the agent on the as-of date ..."
python scripts/run_agent.py
python scripts/pilot_agent_summary.py --out "$REPORTS_DIR/agent_summary.csv"
# the same agent with 98 % for every material (in memory, nothing persisted)
python scripts/pilot_agent_summary.py --levels uniform --out "$REPORTS_DIR/agent_summary_uniform.csv"
echo "[4/10] Backtest As-Is vs To-Be (60 days, realistic) ..."
python scripts/run_validation.py --out "$REPORTS_DIR/validation_report.csv"
echo "[5/10] Forecast accuracy per demand pattern (walk-forward) ..."
python scripts/run_forecast_eval.py --out "$REPORTS_DIR/forecast_report.csv"
echo "[6/10] Target service levels per ABC class (4 backtests, 2 at a time) ..."
python scripts/run_service_level_grid.py --jobs 2 --out "$REPORTS_DIR/service_level_grid.csv"
echo "[7/10] Backtest in every 60-day window with a full year of history (2 at a time) ..."
python scripts/run_pilot_windows.py --jobs 2 --out "$REPORTS_DIR/pilot_windows.csv"

# B. The thesis policy (legacy), same data and same evaluation --------------
# Own anonymized folder, database and reports: nothing of A is touched.
export DEMAND_POLICY=legacy SERVICE_LEVEL_BY_ABC=uniform
export DATA_ANONYMIZED_DIR=data/anonymized/legacy
export DATABASE_URL=sqlite:///replenishment_pilot_legacy.db
export REPORTS_DIR=reports/pilot/legacy
mkdir -p "$REPORTS_DIR"
echo "[8/10] Legacy policy: anonymizing and loading ..."
python -m src.data_layer.anonymization
python scripts/run_etl.py
echo "[9/10] Legacy policy: agent on the as-of date ..."
python scripts/run_agent.py
python scripts/pilot_agent_summary.py --out "$REPORTS_DIR/agent_summary.csv"
echo "[10/10] Legacy policy: backtest, evaluated per demand pattern as A ..."
python scripts/run_validation.py --by-pattern --out "$REPORTS_DIR/validation_report.csv"

echo "Done. Reports: reports/pilot (pilot policy) and reports/pilot/legacy (thesis policy)."
echo "What each file holds: README.md, section on run_pilot_thesis."
