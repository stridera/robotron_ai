# Exercise the supervisor's actual polling block without launching an emulator.
$ErrorActionPreference = 'Stop'
Add-Type @'
using System;
using System.Text;
public static class CollisionFocus {
    public static uint Owner = 10;
    public static IntPtr Window = new IntPtr(222);
    public static IntPtr GetForegroundWindow() { return Window; }
    public static uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid) { pid = Owner; return 1; }
    public static int GetWindowText(IntPtr hwnd, StringBuilder text, int count) { text.Append("test"); return 4; }
}
'@
function Get-Process {
    param([string]$Name, [int]$Id, $ErrorAction)
    if ($Name -eq 'xenia_canary') { return $script:fakeXenia }
    return [pscustomobject]@{ ProcessName='test-foreground' }
}
function Assert-True($Condition, $Message) {
    if (-not $Condition) { throw $Message }
}
$source = Get-Content (Join-Path $PSScriptRoot '../tools/run_collision_ab.ps1') -Raw
$start = $source.IndexOf('        $xenia = @(Get-Process')
$end = $source.IndexOf('        Start-Sleep -Milliseconds 500', $start)
Assert-True ($start -ge 0 -and $end -gt $start) 'Polling block missing'
$poll = [scriptblock]::Create($source.Substring($start, $end - $start))
$runDir = Join-Path ([IO.Path]::GetTempPath()) ('robotron-focus-test-' + [guid]::NewGuid())
[void](New-Item -ItemType Directory -Path $runDir)
$script:fakeXenia = [pscustomobject]@{
    Id=10; StartTime=[datetime]'2026-09-09'; MainWindowHandle=[intptr]111
}
$focusSeen=$false; $lostSince=$null; $lastFocusState=''; $xeniaIdentity=''
. $poll
Assert-True $focusSeen 'Another window owned by Xenia must count as focused'

# PID replacement with no observed empty poll must disarm the old timer.
$script:fakeXenia.Id=11
[CollisionFocus]::Owner=99
$lostSince=(Get-Date).AddSeconds(-10)
. $poll
Assert-True (-not $focusSeen -and $null -eq $lostSince) 'Restart retained old focus state'

[CollisionFocus]::Owner=11
. $poll
Assert-True $focusSeen 'New process did not arm after acquiring focus'
[CollisionFocus]::Owner=99
. $poll
Assert-True ($null -ne $lostSince) 'External foreground did not start loss timer'
[CollisionFocus]::Owner=11
. $poll
Assert-True ($null -eq $lostSince) 'Recovered focus did not clear timer'
[CollisionFocus]::Owner=99
$lostSince=(Get-Date).AddSeconds(-10)
$stopped=$false
try { . $poll } catch {
    if ($_.Exception.Message -notlike '*foreground PID 99*') { throw }
    $stopped=$true
}
Assert-True $stopped 'Sustained external focus did not stop the batch'
$events = @(Get-Content (Join-Path $runDir 'focus.jsonl') | ConvertFrom-Json)
Assert-True ($events[-1].foreground_pid -eq 99) 'Diagnostic omitted actual foreground owner'
Assert-True ($events[0].xenia_main_windows[0] -eq 111) 'Diagnostic omitted main-window handle'
Remove-Item -LiteralPath (Join-Path $runDir 'focus.jsonl')
Remove-Item -LiteralPath $runDir
'PASS: owned secondary window, restart, acquisition, transient loss, sustained loss, diagnostics'
