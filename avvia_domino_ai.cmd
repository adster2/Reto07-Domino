@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" "src\domino_ai.py" --physical %*
if errorlevel 1 pause
