"""Assistente executado no Windows; credencial digitada não é persistida."""
import getpass
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import agendamento
import juridico

if __name__=='__main__':
    try:
        if os.name!='nt':raise ValueError('Execute este assistente no Windows.')
        print('ConectaAdv — agendar coleta diária às 6h. Use sua conta ADMINISTRADOR DO CONECTAADV, não a senha do eproc.')
        login=input('Login ConectaAdv: ').strip();password=getpass.getpass('Senha ConectaAdv (não será salva): ')
        session,token=juridico.store.login(login,password);password=None;actor=session['usuario'];juridico.store.logout(token,actor)
        if actor['role']!='administrador':raise ValueError('A conta deve ser administradora.')
        if '--desativar' in sys.argv:
            agendamento.configure(juridico.store,actor,enabled=False)
            subprocess.run(['powershell.exe','-NoProfile','-Command',"Unregister-ScheduledTask -TaskName 'ConectaAdv-Coleta-6h' -Confirm:$false -ErrorAction SilentlyContinue"],check=True)
            print('Agendamento desativado. Uma coleta já em andamento não é cancelada.');sys.exit(0)
        exe=sys.executable;script=str(Path(__file__).with_name('iniciar_agendado.py').resolve())
        # Dados locais passados como argumentos; sem interpolar valores em código PowerShell.
        ps='''param([string]$PythonExe,[string]$Launcher)
$action=New-ScheduledTaskAction -Execute $PythonExe -Argument ('"'+$Launcher+'"') -WorkingDirectory (Split-Path $Launcher)
$trigger=New-ScheduledTaskTrigger -Daily -At '06:00'
$settings=New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal=New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'ConectaAdv-Coleta-6h' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
'''
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'agendar.ps1';path.write_text(ps,encoding='utf-8-sig')
            subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(path),exe,script],check=True)
        config=agendamento.configure(juridico.store,actor)
        print('Agendamento salvo. Primeiro dia: '+config['inicio']+' às 6h. Mantenha o usuário Windows conectado. Login do eproc precisa estar válido na sessão salva.')
    except Exception:
        print('Não foi possível concluir. Confira a conta administradora e as permissões do Agendador do Windows. Nenhuma senha foi salva.');sys.exit(1)
