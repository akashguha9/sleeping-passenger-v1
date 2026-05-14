<#
.SYNOPSIS
    Run scripts/refresh_live_signals.py once. Manual debug runner.

.DESCRIPTION
    Wraps the local refresh orchestrator with no secrets and predictable
    logging. Default mode is --dry-run (safe: no signal_events written; a
    metadata row is still recorded so the API can report attempt freshness).

    Pass -WriteMode to invoke "--write" which is the explicit opt-in mode
    used by the every-6-hour scheduled task. There is no broker code path
    anywhere on this script -- the orchestrator never connects to a broker,
    never executes a trade, and never increments ai_execution_count.

.PARAMETER WriteMode
    If supplied, runs the orchestrator with --write instead of --dry-run.

.PARAMETER Sources
    Comma-separated source keys to limit the refresh.
    Example: -Sources "newsapi,event_registry".

.PARAMETER LogPath
    Where to append log output. Default: "<repo>\logs\live_signal_refresh.log".

.EXAMPLE
    PS> .\scripts\windows\run_live_signal_refresh_once.ps1
    PS> .\scripts\windows\run_live_signal_refresh_once.ps1 -WriteMode
    PS> .\scripts\windows\run_live_signal_refresh_once.ps1 -Sources "polymarket,gdelt"
#>

param(
    [switch]$WriteMode,
    [string]$Sources = "",
    [string]$LogPath = ""
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")

if ([string]::IsNullOrWhiteSpace($LogPath)) {
    $LogPath = Join-Path $RepoRoot "logs\live_signal_refresh.log"
}

$LogDir = Split-Path -Parent $LogPath
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$Mode = if ($WriteMode) { "--write" } else { "--dry-run" }
$Timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")

"[$Timestamp] live signal refresh start: mode=$Mode sources=$Sources" |
    Out-File -FilePath $LogPath -Append -Encoding utf8

Set-Location $RepoRoot

$pyArgs = @("scripts/refresh_live_signals.py", $Mode)
if (-not [string]::IsNullOrWhiteSpace($Sources)) {
    $pyArgs += "--sources"
    $pyArgs += $Sources
}

try {
    & python @pyArgs 2>&1 | Tee-Object -FilePath $LogPath -Append
    $rc = $LASTEXITCODE
} catch {
    $err = $_.Exception.Message
    "[$Timestamp] orchestrator threw: $err" |
        Out-File -FilePath $LogPath -Append -Encoding utf8
    exit 1
}

if ($rc -eq 0) {
    "[$Timestamp] live signal refresh completed PASS rc=0" |
        Out-File -FilePath $LogPath -Append -Encoding utf8
    Write-Output "PASS"
} else {
    "[$Timestamp] live signal refresh completed FAIL rc=$rc" |
        Out-File -FilePath $LogPath -Append -Encoding utf8
    Write-Output "FAIL rc=$rc"
}
exit $rc
