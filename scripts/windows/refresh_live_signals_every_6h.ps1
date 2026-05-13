<#
.SYNOPSIS
    Run the sleeping-passenger live source refresh orchestrator on a 6-hour cadence.

.DESCRIPTION
    Intended to be registered as a Windows Task Scheduler task with a 6-hour
    trigger (00:00, 06:00, 12:00, 18:00 local time).

    Default mode is --dry-run. To actually persist signal events, pass
    -WriteMode (which translates to "--write" on the orchestrator).

    Safety guarantees:
      * No secrets are written to disk by this wrapper. Anything the orchestrator
        emits is already redacted.
      * --write is opt-in only. Running this script with no arguments is a safe
        plan-and-dry-run that calls no live adapter.
      * The orchestrator never calls a broker or executes a trade.

.PARAMETER WriteMode
    If supplied, runs the orchestrator with --write instead of --dry-run.

.PARAMETER SourceKey
    Single source key (e.g. polymarket) or "all". Default: "all".

.PARAMETER LogPath
    Where to append log output. Default: "<repo>\logs\live_refresh.log".

.EXAMPLE
    PS> .\scripts\windows\refresh_live_signals_every_6h.ps1

.EXAMPLE
    PS> .\scripts\windows\refresh_live_signals_every_6h.ps1 -SourceKey polymarket

.EXAMPLE
    PS> .\scripts\windows\refresh_live_signals_every_6h.ps1 -WriteMode

.NOTES
    To register this as a recurring task:

        schtasks /Create /TN "SleepingPassengerLiveRefresh6h" `
            /TR "powershell -NoProfile -ExecutionPolicy Bypass -File `"$PWD\scripts\windows\refresh_live_signals_every_6h.ps1`"" `
            /SC HOURLY /MO 6 /F

    To remove it:

        schtasks /Delete /TN "SleepingPassengerLiveRefresh6h" /F
#>

param(
    [switch]$WriteMode,
    [string]$SourceKey = "all",
    [string]$LogPath = ""
)

$ErrorActionPreference = "Stop"

# Resolve repo root from this script's path (scripts\windows\refresh_..._6h.ps1).
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")

if ([string]::IsNullOrWhiteSpace($LogPath)) {
    $LogPath = Join-Path $RepoRoot "logs\live_refresh.log"
}

# Make sure the log directory exists.
$LogDir = Split-Path -Parent $LogPath
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$Mode = if ($WriteMode) { "--write" } else { "--dry-run" }
$Timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")

"[$Timestamp] starting live refresh: source=$SourceKey mode=$Mode" |
    Out-File -FilePath $LogPath -Append -Encoding utf8

Set-Location $RepoRoot

try {
    & python "scripts/run_live_refresh.py" `
        "--source" $SourceKey `
        $Mode 2>&1 |
        Tee-Object -FilePath $LogPath -Append
    $rc = $LASTEXITCODE
} catch {
    $err = $_.Exception.Message
    "[$Timestamp] orchestrator threw: $err" |
        Out-File -FilePath $LogPath -Append -Encoding utf8
    exit 1
}

if ($rc -eq 0) {
    "[$Timestamp] live refresh completed PASS rc=0" |
        Out-File -FilePath $LogPath -Append -Encoding utf8
    Write-Output "PASS"
} else {
    "[$Timestamp] live refresh completed FAIL rc=$rc" |
        Out-File -FilePath $LogPath -Append -Encoding utf8
    Write-Output "FAIL rc=$rc"
}
exit $rc
