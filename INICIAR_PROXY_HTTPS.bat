@echo off
chcp 65001 >nul
cd /d "%~dp0"
where caddy >nul 2>&1
if errorlevel 1 (
 echo Caddy nao instalado no PATH. O TI deve obter o executavel oficial em https://caddyserver.com/download
 pause
 exit /b 1
)
if not exist Caddyfile (
 echo Execute CONFIGURAR_PILOTO_REDE.bat primeiro.
 pause
 exit /b 1
)
caddy validate --config Caddyfile --adapter caddyfile
if errorlevel 1 (pause & exit /b 1)
caddy run --config Caddyfile --adapter caddyfile
pause
