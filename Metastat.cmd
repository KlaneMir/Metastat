@echo off
rem Opens Metastat in its own window (no console).
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" -m metastat app %*
