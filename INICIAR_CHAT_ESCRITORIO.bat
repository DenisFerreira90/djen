@echo off
chcp 65001 >nul
title ConectaAdv - Chat independente - mantenha esta janela aberta
cd /d "%~dp0"
if not exist piloto-rede.json (
 echo Execute CONFIGURAR_PILOTO_REDE.bat primeiro, com apoio do TI.
 pause
 exit /b 1
)
where py >nul 2>&1
if not errorlevel 1 (py -3 servidor.py --chat-independente --rede piloto-rede.json --piloto-chat --sem-navegador) else (python servidor.py --chat-independente --rede piloto-rede.json --piloto-chat --sem-navegador)
pause
