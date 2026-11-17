[CmdletBinding(SupportsShouldProcess)]
param([string]$BackupRoot = '')
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($BackupRoot)) { $BackupRoot = Join-Path $PSScriptRoot '..\backups' }
if ((Get-TimeZone).Id -ne 'W. Central Africa Standard Time') {
    throw 'This task expects Lagos time. Review the trigger timezone before installing.'
}
$runner = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'run_backup.ps1'))
$destination = [IO.Path]::GetFullPath($BackupRoot)
$taskName = 'FestyAgricServices-DailyBackup'
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and -not ($existing.Actions.Arguments -like ('*' + $runner + '*'))) {
    throw 'A task with this name belongs to a different location; it was not changed'
}
$arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $runner + '" -BackupRoot "' + $destination + '"'
# Bypass applies to this reviewed script process only; system policy is unchanged.
$action = New-ScheduledTaskAction -Execute (Get-Command powershell.exe).Source -Argument $arguments -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -Daily -At '02:00'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
# Interactive, limited privilege: no account password is stored or requested.
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
if ($PSCmdlet.ShouldProcess($taskName, 'Register daily backup at 02:00 WAT for the signed-in user')) {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'FESTY AGRIC SERVICES read-only daily database backup; does not delete archives' -Force | Select-Object TaskName,State
}
