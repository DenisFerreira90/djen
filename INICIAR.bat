@echo off
chcp 65001 >nul
cd /d "%~dp0"
title ConectaAdv - Gestao juridica local
where py >nul 2>&1
if not errorlevel 1 (
  py -3 servidor.py
) else (
  where python >nul 2>&1
  if not errorlevel 1 (
    python servidor.py
  ) else (
    echo ERRO: Python nao encontrado.
    echo Instale Python 3.10 ou superior e marque "Add Python to PATH".
  )
)
echo.
echo Se houve algum erro, consulte LEIA-ME.txt.
pause
