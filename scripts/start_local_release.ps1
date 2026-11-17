param([ValidateRange(1024,65535)][int]$Port = 8001, [string]$AllowedHosts = 'localhost,127.0.0.1')
$ErrorActionPreference = 'Stop'
$backend = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\backend'))
# Bind to loopback. Remote branch access requires the reviewed HTTPS proxy setup.
$env:APP_ALLOWED_HOSTS = $AllowedHosts
Push-Location -LiteralPath $backend
try {
    & '.\.venv\Scripts\python.exe' -B -m uvicorn main:app --host 127.0.0.1 --port $Port --workers 2 --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-access-log
    $serverExit=$LASTEXITCODE
} finally { Pop-Location }
exit $serverExit
