@echo off
setlocal
cd /d "%~dp0.."
if "%~1"=="" (echo Usage: .\tools\test-brevo-smtp.cmd you@example.com & exit /b 1)
python tools\test_brevo_smtp.py "%~1"
