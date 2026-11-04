@echo off
cd /d "%~dp0"
where caddy >nul 2>nul
if errorlevel 1 (
 echo Instale o Caddy oficial e configure-o com o TI antes de iniciar o proxy.
 pause
 exit /b 1
)
caddy run --config "%~dp0rede_escritorio\Caddyfile" --adapter caddyfile
pause
