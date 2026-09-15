param(
    [ValidateRange(1, 100)][int]$Games = 8,
    [ValidateRange(6, 100)][int]$MaxWave = 40,
    [ValidatePattern('^[a-z][a-z0-9]*$')][string]$CandidateName = 'four',
    [string]$CandidateSettings = 'VSEARCH_COLLISION_SUBSTEPS=4',
    [ValidateRange(0.1, 8)][double]$MaxHours = 8,
    [ValidatePattern('^[a-z0-9_]*$')][string]$RunName = '',
    [switch]$Vision,
    [switch]$Production,
    [switch]$PrepareOnly
)
$ErrorActionPreference = 'Stop'
# Start-Process from PowerShell 7 can pass its module search order into 5.1.
# Resolve the child runtime's built-in modules first; do not change host settings.
$env:PSModulePath = (Join-Path $PSHOME 'Modules') + ';' + $env:PSModulePath
Import-Module Microsoft.PowerShell.Utility -ErrorAction Stop
$repo = Split-Path $PSScriptRoot -Parent
$codeRoot = Split-Path $repo -Parent
$python = Join-Path $codeRoot '.venv\Scripts\python.exe'
$dev = Join-Path $codeRoot 'robotron'
if (-not $RunName) { $RunName = 'collision_' + (Get-Date -Format 'yyyyMMdd_HHmmss') }
foreach ($setting in ($CandidateSettings -split ',')) {
    if ($setting -notmatch '^(VSEARCH|FSM|ROBOTRON)_[A-Z0-9_]+=[A-Za-z0-9_.|+-]+$') {
        throw "Invalid candidate setting: $setting"
    }
}
if ($CandidateName -eq 'base') { throw 'CandidateName cannot be base.' }
$runDir = Join-Path $repo "logs\$runName"
New-Item -ItemType Directory -Path $runDir | Out-Null

# This runner exclusively owns the test rig. Do not attach to another session.
if (Get-Process xenia_canary -ErrorAction SilentlyContinue) {
    throw 'Xenia is already running. Finish the existing session before this batch.'
}
if (Get-NetTCPConnection -LocalPort 9876 -State Listen -ErrorAction SilentlyContinue) {
    throw 'The gamepad server is already running. Finish the existing session first.'
}
# Start from documented defaults rather than inheriting an earlier experiment.
Get-ChildItem Env: | Where-Object Name -Match '^(ROBOTRON|VSEARCH|FSM|LAB)_' |
    ForEach-Object { Remove-Item -LiteralPath ("Env:" + $_.Name) }
$env:PYTHONIOENCODING = 'utf-8'
$oracle = if ($Vision -or $Production) { 0 } else { 1 }
$common = "ROBOTRON_EYE_SYNC=1,ROBOTRON_HOLD_ACTION=4,ROBOTRON_ORACLE=$oracle,ROBOTRON_MAX_WAVE=$MaxWave,ROBOTRON_YOLO_LAG_TICKS=0.7,ROBOTRON_PLAYER_LEAD_TICKS=1.5"
$baseArm = $runName + '_base'
$fineArm = $runName + '_' + $CandidateName
$since = [DateTimeOffset]::Now.ToUnixTimeSeconds()
$manifest = @{
    run=$runName; since=$since; games_per_arm=$Games; max_wave=$MaxWave
    oracle=$oracle; common=$common; baseline=$baseArm; candidate=$fineArm
    production=[bool]$Production
    candidate_settings=$CandidateSettings; max_hours=$MaxHours
    wave_log=(Join-Path $dev 'logs\yolo_waves.jsonl')
    source_hashes=@(Get-FileHash -Algorithm SHA256 -LiteralPath @(
        (Join-Path $dev 'brain_yolo.py'), (Join-Path $dev 'brain_champion.py'),
        (Join-Path $dev 'brain3.py'), (Join-Path $dev 'ab_yolo.py'),
        (Join-Path $dev 'clearance_planner.py'), (Join-Path $dev 'robotron_fsm.py'),
        (Join-Path $dev 'fsm_evolved_planner_v2_hunt.json'),
        (Join-Path $dev 'runs\detect\robotron_yolo6\weights\best.pt')))
}
if ($Production) {
    $manifest.source_hashes += @(Get-FileHash -Algorithm SHA256 -LiteralPath @(
        (Join-Path $repo 'brain.py'), (Join-Path $repo 'perception.py'),
        (Join-Path $repo 'engine/clearance_planner.py'),
        (Join-Path $repo 'coords.py'), (Join-Path $repo 'engine/robotron_fsm.py'),
        (Join-Path $repo 'engine/fsm_evolved_planner_v2_hunt.json'),
        (Join-Path $repo 'harness.py'), (Join-Path $repo 'hud_ocr.py'),
        (Join-Path $repo 'tools/run_production_game.py'),
        (Join-Path $repo 'tools/production_process.py'),
        (Join-Path $repo 'tools/production_decision_trace.py'),
        (Join-Path $repo 'tools/production_visual_trace.py')))
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $runDir 'manifest.json')
if ($PrepareOnly) {
    'prepared; not started' | Set-Content (Join-Path $runDir 'status.txt')
    Write-Output $runDir
    return
}

