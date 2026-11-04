@echo off
cd /d "%~dp0"
if not exist "rede_escritorio\piloto-rede.json" (
 echo Execute primeiro CONFIGURAR_REDE_ESCRITORIO.bat com os dados da rede.
 pause
 exit /b 1
)
py -3 servidor.py --piloto-escritorio --rede "rede_escritorio\piloto-rede.json" --sem-navegador
pause
