@echo off
setlocal
cd /d "%~dp0"
python -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Ready. Double-click launch.bat to open HALS Studio.
pause
exit /b 0
:failed
echo Installation failed. See the error above.
pause
exit /b 1
