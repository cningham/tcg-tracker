@echo off
cd /d "%~dp0"
if not exist .venv (
  echo First run: setting up...
  py -3 -m venv .venv || python -m venv .venv || (echo Python 3 not found. Install it from python.org and tick "Add to PATH". & pause & exit /b 1)
  .venv\Scripts\python -m pip install --upgrade pip >nul
  .venv\Scripts\python -m pip install -r requirements.txt || (pause & exit /b 1)
)
if not exist .env (
  copy .env.example .env >nul
  echo Created .env - open it in Notepad, add your eBay keys, then run start.bat again.
  notepad .env
  pause
  exit /b 0
)
.venv\Scripts\python run.py
pause
