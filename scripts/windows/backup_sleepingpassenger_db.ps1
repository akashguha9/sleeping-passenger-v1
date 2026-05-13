# backup_sleepingpassenger_db.ps1
#
# Operator-friendly wrapper around scripts/backup_db.py for Windows.  Drop
# into Task Scheduler for daily automated SQLite backups -- safe to run
# while the API server is up because backup_db.py uses the SQLite hot-copy
# backup API.
#
# Safety:
#   * Never deletes the source DB.
#   * Never deletes old backups.  (Retention is a separate concern; see
#     docs/WINDOWS_BACKUP_TASK.md for guidance.)
#   * Does not print env values or secrets.
#   * Exits non-zero on failure so Task Scheduler can flag the run.
#
# Usage:
#   .\scripts\windows\backup_sleepingpassenger_db.ps1
#   .\scripts\windows\backup_sleepingpassenger_db.ps1 -Label predemo
#   .\scripts\windows\backup_sleepingpassenger_db.ps1 -JsonOutput
#
# Exit codes:
#   0  -> backup succeeded
#   1  -> backup failed (see error output)
#   2  -> invalid argument (e.g. bad label)
#   3  -> Python interpreter not found
#   4  -> script not run from repo root (no scripts/backup_db.py found)

[CmdletBinding()]
param(
    [string]$Label = "",
    [string]$DbPath = "",
    [string]$BackupDir = "",
    [switch]$JsonOutput
)

$ErrorActionPreference = "Stop"

# Resolve the repo root: this script lives at scripts/windows/, so two
# directory levels up.
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$BackupScript = Join-Path $RepoRoot "scripts\backup_db.py"

if (-not (Test-Path $BackupScript)) {
    Write-Error "Could not find scripts/backup_db.py under $RepoRoot. Run this from the sleeping-passenger-v1 repo."
    exit 4
}

# Pick a Python interpreter.  Prefer the launcher 'py' if available; fall
# back to 'python'.  We do NOT auto-install Python.
$PythonCmd = $null
foreach ($candidate in @("py", "python", "python3")) {
    $resolved = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($null -ne $resolved) {
        $PythonCmd = $resolved.Source
        break
    }
}
if ($null -eq $PythonCmd) {
    Write-Error "No Python interpreter found on PATH. Install Python 3.11+ and try again."
    exit 3
}

# Build the argument list.  Anything user-supplied is passed through to
# backup_db.py which does its own validation (e.g. label charset).
$BackupArgs = @($BackupScript)
if ($Label -ne "") {
    $BackupArgs += @("--label", $Label)
}
if ($DbPath -ne "") {
    $BackupArgs += @("--db-path", $DbPath)
}
if ($BackupDir -ne "") {
    $BackupArgs += @("--backup-dir", $BackupDir)
}
if ($JsonOutput) {
    $BackupArgs += @("--json")
}

# Set working dir to repo root so MVP_DB_PATH / default resolution works.
Push-Location $RepoRoot
try {
    & $PythonCmd @BackupArgs
    $exitCode = $LASTEXITCODE
} finally {
    Pop-Location
}

if ($exitCode -eq 0) {
    if (-not $JsonOutput) {
        Write-Host "Backup complete." -ForegroundColor Green
    }
    exit 0
} else {
    if (-not $JsonOutput) {
        Write-Host "Backup failed with exit code $exitCode." -ForegroundColor Red
    }
    exit $exitCode
}
