param([string]$BackupRoot = '')
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($BackupRoot)) { $BackupRoot = Join-Path $PSScriptRoot '..\backups' }
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$backend = Join-Path $projectRoot 'backend'
$python = Join-Path $backend '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Backend virtual environment is missing' }
# The Python helper loads backend/.env; credentials never enter task arguments.
Push-Location -LiteralPath $backend
try {
    & $python -B scheduled_backup.py --output $BackupRoot
    $backupExit = $LASTEXITCODE
} finally { Pop-Location }
exit $backupExit
