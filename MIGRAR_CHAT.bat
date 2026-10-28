@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>&1
if not errorlevel 1 (py -3 chat_servico.py) else (python chat_servico.py)
pause
