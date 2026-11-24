#!/usr/bin/env bash
# Replenishment Agent - full pipeline on the SAMPLE data (macOS / Linux).
# See run_all.bat for details. Real pilot data: ./run_all_pilot.sh
set -e
cd "$(dirname "$0")"
export DATA_SOURCE=samples
unset DATABASE_URL REPORTS_DIR
export GR_MOVEMENT_TYPES=101   # sample data receive with 101 (.env value is for pilot data)
# Default settings for the sample data (.env / data/pilot/dataset.env are for the pilot)
export DEMAND_MOVEMENT_TYPES=601,251,261,201,281 STOCK_COLUMNS=LABST MATERIAL_SCOPE=all AS_OF_DATE=auto
export DEMAND_POLICY=legacy
export SERVICE_LEVEL_BY_ABC=uniform   # 98 % for every material (thesis results)
if [ ! -f .venv/bin/activate ]; then
  echo "[!] No virtual environment found - creating .venv and installing requirements (once) ..."
  python3 -m venv .venv
fi
source .venv/bin/activate
python -c "import sqlalchemy, pandas, numpy, scipy, streamlit, plotly" 2>/dev/null || pip install -r requirements.txt
if [ "$1" != "--keep-data" ]; then python scripts/generate_sample_data.py; fi
python scripts/run_etl.py
python scripts/run_agent.py
python scripts/run_validation.py
python scripts/run_validation.py --all-scenarios
python scripts/run_validation.py --sensitivity
python scripts/run_bootstrap.py
python scripts/run_rule_ablation.py --stress-test
python scripts/run_forecast_eval.py
echo "Done. Start the dashboard with: DATASET=samples streamlit run dashboard/app.py"
