@echo off
REM Starts the Streamlit dashboard on http://localhost:8501
cd /d "%~dp0"
if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"
echo Starting dashboard ... (close this window to stop it)
python -m streamlit run dashboard\app.py --server.port 8501
pause
