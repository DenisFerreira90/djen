$ErrorActionPreference = 'Stop'
$taskName = 'ConectaAdv-JUSDOWN'
$taskPython = (& py -3 -c 'import sys; print(sys.executable)' | Select-Object -Last 1).Trim()
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $taskPython)) { throw 'Python 3 não localizado. Instale o Python usado pelo ConectaAdv.' }
$taskServer = Join-Path $PSScriptRoot 'servidor.py'
if (-not (Test-Path -LiteralPath $taskServer)) { throw 'Mantenha este arquivo na pasta do servidor.py.' }
$taskUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $taskPython -Argument ('-B "' + $taskServer + '" --sem-navegador') -WorkingDirectory $PSScriptRoot
$triggers = @((New-ScheduledTaskTrigger -Daily -At '07:55'), (New-ScheduledTaskTrigger -Daily -At '12:25'), (New-ScheduledTaskTrigger -AtLogOn -User $taskUser))
$principal = New-ScheduledTaskPrincipal -UserId $taskUser -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Principal $principal -Settings $settings -Description 'Abre o servidor ConectaAdv; JUSDOWN consulta às 08:00 e 12:30 no horário de Brasília.' -Force | Out-Null
Write-Host 'Rotina instalada para esta conta do Windows.'
Write-Host 'Mantenha a conta conectada, o computador ligado e com Internet. A tarefa não usa senha de tribunal.'
Write-Host 'O servidor é preparado às 07:55/12:25; o JUSDOWN inicia a rodada às 08:00/12:30.'
Write-Host 'Não foi iniciada uma coleta autenticada de processos. Não mova a pasta após instalar a tarefa.'
