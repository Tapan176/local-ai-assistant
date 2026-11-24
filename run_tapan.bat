@echo off
setlocal
cd /d "%~dp0"
set PYTHONPATH=%cd%
set PYTHONIOENCODING=utf-8

rem Prefer the project's virtualenv if it exists.
set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe

echo Launching TAPAN_AI (Jarvis mode)...
%PY% -m src.main
pause
