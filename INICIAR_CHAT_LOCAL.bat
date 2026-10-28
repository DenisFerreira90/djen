@echo off
chcp 65001 >nul
title ConectaAdv - Chat independente - mantenha esta janela aberta
cd /d "%~dp0"
where py >nul 2>&1
if not errorlevel 1 (py -3 servidor.py --chat-independente --piloto-chat) else (python servidor.py --chat-independente --piloto-chat)
pause
