@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" ir_capture_review.py %*
) else (
  python ir_capture_review.py %*
)
if errorlevel 1 pause
