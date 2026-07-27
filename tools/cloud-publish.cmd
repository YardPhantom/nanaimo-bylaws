@echo off
setlocal
cd /d "%~dp0.."
python tools\cloud_sync.py publish
if errorlevel 1 exit /b %errorlevel%
python tools\cloud_sync.py verify
exit /b %errorlevel%
