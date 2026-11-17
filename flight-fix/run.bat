@echo off
rem One-command start for Windows: creates a virtual environment, installs Flask, starts FlightFix.
cd /d "%~dp0"
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
echo FlightFix running at http://localhost:5000
python run.py
