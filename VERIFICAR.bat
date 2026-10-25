@echo off
chcp 65001 >nul
cd /d "%~dp0"
title DJEN Consulta - Verificar Python
where py >nul 2>&1
if not errorlevel 1 (
 py -3 --version
 echo.
 echo Tudo pronto. Execute INICIAR.bat para abrir o site.
) else (
  where python >nul 2>&1
  if not errorlevel 1 (
    python --version
    echo.
    echo Tudo pronto. Execute INICIAR.bat para abrir o site.
  ) else (
    echo Python nao encontrado. Instale Python 3.9 ou superior em https://www.python.org/downloads/
    echo Marque "Add Python to PATH" na instalacao.
  )
)
pause
