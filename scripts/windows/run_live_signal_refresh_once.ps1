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

# Force UTF-8 across the wrapper so PowerShell does not double-encode python
# stdout into UTF-16LE (which produced "S l e e p i n g" / "?" artefacts in
# the rotated log file before Sprint 10B).
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
    # Older console hosts can refuse this; fall back silently. The log will
    # still be appended via Out-File -Encoding utf8 below.
}
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")

if ([string]::IsNullOrWhiteSpace($LogPath)) {
    $LogPath = Join-Path $RepoRoot "logs\live_signal_refresh.log"
}

$LogDir = Split-Path -Parent $LogPath
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# Enable the built-in SEC EDGAR 7-stock watchlist for the scheduled
# refresh (data-pipeline sprint: sec_edgar previously skipped every run
# with "No CIK provided"). No secret involved — public EDGAR data.
if ([string]::IsNullOrWhiteSpace($env:SEC_DEFAULT_WATCHLIST)) {
    $env:SEC_DEFAULT_WATCHLIST = "1"
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

$rc = 0
try {
    # Capture python stdout/stderr as strings, then append in a single UTF-8
    # write. Tee-Object on Windows PowerShell 5.1 has no -Encoding parameter
    # and defaults to UTF-16LE for file output, which corrupted prior logs.
    $pyOut = & python @pyArgs 2>&1
    $rc = $LASTEXITCODE
    if ($null -ne $pyOut) {
        $pyOut | Out-File -FilePath $LogPath -Append -Encoding utf8
        $pyOut | ForEach-Object { Write-Output $_ }
    }
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

# --- longitudinal research-data capture (data-pipeline sprint) ---------------
# Appends prediction-market probability observations to the append-only
# ledger, freezes the event->equity exposure map when changed, matures
# real PEG observations, and refreshes the readiness dashboard.  Each
# step is isolated: a failure here is logged but NEVER changes the
# refresh exit code — one broken step must not destroy the day's capture
# or the existing signal refresh.
if ($WriteMode) {
    $captureSteps = @(
        @("scripts/prediction_market_state_capture.py", "--write"),
        @("scripts/run_quant_peg_dataset.py"),
        @("scripts/quant_data_readiness_report.py")
    )
    foreach ($step in $captureSteps) {
        try {
            $stepOut = & python @step 2>&1
            $stepRc = $LASTEXITCODE
            "[$Timestamp] capture step $($step[0]) rc=$stepRc" |
                Out-File -FilePath $LogPath -Append -Encoding utf8
            if ($null -ne $stepOut) {
                $stepOut | Out-File -FilePath $LogPath -Append -Encoding utf8
            }
        } catch {
            "[$Timestamp] capture step $($step[0]) threw: $($_.Exception.Message)" |
                Out-File -FilePath $LogPath -Append -Encoding utf8
        }
    }
}

exit $rc
