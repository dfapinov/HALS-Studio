@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run install.bat first to set up HALS Studio.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" entry.py %*
if errorlevel 1 pause
