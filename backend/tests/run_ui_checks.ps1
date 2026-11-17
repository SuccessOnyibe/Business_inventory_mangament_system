[CmdletBinding()]
param([ValidateSet('layout','smoke')][string]$Suite = 'layout', [switch]$BackendChecks)
$ErrorActionPreference='Stop'
$projectRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$backend=Join-Path $projectRoot 'backend'
$cluster=Join-Path $env:TEMP 'inventory-postgres-27bc6b445d1840e7b9add170b5237454'
$pgCtl='C:\Program Files\PostgreSQL\17\bin\pg_ctl.exe'
if(-not(Test-Path -LiteralPath $cluster)){throw 'Dedicated UI-test cluster is missing; business PostgreSQL will not be used'}
& $pgCtl -D $cluster status *> $null
if($LASTEXITCODE -eq 0){throw 'Test cluster already running; this runner will not take ownership of an existing session'}
if(Get-NetTCPConnection -State Listen -LocalPort 58541,9223 -ErrorAction SilentlyContinue){throw 'A test port is already in use'}
$qa=Join-Path $env:TEMP ('inventory-layout-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $qa | Out-Null
Write-Output ('QA_ARTIFACTS='+$qa)
$api=$null;$browser=$null;$started=$false;$result=1
try {
    & $pgCtl -D $cluster -l (Join-Path $cluster 'server.log') -o '-h 127.0.0.1 -p 55439' -w start
    if($LASTEXITCODE -ne 0){throw 'Disposable test server failed to start'}
    $started=$true
    # A shell may already have a hosted URL; this child process must use QA only.
    Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
    $env:DB_HOST='127.0.0.1';$env:DB_PORT='55439';$env:DB_NAME='postgres';$env:DB_USER='inventory_test';$env:DB_PASSWORD=''
    $env:PYTHONPATH=$backend;$env:UI_TEST_DATABASE='inventory_ui_test_'+[guid]::NewGuid().ToString('N')
    $env:UI_TEST_PASSWORD=[guid]::NewGuid().ToString('N')
    $python=Join-Path $backend '.venv\Scripts\python.exe'
    & $python -B (Join-Path $PSScriptRoot 'prepare_ui_test.py')
    if($LASTEXITCODE -ne 0){throw 'Isolated UI fixture failed'}
    $env:DB_NAME=$env:UI_TEST_DATABASE
    $unitResult=0
    if($BackendChecks){
        $env:RUN_POSTGRES_TESTS='1';$env:RUN_POSTGRES_CONCURRENCY='1';$env:RUN_BACKUP_TESTS='1'
        $unit=Start-Process -FilePath $python -ArgumentList @('-B','-m','unittest','discover','-s','tests') -WorkingDirectory $backend -WindowStyle Hidden -RedirectStandardOutput (Join-Path $qa 'unit.out') -RedirectStandardError (Join-Path $qa 'unit.err') -Wait -PassThru
        $unitResult=$unit.ExitCode
        Get-Content -LiteralPath (Join-Path $qa 'unit.err') -Tail 12
    }
    $api=Start-Process -FilePath $python -ArgumentList @('-B','-m','uvicorn','main:app','--host','127.0.0.1','--port','58541') -WorkingDirectory $backend -WindowStyle Hidden -RedirectStandardOutput (Join-Path $qa 'api.out') -RedirectStandardError (Join-Path $qa 'api.err') -PassThru
    # Wait for API readiness rather than racing slow startup on this PC.
    $apiReady=$false
    $apiDeadline=(Get-Date).AddSeconds(30)
    while((Get-Date) -lt $apiDeadline){
        try {
            $probe=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:58541/health' -TimeoutSec 2
            if($probe.StatusCode -eq 200){$apiReady=$true;break}
        } catch { if($api.HasExited){throw 'Test API exited during startup'} }
        Start-Sleep -Milliseconds 300
    }
    if(-not $apiReady){throw 'Test API did not become ready'}
    $browser=Start-Process -FilePath 'C:\Program Files\Google\Chrome\Application\chrome.exe' -ArgumentList @('--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-extensions','--remote-debugging-address=127.0.0.1','--remote-debugging-port=9223',('--user-data-dir='+(Join-Path $qa 'chrome')),'about:blank') -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 2
    $env:UI_TEST_URL='http://127.0.0.1:58541';$env:UI_SCREENSHOT_PATH=Join-Path $qa 'mobile.png'
    $check=Start-Process -FilePath (Get-Command node).Source -ArgumentList @((Join-Path $PSScriptRoot ('ui_'+$Suite+'.mjs'))) -WorkingDirectory $backend -WindowStyle Hidden -RedirectStandardOutput (Join-Path $qa 'ui.out') -RedirectStandardError (Join-Path $qa 'ui.err') -Wait -PassThru
    $browserResult=$check.ExitCode
    $result=if($unitResult -eq 0 -and $browserResult -eq 0){0}else{1}
    Get-Content -LiteralPath (Join-Path $qa 'ui.out')
    Get-Content -LiteralPath (Join-Path $qa 'ui.err')
    @{suite=$Suite;exit_code=$result;unit=$unitResult;browser=$browserResult}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $qa 'results.json')
} finally {
    if($browser -and -not $browser.HasExited){Stop-Process -Id $browser.Id -ErrorAction SilentlyContinue}
    if($api -and -not $api.HasExited){Stop-Process -Id $api.Id -ErrorAction SilentlyContinue}
    if($started){& $pgCtl -D $cluster -m fast -w stop}
}
exit $result
