@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 (set "EPROC_PY=python") else (set "EPROC_PY=py -3")
%EPROC_PY% -m pip install -r requirements-eproc.txt
if errorlevel 1 goto erro
%EPROC_PY% -m playwright install chromium
if errorlevel 1 goto erro
echo Instalacao concluida. Execute INICIAR.bat.
pause
exit /b 0
:erro
echo Nao foi possivel instalar. Confira Python e conexao com a internet.
pause
exit /b 1
