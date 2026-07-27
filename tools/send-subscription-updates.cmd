@echo off
setlocal
cd /d "%~dp0.."
if not exist runtime\subscription.env (
  echo Missing runtime\subscription.env
  exit /b 1
)
python tools\send_subscription_updates.py
