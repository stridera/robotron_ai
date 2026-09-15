param([switch]$UseWsl)
$ErrorActionPreference = 'Stop'
$python = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) '.venv/Scripts/python.exe'
$log = Join-Path (Split-Path $PSScriptRoot -Parent) "logs/process_exit_test_$PID"
New-Item -ItemType Directory $log | Out-Null
foreach ($expected in @(0,7)) {
    foreach ($retainHandle in @($false,$true)) {
        $exe = $python
        $argsList = @('-c',"`"import time,sys; time.sleep(0.3); sys.exit($expected)`"")
        if ($UseWsl) {
            $exe = 'wsl.exe'
            $argsList = @('-d','Ubuntu','--exec','/home/strider/Code/robotron-rl/.venv-collision/bin/python') + $argsList
        }
        $process = Start-Process $exe -ArgumentList $argsList -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput "$log/$expected-$retainHandle.out" `
            -RedirectStandardError "$log/$expected-$retainHandle.err"
        if ($retainHandle) { [void]$process.Handle }
        while (-not $process.HasExited) {
            Start-Sleep -Milliseconds 100
            $process.Refresh()
        }
        $process.WaitForExit()
        Write-Output "expected=$expected retained_handle=$retainHandle actual=$($process.ExitCode)"
        if ($retainHandle -and ($null -eq $process.ExitCode -or $process.ExitCode -ne $expected)) {
            throw "Exit code was not preserved: expected $expected"
        }
        $process.Dispose()
    }
}
