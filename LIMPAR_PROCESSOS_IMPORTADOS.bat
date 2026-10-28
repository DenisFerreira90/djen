@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>&1
if not errorlevel 1 (py -3 limpar_processos.py --executar) else (python limpar_processos.py --executar)
pause
