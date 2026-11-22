@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" "src\domino_visualizer.py"
if errorlevel 1 pause
