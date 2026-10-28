@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>&1
if not errorlevel 1 (py -3 configurar_piloto_rede.py) else (python configurar_piloto_rede.py)
pause
