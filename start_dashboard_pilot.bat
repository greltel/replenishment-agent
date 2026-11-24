@echo off
REM Starts the Streamlit dashboard on the PILOT data: http://localhost:8502
REM (database and reports built by run_all_pilot.bat). It uses its own port,
REM so it can run side by side with start_dashboard.bat (samples, 8501).
setlocal
cd /d "%~dp0"
set DATASET=pilot
set DATABASE_URL=sqlite:///replenishment_pilot.db
set REPORTS_DIR=reports\pilot

REM Settings of this dataset (as-of date, movement types, stock types,
REM material scope): data\pilot\dataset.env, one KEY=value per line
if exist "data\pilot\dataset.env" (
    for /f "usebackq eol=# tokens=1,* delims==" %%a in ("data\pilot\dataset.env") do set "%%a=%%b"
)
if not exist "replenishment_pilot.db" (
    echo [!] replenishment_pilot.db not found - run run_all_pilot.bat first.
    pause
    exit /b 1
)
if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
) else (
    echo [!] No virtual environment found - run run_all_pilot.bat first.
    pause
    exit /b 1
)
echo Starting dashboard on the pilot data ... (close this window to stop it)
python -m streamlit run dashboard\app.py --server.port 8502
pause
