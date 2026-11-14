@echo off
rem Opens Metastat in demo mode: made-up data, no connection to Meta (separate data-demo folder).
chcp 65001 >nul
cd /d "%~dp0"
set "DEMO=true"
start "" ".venv\Scripts\pythonw.exe" -m metastat app %*
