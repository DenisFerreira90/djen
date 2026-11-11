@echo off
chcp 65001 >nul
cd /d "%~dp0"
".venv\Scripts\python.exe" coletor.py coletar TJRS --visivel --modo completa
pause
