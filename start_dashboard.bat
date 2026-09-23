@echo off
REM Starts the Streamlit dashboard on http://localhost:8501
cd /d "%~dp0"
if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
) else (
    echo [!] No virtual environment found - run run_all.bat first, or: python -m venv .venv ^&^& pip install -r requirements.txt
)
python -c "import streamlit, sqlalchemy" >nul 2>&1 || pip install -r requirements.txt
echo Starting dashboard ... (close this window to stop it)
python -m streamlit run dashboard\app.py --server.port 8501
pause
