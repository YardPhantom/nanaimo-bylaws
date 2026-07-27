@echo off
setlocal
cd /d "%~dp0.."
python tools\verify_council_collection.py %*
exit /b %errorlevel%
