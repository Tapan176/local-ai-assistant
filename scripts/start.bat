@echo off
:: Windows startup script for TAPAN-AI

cd /d "%~dp0.."

if exist "venv\Scripts\activate.bat" (
  echo Starting TAPAN-AI (venv)...
  call venv\Scripts\activate.bat
) else (
  echo Starting TAPAN-AI (system python)...
)

python start.py
pause
