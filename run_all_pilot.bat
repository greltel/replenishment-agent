@echo off
REM ============================================================
REM  Replenishment Agent - pipeline on the REAL pilot data (Windows)
REM
REM  Reads the SAP exports of data\pilot, anonymizes them into
REM  data\anonymized and builds its own database replenishment_pilot.db
REM  and its own reports in reports\pilot. The sample-data results of
REM  run_all.bat (replenishment.db, reports in the project root) are
REM  not touched.
REM
REM    run_all_pilot.bat          agent + 60-day backtest
REM                               (~30-45 min on ~50k materials)
REM    run_all_pilot.bat --full   + cost scenarios, sensitivity,
REM                               bootstrap, rule ablation, forecast
REM                               (many hours on ~50k materials)
REM
REM  Dashboard afterwards: start_dashboard_pilot.bat
REM ============================================================
setlocal
cd /d "%~dp0"
set DATA_RAW_DIR=data/pilot
set DATA_SOURCE=anonymized
set DATABASE_URL=sqlite:///replenishment_pilot.db
set REPORTS_DIR=reports\pilot

REM Settings of this dataset (as-of date, movement types, stock types,
REM material scope): data\pilot\dataset.env, one KEY=value per line
if exist "data\pilot\dataset.env" (
    for /f "usebackq eol=# tokens=1,* delims==" %%a in ("data\pilot\dataset.env") do set "%%a=%%b"
)

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

if not exist "data\pilot\MARA_export.csv" (
    echo [X] data\pilot\MARA_export.csv not found - copy the SAP exports there.
    goto :error
)

REM Fresh reports folder: every report in it belongs to this run
if exist "%REPORTS_DIR%" rmdir /s /q "%REPORTS_DIR%"
mkdir "%REPORTS_DIR%" || goto :error

echo Dataset settings: AS_OF_DATE=%AS_OF_DATE% GR_MOVEMENT_TYPES=%GR_MOVEMENT_TYPES% DEMAND_MOVEMENT_TYPES=%DEMAND_MOVEMENT_TYPES% STOCK_COLUMNS=%STOCK_COLUMNS% MATERIAL_SCOPE=%MATERIAL_SCOPE% DEMAND_POLICY=%DEMAND_POLICY% SERVICE_LEVEL_BY_ABC=%SERVICE_LEVEL_BY_ABC%
echo [1/4] Anonymizing the SAP exports (data\pilot -^> data\anonymized) ...
python -m src.data_layer.anonymization || goto :error

echo [2/4] Loading data into SQLite (replenishment_pilot.db) ...
python scripts\run_etl.py || goto :error

echo [3/4] Running the agent (BDI cycle) ...
python scripts\run_agent.py || goto :error

echo [4/4] Backtest As-Is vs To-Be (60 days, realistic) ...
python scripts\run_validation.py --out %REPORTS_DIR%\validation_report.csv || goto :error

if /I not "%1"=="--full" goto :done

echo [5/9] Cost scenarios ...
python scripts\run_validation.py --all-scenarios --out %REPORTS_DIR%\validation_report.csv || goto :error

echo [6/9] Sensitivity analysis ...
python scripts\run_validation.py --sensitivity --out %REPORTS_DIR%\validation_report.csv || goto :error

echo [7/9] Random windows + bootstrap (30 x 60 days, the longest step) ...
python scripts\run_bootstrap.py --out %REPORTS_DIR%\bootstrap_report.csv || goto :error

echo [8/9] Rule ablation (stress test) ...
python scripts\run_rule_ablation.py --stress-test --out %REPORTS_DIR%\ablation_report.csv || goto :error

echo [9/9] Forecast accuracy (walk-forward, all materials) ...
python scripts\run_forecast_eval.py --out %REPORTS_DIR%\forecast_report.csv || goto :error

:done
echo.
echo ============================================================
echo  Done (pilot data). Start the dashboard with:  start_dashboard_pilot.bat
echo ============================================================
pause
exit /b 0

:error
echo.
echo [X] A step failed (see the messages above).
pause
exit /b 1
