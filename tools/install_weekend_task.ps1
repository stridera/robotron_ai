$ErrorActionPreference = 'Stop'
$env:PSModulePath = (Join-Path $PSHOME 'Modules') + ';' + $env:PSModulePath
Import-Module ScheduledTasks -ErrorAction Stop
$repo = Split-Path $PSScriptRoot -Parent
$python = Join-Path (Split-Path $repo -Parent) '.venv/Scripts/python.exe'
$name = 'RobotronWeekend20260912'
if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
    throw "Task already exists: $name; inspect it instead of replacing it."
}
$deadline = [datetime]'2026-09-14T09:00:00'
if ((Get-Date) -ge $deadline) { throw 'Weekend deadline has passed.' }
$action = New-ScheduledTaskAction -Execute $python `
    -Argument ('-u "' + (Join-Path $repo 'tools/weekend_supervisor.py') + '"') -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration ($deadline - (Get-Date))
$trigger.EndBoundary = $deadline.ToString('s')
$logon = New-ScheduledTaskTrigger -AtLogOn -User ([Security.Principal.WindowsIdentity]::GetCurrent().Name)
$logon.EndBoundary = $deadline.ToString('s')
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 72) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) -Hidden
Register-ScheduledTask -TaskName $name -Action $action -Trigger @($trigger,$logon) `
    -Principal $principal -Settings $settings `
    -Description 'User-authorized Robotron research through Monday Sep 14 09:00 Pacific. Serialized tests/reviews; logs/weekend_20260912/STOP stops work.' | Out-Null
Start-ScheduledTask -TaskName $name
Get-ScheduledTask -TaskName $name | Select-Object TaskName,State
