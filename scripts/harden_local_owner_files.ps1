# Harden local owner-private files on Windows (NTFS ACLs).
#
# Purpose: restrict .env, runtime databases, logs, and local backups to the
# current Windows user. Advisory-only MVP; this script never deletes data,
# never touches git state, and never transmits anything.
#
# Honest scope (see SECURITY.md): API auth cannot protect against malware
# or another process running as YOUR user. Real local protection requires:
#   * a Windows account password,
#   * BitLocker / device encryption,
#   * never syncing .env or the DB into public cloud folders unencrypted.
#
# Usage (PowerShell):
#   .\scripts\harden_local_owner_files.ps1            # DRY RUN (default)
#   .\scripts\harden_local_owner_files.ps1 -Apply     # actually set ACLs
#
[CmdletBinding()]
param(
    # Dry-run is the default; nothing changes unless -Apply is passed.
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$CurrentUser = "$env:USERDOMAIN\$env:USERNAME"

Write-Host "=== Local owner-file hardening (advisory-only MVP) ==="
Write-Host "Repo root    : $RepoRoot"
Write-Host "Current user : $CurrentUser"
Write-Host "Mode         : $(if ($Apply) { 'APPLY' } else { 'DRY RUN (pass -Apply to change ACLs)' })"
Write-Host ""

if (-not $IsWindows -and $PSVersionTable.PSEdition -ne "Desktop") {
    Write-Warning "Not running on Windows. NTFS ACL hardening does not apply."
    Write-Host  "On POSIX run instead:  chmod 600 .env; chmod -R o-rwx runtime logs backup_local_state 2>/dev/null"
    exit 0
}

# Warn if the repo lives outside the user profile (e.g. C:\repos shared
# folder or a cloud-synced path) — broader default ACLs / sync exposure.
if (-not $RepoRoot.StartsWith($env:USERPROFILE, [System.StringComparison]::OrdinalIgnoreCase)) {
    Write-Warning "Repo is OUTSIDE your user profile ($env:USERPROFILE)."
    Write-Warning "Default ACLs may grant other local users read access, and shared/cloud paths can sync secrets."
}
foreach ($cloudHint in @("OneDrive", "Dropbox", "Google Drive", "iCloudDrive")) {
    if ($RepoRoot -like "*$cloudHint*") {
        Write-Warning "Repo path contains '$cloudHint' — .env and the SQLite DB may be syncing to a cloud account. Move the repo or exclude these files from sync."
    }
}

# Sensitive paths: restrict to the current user. Existence is optional.
$Targets = @(
    (Join-Path $RepoRoot ".env"),
    (Join-Path $RepoRoot "runtime"),
    (Join-Path $RepoRoot "logs"),
    (Join-Path $RepoRoot "backup_local_state"),
    (Join-Path $RepoRoot "private_backups")
)

$changed = 0
$skipped = 0
foreach ($target in $Targets) {
    if (-not (Test-Path $target)) {
        Write-Host "[skip]  $target (not present)"
        $skipped++
        continue
    }
    Write-Host "[found] $target"
    # icacls plan: remove inherited ACEs, grant only the current user.
    #   /inheritance:r  strip inherited permissions
    #   /grant:r        replace grants with exactly this list
    #   (OI)(CI)F       full control, inherited by children (dirs only)
    $isDir = (Get-Item $target).PSIsContainer
    $grant = if ($isDir) { "${CurrentUser}:(OI)(CI)F" } else { "${CurrentUser}:F" }
    if ($Apply) {
        & icacls $target /inheritance:r /grant:r $grant | ForEach-Object { Write-Host "        $_" }
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "icacls failed on $target (exit $LASTEXITCODE) — no changes made to it."
        } else {
            $changed++
        }
    } else {
        Write-Host "        would run: icacls `"$target`" /inheritance:r /grant:r `"$grant`""
    }
}

Write-Host ""
Write-Host "=== Report ==="
Write-Host "Targets present  : $($Targets.Count - $skipped)"
Write-Host "Targets hardened : $changed $(if (-not $Apply) { '(dry run — none changed)' })"
Write-Host ""
Write-Host "Verify ACLs:    icacls .env ; icacls runtime"
Write-Host "Reminder: enable BitLocker and a Windows account password; this"
Write-Host "script narrows file ACLs but cannot stop same-user processes."
exit 0
