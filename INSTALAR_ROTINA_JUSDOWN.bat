@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALAR_ROTINA_JUSDOWN.ps1"
if errorlevel 1 echo Nao foi possivel instalar. Confira a mensagem acima.
pause
