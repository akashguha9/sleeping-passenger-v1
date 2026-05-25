<#
.SYNOPSIS
    Run scripts/watchdog_refresh_stale_sources.py once. Wrapper used by the
    SleepingPassengerRefreshWatchdog scheduled task and operator manual runs.

.DESCRIPTION
    The watchdog checks the canonical stale-active source list and retries
    refresh_live_signals.py for any active source that has aged beyond the
    TTL. Optional / not-configured sources (e.g. Etherscan without a key)
    are explicitly excluded from the failure count.

    Safety:
      * ADVISORY_ONLY. No broker contacted, no order placement, no
        execution route added.
      * The watchdog only invokes existing local Python scripts and reads
        SQLite metadata; it cannot unlock execution_gate.

.PARAMETER TtlHours
    TTL in hours. Default 6.

.PARAMETER MaxRetries
    Maximum retry attempts. Default 3.

.PARAMETER NoSleep
    Skip sleeps between retries (useful for manual smoke checks).

.PARAMETER Sources
    Optional comma-separated source filter.

.PARAMETER LogPath
    Where to append log output. Default "<repo>\logs\refresh_watchdog.log".

.EXAMPLE
    PS> .\scripts\windows\run_refresh_watchdog_once.ps1
    PS> .\scripts\windows\run_refresh_watchdog_once.ps1 -TtlHours 6 -MaxRetries 3
    PS> .\scripts\windows\run_refresh_watchdog_once.ps1 -NoSleep
#>

param(
    [int]$TtlHours = 6,
    [int]$MaxRetries = 3,
    [switch]$NoSleep,
    [string]$Sources = "",
    [string]$LogPath = ""
)

$ErrorActionPreference = "Stop"

# Force UTF-8 so PowerShell does not double-encode python stdout into UTF-16LE.
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch {}
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")

if ([string]::IsNullOrWhiteSpace($LogPath)) {
    $LogPath = Join-Path $RepoRoot "logs\refresh_watchdog.log"
}

$LogDir = Split-Path -Parent $LogPath
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$RuntimeDir = Join-Path $RepoRoot "runtime"
if (-not (Test-Path $RuntimeDir)) {
    New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null
}

$Timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
"[$Timestamp] refresh watchdog start: ttl=$TtlHours retries=$MaxRetries no_sleep=$NoSleep sources=$Sources" |
    Out-File -FilePath $LogPath -Append -Encoding utf8

Set-Location $RepoRoot

$pyArgs = @(
    "scripts/watchdog_refresh_stale_sources.py",
    "--ttl-hours", $TtlHours,
    "--max-retries", $MaxRetries
)
if ($NoSleep) { $pyArgs += "--no-sleep" }
if (-not [string]::IsNullOrWhiteSpace($Sources)) {
    $pyArgs += "--sources"
    $pyArgs += $Sources
}

$rc = 0
try {
    $pyOut = & python @pyArgs 2>&1
    $rc = $LASTEXITCODE
    if ($null -ne $pyOut) {
        $pyOut | Out-File -FilePath $LogPath -Append -Encoding utf8
        $pyOut | ForEach-Object { Write-Output $_ }
    }
} catch {
    $err = $_.Exception.Message
    "[$Timestamp] watchdog threw: $err" |
        Out-File -FilePath $LogPath -Append -Encoding utf8
    exit 1
}

$SummaryPath = Join-Path $RuntimeDir "refresh_watchdog_summary.json"
if (-not (Test-Path $SummaryPath)) {
    "[$Timestamp] WARNING: summary file missing at $SummaryPath" |
        Out-File -FilePath $LogPath -Append -Encoding utf8
}

if ($rc -eq 0) {
    "[$Timestamp] refresh watchdog completed PASS rc=0" |
        Out-File -FilePath $LogPath -Append -Encoding utf8
    Write-Output "PASS"
} else {
    "[$Timestamp] refresh watchdog completed FAIL rc=$rc" |
        Out-File -FilePath $LogPath -Append -Encoding utf8
    Write-Output "FAIL rc=$rc"
}
exit $rc
