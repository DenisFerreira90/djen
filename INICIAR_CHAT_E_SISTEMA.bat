@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist dados_chat\chat.sqlite3 (
 echo Primeiro execute MIGRAR_CHAT.bat com os servidores parados.
 pause
 exit /b 1
)
start "ConectaAdv - Chat independente" cmd /c call "%~dp0INICIAR_CHAT_LOCAL.bat"
start "ConectaAdv - Sistema juridico e eproc" cmd /c call "%~dp0INICIAR.bat"
