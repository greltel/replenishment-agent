@echo off
REM Starts the Streamlit dashboard on the SAMPLE data: http://localhost:8501
REM (database built by run_all.bat). Pilot data: start_dashboard_pilot.bat
setlocal
cd /d "%~dp0"
set DATASET=samples
set DATABASE_URL=
set REPORTS_DIR=
REM Default settings for the sample data (dataset.env is for the pilot)
set DEMAND_MOVEMENT_TYPES=601,251,261,201,281
set AS_OF_DATE=auto
set DEMAND_POLICY=legacy
set SERVICE_LEVEL_BY_ABC=uniform
if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
) else (
    echo [!] No virtual environment found - run run_all.bat first, or: python -m venv .venv ^&^& pip install -r requirements.txt
)
python -c "import streamlit, sqlalchemy" >nul 2>&1 || pip install -r requirements.txt
echo Starting dashboard ... (close this window to stop it)
python -m streamlit run dashboard\app.py --server.port 8501
pause
