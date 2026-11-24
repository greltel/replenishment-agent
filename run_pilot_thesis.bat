@echo off
REM ============================================================
REM  Replenishment Agent - every pilot result reported in the thesis,
REM  with one command (Windows). About 4 hours on ~50k materials
REM  (2 cores, ~8 GB of memory: two backtests run side by side).
REM
REM  A. The pilot policy of data\pilot\dataset.env (as run_all_pilot.bat):
REM     anonymization, ETL, agent on the as-of date + summary, 60-day
REM     backtest, forecast accuracy per demand pattern, the backtest
REM     for 4 target service levels per ABC class, and the backtest in
REM     every 60-day window of the history.
REM       -> replenishment_pilot.db, reports\pilot
REM  B. The thesis policy (DEMAND_POLICY=legacy) on the same data, with
REM     the same evaluation per demand pattern, in its own folders:
REM       -> data\anonymized\legacy, replenishment_pilot_legacy.db,
REM          reports\pilot\legacy
REM
REM  What each report holds: README.md, section on run_pilot_thesis.
REM  Dashboard afterwards: start_dashboard_pilot.bat.
REM ============================================================
setlocal
cd /d "%~dp0"
set DATA_RAW_DIR=data/pilot
set DATA_SOURCE=anonymized

REM Settings of this dataset: data\pilot\dataset.env, one KEY=value per line
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
python -c "import sqlalchemy, pandas, numpy, scipy, streamlit, plotly" >nul 2>&1
if errorlevel 1 (
    echo [!] Missing packages - installing requirements ...
    pip install -r requirements.txt || goto :error
)
if not exist "data\pilot\MARA_export.csv" (
    echo [X] data\pilot\MARA_export.csv not found - copy the SAP exports there.
    goto :error
)
echo Dataset settings: AS_OF_DATE=%AS_OF_DATE% GR_MOVEMENT_TYPES=%GR_MOVEMENT_TYPES% DEMAND_MOVEMENT_TYPES=%DEMAND_MOVEMENT_TYPES% STOCK_COLUMNS=%STOCK_COLUMNS% MATERIAL_SCOPE=%MATERIAL_SCOPE% DEMAND_POLICY=%DEMAND_POLICY% SERVICE_LEVEL_BY_ABC=%SERVICE_LEVEL_BY_ABC%

REM ---- A. The pilot policy of dataset.env ----
set DATA_ANONYMIZED_DIR=data/anonymized
set DATABASE_URL=sqlite:///replenishment_pilot.db
set REPORTS_DIR=reports\pilot
if exist "%REPORTS_DIR%" rmdir /s /q "%REPORTS_DIR%"
mkdir "%REPORTS_DIR%" || goto :error

echo [1/10] Anonymizing the SAP exports ...
python -m src.data_layer.anonymization || goto :error
echo [2/10] Loading data into SQLite (replenishment_pilot.db) ...
python scripts\run_etl.py || goto :error
echo [3/10] Running the agent on the as-of date ...
python scripts\run_agent.py || goto :error
python scripts\pilot_agent_summary.py --out %REPORTS_DIR%\agent_summary.csv || goto :error
REM the same agent with 98 %% for every material (in memory, nothing persisted)
python scripts\pilot_agent_summary.py --levels uniform --out %REPORTS_DIR%\agent_summary_uniform.csv || goto :error
echo [4/10] Backtest As-Is vs To-Be (60 days, realistic) ...
python scripts\run_validation.py --out %REPORTS_DIR%\validation_report.csv || goto :error
echo [5/10] Forecast accuracy per demand pattern (walk-forward) ...
python scripts\run_forecast_eval.py --out %REPORTS_DIR%\forecast_report.csv || goto :error
echo [6/10] Target service levels per ABC class (4 backtests, 2 at a time) ...
python scripts\run_service_level_grid.py --jobs 2 --out %REPORTS_DIR%\service_level_grid.csv || goto :error
echo [7/10] Backtest in every 60-day window with a full year of history (2 at a time) ...
python scripts\run_pilot_windows.py --jobs 2 --out %REPORTS_DIR%\pilot_windows.csv || goto :error

REM ---- B. The thesis policy (legacy), same data and same evaluation ----
set DEMAND_POLICY=legacy
set SERVICE_LEVEL_BY_ABC=uniform
set DATA_ANONYMIZED_DIR=data/anonymized/legacy
set DATABASE_URL=sqlite:///replenishment_pilot_legacy.db
set REPORTS_DIR=reports\pilot\legacy
mkdir "%REPORTS_DIR%" || goto :error

echo [8/10] Legacy policy: anonymizing and loading ...
python -m src.data_layer.anonymization || goto :error
python scripts\run_etl.py || goto :error
echo [9/10] Legacy policy: agent on the as-of date ...
python scripts\run_agent.py || goto :error
python scripts\pilot_agent_summary.py --out %REPORTS_DIR%\agent_summary.csv || goto :error
echo [10/10] Legacy policy: backtest, evaluated per demand pattern as A ...
python scripts\run_validation.py --by-pattern --out %REPORTS_DIR%\validation_report.csv || goto :error

echo.
echo ============================================================
echo  Done. Reports: reports\pilot (pilot policy) and
echo  reports\pilot\legacy (thesis policy).
echo ============================================================
pause
exit /b 0

:error
echo.
echo [X] A step failed (see the messages above).
pause
exit /b 1
