@echo off
setlocal
cd /d "%~dp0.."
python tools\cloud_sync.py pull
exit /b %errorlevel%