Add-Type @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class CollisionFocus {
    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint processId);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetWindowText(IntPtr hwnd, StringBuilder text, int count);
}
'@
$player = $null
$batch = $null
$status = 'starting'
try {
    if (-not $Production) {
    $player = Start-Process -FilePath $python -ArgumentList '-u','robotron/player.py' `
        -WorkingDirectory $codeRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runDir 'player.log') `
        -RedirectStandardError (Join-Path $runDir 'player.err.log')
    [void]$player.Handle
    Start-Sleep -Seconds 2
    if ($player.HasExited) { throw 'Gamepad server failed to start.' }
    }
    $batchArgs = @('-u','robotron/ab_yolo.py','run','--games',"$Games",
        '--arm',"$baseArm=$common,VSEARCH_COLLISION_SUBSTEPS=1",
        '--arm',"$fineArm=$common,$CandidateSettings",
        '--weights','robotron/runs/detect/robotron_yolo6/weights/best.pt',
        '--band','25','40','--timeout','3600')
    if ($Production) { $batchArgs += '--production' }
    $batch = Start-Process -FilePath $python -ArgumentList $batchArgs `
        -WorkingDirectory $codeRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runDir 'run.log') `
        -RedirectStandardError (Join-Path $runDir 'run.err.log')
    [void]$batch.Handle
    @{supervisor_pid=$PID; batch_pid=$batch.Id; player_pid=$player.Id} |
        ConvertTo-Json | Set-Content (Join-Path $runDir 'processes.json')
    $status = 'running'
    $status | Set-Content (Join-Path $runDir 'status.txt')
    $focusSeen = $false
    $lostSince = $null
    $lastFocusState = ''
    $xeniaIdentity = ''
    $deadline = (Get-Date).AddHours($MaxHours)
    while (-not $batch.HasExited) {
        if (Test-Path -LiteralPath (Join-Path $runDir 'STOP')) { throw 'STOP file requested.' }
        if ((Get-Date) -gt $deadline) { throw "$MaxHours-hour batch limit reached." }
        if ($null -ne $player -and $player.HasExited) { throw 'Gamepad server exited during the batch.' }
        $xenia = @(Get-Process xenia_canary -ErrorAction SilentlyContinue)
        # Reset across process generations even if the poll misses the gap.
        $identity = ($xenia | Sort-Object Id | ForEach-Object { "$($_.Id):$($_.StartTime.Ticks)" }) -join ','
        if ($identity -ne $xeniaIdentity) {
            $focusSeen = $false; $lostSince = $null
            $xeniaIdentity = $identity
        }
        $foreground = [CollisionFocus]::GetForegroundWindow()
        [uint32]$foregroundPid = 0
        [void][CollisionFocus]::GetWindowThreadProcessId($foreground, [ref]$foregroundPid)
        # MainWindowHandle is a heuristic; Xenia may own several windows.
        $focused = $foregroundPid -ne 0 -and $foregroundPid -in @($xenia.Id)
        $focusState = "$identity|$foreground|$foregroundPid|$focused"
        if ($focusState -ne $lastFocusState) {
            $windowTitle = [System.Text.StringBuilder]::new(1024)
            [void][CollisionFocus]::GetWindowText($foreground, $windowTitle, $windowTitle.Capacity)
            $foregroundProcess = Get-Process -Id $foregroundPid -ErrorAction SilentlyContinue
            @{
                time=(Get-Date).ToString('o'); xenia_identity=$identity
                foreground_hwnd=$foreground.ToInt64(); foreground_pid=$foregroundPid
                foreground_process=$foregroundProcess.ProcessName
                foreground_title=$windowTitle.ToString(); xenia_focused=$focused
                xenia_main_windows=@($xenia | ForEach-Object { $_.MainWindowHandle.ToInt64() })
            } | ConvertTo-Json -Compress | Add-Content (Join-Path $runDir 'focus.jsonl')
            $lastFocusState = $focusState
        }
        if ($xenia.Count -eq 0) {
            $focusSeen = $false; $lostSince = $null
        } else {
            if ($focused) { $focusSeen = $true; $lostSince = $null }
            elseif ($focusSeen) {
                if ($null -eq $lostSince) { $lostSince = Get-Date }
                elseif (((Get-Date) - $lostSince).TotalSeconds -gt 3) {
                    throw "Xenia lost focus for three seconds (foreground PID $foregroundPid); see focus.jsonl. Stopping controller and batch."
                }
            }
        }
        Start-Sleep -Milliseconds 500
        $batch.Refresh()
    }
    $batch.WaitForExit()
    if ($batch.ExitCode -ne 0) { throw "A/B harness exited with code $($batch.ExitCode)." }
    $status = 'harness finished; check completed game counts and errors before interpreting results'
} catch {
    $status = 'stopped: ' + $_.Exception.Message
} finally {
    if ($null -ne $batch -and -not $batch.HasExited) {
        & taskkill /PID $batch.Id /T /F | Out-Null
    }
    if ($null -ne $player -and -not $player.HasExited) {
        Stop-Process -Id $player.Id
    }
    $status | Set-Content (Join-Path $runDir 'status.txt')
    # ab_yolo.run currently has an unreachable stats call; analyse explicitly.
    Push-Location $codeRoot
    try {
        & $python -u robotron/ab_yolo.py stats --band 25 40 --since $since --baseline $baseArm 2>&1 |
            Out-File (Join-Path $runDir 'stats_late.txt') -Encoding utf8
        & $python -u robotron/ab_yolo.py stats --band 5 25 --since $since --baseline $baseArm 2>&1 |
            Out-File (Join-Path $runDir 'stats_early.txt') -Encoding utf8
    } finally { Pop-Location }
}
Write-Output "$runDir : $status"
