#!/usr/bin/env bash
# Replenishment Agent - full pipeline (macOS / Linux). See run_all.bat for details.
set -e
cd "$(dirname "$0")"
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
echo "Done. Start the dashboard with: streamlit run dashboard/app.py"
