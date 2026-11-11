@echo off
chcp 65001 >nul
cd /d "%~dp0"
".venv\Scripts\python.exe" coletor.py retomar
if errorlevel 1 exit /b %errorlevel%
".venv\Scripts\python.exe" coletor.py coletar TJRS --visivel --modo pendentes
