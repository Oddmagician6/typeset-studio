@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo Python was not found on this computer.
  echo Install Python 3.10 or newer from https://www.python.org/downloads/
  echo During install, tick the box "Add Python to PATH", then run this file again.
  echo.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\activate.bat" (
  echo First run: setting up a private workspace. This happens once and takes a minute...
  python -m venv .venv
  call ".venv\Scripts\activate.bat"
  python -m pip install --upgrade pip >nul
  pip install -r requirements.txt
) else (
  call ".venv\Scripts\activate.bat"
)

echo.
echo ============================================================
echo  Typeset Studio is starting.
echo  A browser tab will open at http://127.0.0.1:5050
echo  Keep this window open while you work; close it to stop.
echo ============================================================
echo.
python app.py
pause
