@echo off
setlocal
cd /d "%~dp0.."
python tools\deduplicate_archive.py --apply
if errorlevel 1 exit /b %errorlevel%
python tools\collect_bylaws.py --download-pdfs
if errorlevel 1 exit /b %errorlevel%
python tools\collect_council.py --download
if errorlevel 1 exit /b %errorlevel%
python tools\deduplicate_archive.py --check
exit /b %errorlevel%
