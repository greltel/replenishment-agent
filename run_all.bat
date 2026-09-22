@echo off
REM ============================================================
REM  Replenishment Agent - full pipeline (Windows)
REM  Generates sample data (skip with: run_all.bat --keep-data),
REM  loads the DB, runs the agent and every evaluation script.
REM  Total time: ~6-8 minutes on a typical laptop.
REM ============================================================
cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
) else (
    echo [!] No virtual environment found - using the system Python.
)

if /I "%1"=="--keep-data" (
    echo [1/8] Keeping existing data in data\samples or data\anonymized
) else (
    echo [1/8] Generating sample data ...
    python scripts\generate_sample_data.py || goto :error
)

echo [2/8] Loading data into SQLite ...
python scripts\run_etl.py || goto :error

echo [3/8] Running the agent (BDI cycle) ...
python scripts\run_agent.py || goto :error

echo [4/8] Backtest As-Is vs To-Be (60 days, realistic) ...
python scripts\run_validation.py || goto :error

echo [5/8] Cost scenarios ...
python scripts\run_validation.py --all-scenarios || goto :error

echo [6/8] Sensitivity analysis ...
python scripts\run_validation.py --sensitivity || goto :error

echo [7/8] Random windows + bootstrap (30 x 21 days) ...
python scripts\run_bootstrap.py || goto :error

echo [8/8] Rule ablation (stress test) ...
python scripts\run_rule_ablation.py --stress-test || goto :error

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
