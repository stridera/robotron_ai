param(
    [string]$TrainingRun = 'residual_net_20260909_v2',
    [int]$XeniaGames = 8,
    [string]$RunName = 'evening_20260909',
    [ValidateRange(0.25,8)][double]$MaxHours = 4
)
$ErrorActionPreference = 'Stop'
$env:PSModulePath = (Join-Path $PSHOME 'Modules') + ';' + $env:PSModulePath
Import-Module Microsoft.PowerShell.Utility -ErrorAction Stop
$repo = Split-Path $PSScriptRoot -Parent
$codeRoot = Split-Path $repo -Parent
$winPython = Join-Path $codeRoot '.venv/Scripts/python.exe'
$linuxPython = '/home/strider/Code/robotron-rl/.venv-collision/bin/python'
$linuxRepo = '/mnt/c/Users/strid/code/robotron_ai'
$runDir = Join-Path $repo "logs/$RunName"
New-Item -ItemType Directory -Path $runDir | Out-Null
$deadline = (Get-Date).AddHours($MaxHours)
$state = [ordered]@{ running=$true; stage='waiting for training'; training=$TrainingRun;
    started=(Get-Date).ToString('o'); deadline=$deadline.ToString('o'); results=@() }
function Save-State {
    $state.updated = (Get-Date).ToString('o')
    $state | ConvertTo-Json -Depth 12 | Set-Content (Join-Path $runDir 'state.json')
    @{running=$state.running; stage=$state.stage; supervisor_pid=$PID;
      state_file="logs/$RunName/state.json"; report='DAY_REPORT.md'} |
        ConvertTo-Json | Set-Content (Join-Path $repo 'logs/day_active.json')
}
function Record-Result($Phase, $Status, $Artifacts, $Detail) {
    $state.results += @{phase=$Phase; status=$Status; artifacts=$Artifacts; detail=$Detail}
    Save-State
    $line = '- {0}: {1}; artifacts `{2}`. {3}' -f $Phase, $Status, $Artifacts, $Detail
    Add-Content -LiteralPath (Join-Path $repo 'DAY_REPORT.md') -Value $line
    Write-Output $line
}
function Run-Mame($Prefix, $Games, $Candidate, $Model, $Sample, $Seed) {
    $state.stage = $Prefix; Save-State
    $argsList = @('-d','Ubuntu','--',$linuxPython,'-u',
        "$linuxRepo/tools/run_collision_mame_fresh.py", '--prefix',$Prefix,
        '--games',"$Games",'--workers','12','--candidate-name',$Candidate,
        '--candidate-env',"LAB_RESIDUAL_MODEL=$Model",
        '--candidate-env',"LAB_RESIDUAL_SAMPLE=$Sample",'--seed-base',"$Seed")
    $process = Start-Process -FilePath 'wsl.exe' -ArgumentList $argsList -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runDir "$Prefix.out") `
        -RedirectStandardError (Join-Path $runDir "$Prefix.err")
    # Windows PowerShell can lose ExitCode for redirected Start-Process jobs
    # unless the native handle is retained before the child exits.
    [void]$process.Handle
    try {
        while (-not $process.HasExited) {
            if ((Get-Date) -gt $deadline -or (Test-Path (Join-Path $runDir 'STOP'))) {
                Set-Content (Join-Path $repo "logs/$Prefix/STOP") 'evening supervisor stop'
                if (-not $process.WaitForExit(20000)) { throw 'MAME did not acknowledge STOP.' }
                throw 'Evening time limit or STOP reached.'
            }
            Start-Sleep -Seconds 5
            $process.Refresh()
        }
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) { throw "MAME stage exited $($process.ExitCode)." }
        $summary = Get-Content (Join-Path $repo "logs/$Prefix/summary.json") -Raw | ConvertFrom-Json
        if (-not $summary.complete) { throw 'MAME summary is incomplete.' }
        foreach ($arm in $summary.arms.PSObject.Properties.Value) {
            if ($arm.completed_valid_games -ne $Games) { throw 'MAME valid episode count mismatch.' }
        }
        return $summary
    } finally {
        if (-not $process.HasExited) {
            Set-Content (Join-Path $repo "logs/$Prefix/STOP") 'supervisor cleanup'
            [void]$process.WaitForExit(20000)
        }
    }
}
Save-State
Add-Content (Join-Path $repo 'DAY_REPORT.md') "`n## Automatic evening stages`n"
try {
    $trainingStatusPath = Join-Path $repo "logs/$TrainingRun/status.json"
    while ($true) {
        if (Test-Path (Join-Path $runDir 'STOP')) {
            Set-Content (Join-Path $repo "logs/$TrainingRun/STOP") 'supervisor STOP'
            throw 'STOP requested while waiting for training; training STOP written.'
        }
        $live = @(Get-CimInstance Win32_Process -Filter "Name='wsl.exe'" |
            Where-Object { $_.CommandLine -like '*train_champion_residual.py*' -and
                           $_.CommandLine -like "*$TrainingRun*" })
        if ($live.Count -eq 0) { break }
        if ((Get-Date) -gt $deadline.AddMinutes(-3)) {
            Set-Content (Join-Path $repo "logs/$TrainingRun/STOP") 'evening time limit'
        }
        Start-Sleep -Seconds 10
    }
    $training = Get-Content $trainingStatusPath -Raw | ConvertFrom-Json
    if ($training.running) { throw 'Training process ended without a completed status record.' }
    $modelWin = Join-Path $repo "logs/$TrainingRun/actor_final.npz"
    if (-not (Test-Path $modelWin)) { throw 'Final actor missing.' }
    Record-Result 'Training' $(if ($training.complete) {'complete'} else {'time-limited'}) `
        "logs/$TrainingRun" ("{0} decisions; {1:N0} seconds." -f $training.steps, $training.elapsed_s)
    & $winPython (Join-Path $repo 'tools/inspect_residual_models.py') (Join-Path $repo "logs/$TrainingRun") |
        Set-Content (Join-Path $runDir 'behavior_audit.out')
    if ($LASTEXITCODE -ne 0) { throw 'Actor behavior audit failed.' }
    $audit = Get-Content (Join-Path $repo "logs/$TrainingRun/behavior_audit.json") -Raw | ConvertFrom-Json
    $final = $audit | Where-Object model -eq 'actor_final.npz'
    $model = "$linuxRepo/logs/$TrainingRun/actor_final.npz"
    if ($final.greedy_proven_noop) {
        Record-Result 'Greedy actor' 'proved identical to champion' "logs/$TrainingRun/behavior_audit.json" `
            'Both alternative logits are globally below keep; no gameplay needed.'
    } else {
        $smoke = Run-Mame 'residual_greedy_smoke_20260909' 8 'greedy' $model 0 91026900
        Record-Result 'Greedy smoke' 'complete' 'logs/residual_greedy_smoke_20260909' 'Diagnostic only, 8 games per arm.'
    }
    $summary = Run-Mame 'residual_sampled_screen_20260909' 144 'sampled' $model 1 91027000
    $effect = $summary.comparisons_to_baseline.PSObject.Properties.Value | Select-Object -First 1
    Record-Result 'Sampled actor screen' 'complete' 'logs/residual_sampled_screen_20260909' `
        ('NET delta {0:F4}, 95% CI [{1:F4}, {2:F4}].' -f $effect.net_delta, $effect.bootstrap_95[0], $effect.bootstrap_95[1])
    if ($effect.net_delta -gt .03) {
        if (($deadline - (Get-Date)).TotalHours -gt 2) {
            $confirmation = Run-Mame 'residual_sampled_confirm_20260909' 576 'sampled' $model 1 91028000
            $confirmEffect = $confirmation.comparisons_to_baseline.PSObject.Properties.Value | Select-Object -First 1
            Record-Result 'Sampled actor confirmation' 'complete' 'logs/residual_sampled_confirm_20260909' `
                ('NET delta {0:F4}, 95% CI [{1:F4}, {2:F4}]. No automatic promotion.' -f $confirmEffect.net_delta,
                  $confirmEffect.bootstrap_95[0], $confirmEffect.bootstrap_95[1])
        } else {
            Record-Result 'Sampled actor confirmation' 'not started: insufficient time' '' 'Positive screen remains unconfirmed.'
        }
    } else {
        Record-Result 'Sampled actor confirmation' 'not warranted by screen' '' 'Predeclared NET delta > +0.03 entry threshold not met.'
    }
    $remainingHours = ($deadline - (Get-Date)).TotalHours
    if ($remainingHours -gt .75 -and -not (Test-Path (Join-Path $runDir 'STOP'))) {
        $mamePids = @(& wsl -d Ubuntu -- pgrep -x mame)
        if ($mamePids.Count -gt 0) { throw 'MAME still running; Xenia not started.' }
        $state.stage = 'production Xenia tracking comparison'; Save-State
        $limit = [Math]::Min(2.5, $remainingHours - .05).ToString('F2', [Globalization.CultureInfo]::InvariantCulture)
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo 'tools/run_collision_ab.ps1') `
            -Production -Games $XeniaGames -MaxWave 40 -CandidateName timed -CandidateSettings ROBOTRON_TRACK_TIME=1 `
            -RunName production_timing_20260909 -MaxHours $limit |
            Set-Content (Join-Path $runDir 'xenia_supervisor.out')
        $status = Get-Content (Join-Path $repo 'logs/production_timing_20260909/status.txt') -Raw
        Record-Result 'Production Xenia comparison' $status.Trim() 'logs/production_timing_20260909' `
            'Check per-arm completed games, HUD/oracle agreement and band metrics before interpreting.'
    } else {
        Record-Result 'Production Xenia comparison' 'not started: time limit or STOP' '' ''
    }
    $state.stage = 'queue ended; review stage results'
} catch {
    Record-Result $state.stage 'stopped with error' "logs/$RunName" $_.Exception.Message
    $state.stage = 'queue stopped with error'
} finally {
    $state.running = $false
    Save-State
}
