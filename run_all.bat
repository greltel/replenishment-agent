@echo off
REM ============================================================
REM  Replenishment Agent - full pipeline on the SAMPLE data (Windows)
REM  Generates sample data (skip with: run_all.bat --keep-data),
REM  loads the DB, runs the agent and every evaluation script.
REM  Total time: ~10-12 minutes on a typical laptop.
REM  Always uses data\samples, even if data\anonymized exists.
REM  Real pilot data: run_all_pilot.bat
REM ============================================================
setlocal
cd /d "%~dp0"
set DATA_SOURCE=samples
set DATABASE_URL=
set REPORTS_DIR=
REM The sample data post goods receipts as 101 and use the default
REM settings: values in .env or data\pilot\dataset.env are for the pilot
set GR_MOVEMENT_TYPES=101
set DEMAND_MOVEMENT_TYPES=601,251,261,201,281
set STOCK_COLUMNS=LABST
set MATERIAL_SCOPE=all
set AS_OF_DATE=auto
set DEMAND_POLICY=legacy
set SERVICE_LEVEL_BY_ABC=uniform

if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
) else (
    echo [!] No virtual environment found - creating .venv and installing requirements, once, 2-5 min ...
    python -m venv .venv || goto :error
    call ".venv\Scripts\activate.bat"
    python -m pip install --upgrade pip >nul
    pip install -r requirements.txt || goto :error
)

REM Make sure the dependencies are installed (e.g. an empty or stale .venv)
python -c "import sqlalchemy, pandas, numpy, scipy, streamlit, plotly" >nul 2>&1
if errorlevel 1 (
    echo [!] Missing packages - installing requirements ...
    pip install -r requirements.txt || goto :error
)

if /I "%1"=="--keep-data" (
    echo [1/9] Keeping existing data in data\samples
) else (
    echo [1/9] Generating sample data ...
    python scripts\generate_sample_data.py || goto :error
)

echo [2/9] Loading data into SQLite ...
python scripts\run_etl.py || goto :error

echo [3/9] Running the agent (BDI cycle) ...
python scripts\run_agent.py || goto :error

echo [4/9] Backtest As-Is vs To-Be (60 days, realistic) ...
python scripts\run_validation.py || goto :error

echo [5/9] Cost scenarios ...
python scripts\run_validation.py --all-scenarios || goto :error

echo [6/9] Sensitivity analysis ...
python scripts\run_validation.py --sensitivity || goto :error

echo [7/9] Random windows + bootstrap (30 x 60 days, ~5 min) ...
python scripts\run_bootstrap.py || goto :error

echo [8/9] Rule ablation (stress test) ...
python scripts\run_rule_ablation.py --stress-test || goto :error

echo [9/9] Forecast accuracy (walk-forward, all materials) ...
python scripts\run_forecast_eval.py || goto :error

echo.
echo ============================================================
echo  Done. Start the dashboard with:  start_dashboard.bat
echo ============================================================
pause
exit /b 0

:error
echo.
echo [X] A step failed (see the messages above).
pause
exit /b 1
