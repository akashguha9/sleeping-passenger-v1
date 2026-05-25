<#
.SYNOPSIS
    Run scripts/watchdog_refresh_stale_sources.py once. Wrapper used by the
    SleepingPassengerRefreshWatchdog scheduled task and operator manual runs.

.DESCRIPTION
    The watchdog checks the canonical stale-active source list and retries
    refresh_live_signals.py for any active source that has aged beyond the
    TTL. Optional / not-configured sources (e.g. Etherscan without a key)
    are explicitly excluded from the failure count.

    Exit-code semantics
    -------------------
    The Python watchdog uses distinct exit codes so this wrapper can tell
    "watchdog ran cleanly and upstreams are still stale" apart from
    "watchdog itself crashed":

      0  HEALTHY / IMPROVED_BUT_STALE   - PASS                  -> wrapper exits 0
      2  STALE_UNCHANGED                - PASS_WITH_STALE_SOURCES -> wrapper exits 0
      1  ERROR (or crash)               - FAIL                  -> wrapper exits 1

    Mapping STALE_UNCHANGED -> wrapper exit 0 prevents Windows Task
    Scheduler from showing the task as failed merely because upstreams
    are still down. The cockpit always shows the watchdog's own
    STALE_UNCHANGED status truthfully via runtime/refresh_watchdog_summary.json
    - this remapping is for Task Scheduler's LastTaskResult only.

    Log rotation
    ------------
    Before each run the wrapper rotates logs/refresh_watchdog.log when it
    exceeds -LogMaxBytes. Up to -LogBackupCount backups are kept
    (refresh_watchdog.log.1 ... refresh_watchdog.log.5). Defaults:
    5 MB per file, 5 backups (~30 MB max retained).

    Safety:
      * ADVISORY_ONLY. No broker contacted, no order placement, no
        execution route added.
      * The watchdog only invokes existing local Python scripts and reads
        SQLite metadata; it cannot unlock execution_gate.
      * Rotation only touches refresh_watchdog.log* files in the chosen
        LogPath directory. Unrelated logs are never moved or deleted.

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

.PARAMETER LogMaxBytes
    Rotate the log when it exceeds this many bytes. Default 5242880 (5 MB).

.PARAMETER LogBackupCount
    Maximum number of rotated backups to retain. Default 5.

.EXAMPLE
    PS> .\scripts\windows\run_refresh_watchdog_once.ps1
    PS> .\scripts\windows\run_refresh_watchdog_once.ps1 -TtlHours 6 -MaxRetries 3
    PS> .\scripts\windows\run_refresh_watchdog_once.ps1 -NoSleep
    PS> .\scripts\windows\run_refresh_watchdog_once.ps1 -LogMaxBytes 10485760 -LogBackupCount 3
#>

param(
    [int]$TtlHours = 6,
    [int]$MaxRetries = 3,
    [switch]$NoSleep,
    [string]$Sources = "",
    [string]$LogPath = "",
    [int]$LogMaxBytes = 5242880,
    [int]$LogBackupCount = 5
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

# -------------------------------------------------------------------------
# Log rotation - size-based, never touches unrelated files.
#
# Rotate when the active log exceeds $LogMaxBytes. We shift suffixes
# starting from the highest (drop refresh_watchdog.log.<backupCount>)
# down to .1, then rename the active log to refresh_watchdog.log.1.
# A new active log is created on the next write below.
# -------------------------------------------------------------------------
function Invoke-WatchdogLogRotation {
    param(
        [Parameter(Mandatory = $true)][string]$ActivePath,
        [Parameter(Mandatory = $true)][int]$MaxBytes,
        [Parameter(Mandatory = $true)][int]$BackupCount
    )
    if (-not (Test-Path $ActivePath)) { return }
    if ($MaxBytes -le 0 -or $BackupCount -le 0) { return }
    try {
        $size = (Get-Item $ActivePath -ErrorAction Stop).Length
    } catch {
        return
    }
    if ($size -lt $MaxBytes) { return }

    # Drop the oldest backup if it exists.
    $oldest = "$ActivePath.$BackupCount"
    if (Test-Path $oldest) {
        try { Remove-Item -Path $oldest -Force -ErrorAction Stop } catch {}
    }
    # Shift .N-1 -> .N down to .1.
    for ($i = $BackupCount - 1; $i -ge 1; $i--) {
        $src = "$ActivePath.$i"
        $dst = "$ActivePath.$($i + 1)"
        if (Test-Path $src) {
            try { Move-Item -Path $src -Destination $dst -Force -ErrorAction Stop } catch {}
        }
    }
    # Active -> .1
    try { Move-Item -Path $ActivePath -Destination "$ActivePath.1" -Force -ErrorAction Stop } catch {}
}

Invoke-WatchdogLogRotation -ActivePath $LogPath -MaxBytes $LogMaxBytes -BackupCount $LogBackupCount

$RuntimeDir = Join-Path $RepoRoot "runtime"
if (-not (Test-Path $RuntimeDir)) {
    New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null
}

$Timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
"[$Timestamp] refresh watchdog start: ttl=$TtlHours retries=$MaxRetries no_sleep=$NoSleep sources=$Sources log_max_bytes=$LogMaxBytes log_backup_count=$LogBackupCount" |
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

# -------------------------------------------------------------------------
# Exit-code mapping (see header for the full semantics):
#   rc=0 -> PASS
#   rc=2 -> PASS_WITH_STALE_SOURCES (cockpit still shows STALE_UNCHANGED)
#   rc=1 -> FAIL (watchdog itself crashed)
#   anything else -> FAIL with explicit rc echoed
# -------------------------------------------------------------------------
if ($rc -eq 0) {
    "[$Timestamp] refresh watchdog completed PASS rc=0" |
        Out-File -FilePath $LogPath -Append -Encoding utf8
    Write-Output "PASS"
    exit 0
}
elseif ($rc -eq 2) {
    "[$Timestamp] refresh watchdog completed PASS_WITH_STALE_SOURCES rc=2 status=STALE_UNCHANGED (cockpit truth preserved; wrapper exits 0 to avoid scheduler-failure noise)" |
        Out-File -FilePath $LogPath -Append -Encoding utf8
    Write-Output "PASS_WITH_STALE_SOURCES"
    exit 0
}
elseif ($rc -eq 1) {
    "[$Timestamp] refresh watchdog completed FAIL rc=1 (watchdog crashed - investigate)" |
        Out-File -FilePath $LogPath -Append -Encoding utf8
    Write-Output "FAIL rc=1"
    exit 1
}
else {
    "[$Timestamp] refresh watchdog completed FAIL rc=$rc (unexpected exit code)" |
        Out-File -FilePath $LogPath -Append -Encoding utf8
    Write-Output "FAIL rc=$rc"
    exit $rc
}
