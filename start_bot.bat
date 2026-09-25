@echo off
cd /d "%~dp0"
start "" /b ".venv\Scripts\pythonw.exe" run.py --loop
