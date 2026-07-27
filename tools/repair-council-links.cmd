@echo off
setlocal
cd /d "%~dp0.."
python tools\repair_council_links.py
if errorlevel 1 exit /b %errorlevel%
echo.
echo Council links repaired.
endlocal
