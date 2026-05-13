<#
.SYNOPSIS
Start the Next.js frontend directly on port 80 so http://sleepingpassenger/ works.

Sibling to the existing reverse-proxy approach (start_sleepingpassenger_proxy.ps1).
Unlike that script, this one runs Next.js itself on port 80 — no proxy hop.

Preflight checks (non-destructive):
  1. Verifies C:\Windows\System32\drivers\etc\hosts contains "127.0.0.1 sleepingpassenger".
     If missing, prints the exact Administrator command to add it. Does not modify
     the hosts file from this script.
  2. Checks whether port 80 is already in use. If so, prints the owning PID and the
     exact command to stop it. Does not kill anything automatically.
  3. If both checks pass, launches `npm run dev:sleepingpassenger` from frontend/.

NOTE: Binding port 80 on Windows requires Administrator privileges.
Run this script from an elevated PowerShell session.

Fallback: if port 80 cannot be used, just run `npm run dev` and open http://localhost:3000.
#>

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
)

$ErrorActionPreference = "Stop"

$HostsFile    = "C:\Windows\System32\drivers\etc\hosts"
$FrontendDir  = Join-Path $RepoRoot "frontend"
$RequiredHost = "sleepingpassenger"
$RequiredLine = "127.0.0.1 $RequiredHost"

Write-Host "=== sleepingpassenger local frontend (direct port 80) ===" -ForegroundColor Cyan
Write-Host ""

# --- 1. Hosts file check ----------------------------------------------------
Write-Host "[1/3] Checking hosts file for: $RequiredLine"
$hostsHasEntry = $false
try {
    $hostsLines = Get-Content $HostsFile -Encoding UTF8 -ErrorAction Stop
    $pattern    = "^\s*127\.0\.0\.1\s+$([regex]::Escape($RequiredHost))\s*(\s|#|$)"
    if ($hostsLines | Where-Object { $_ -match $pattern }) {
        $hostsHasEntry = $true
    }
} catch {
    Write-Host "      Could not read $HostsFile - $($_.Exception.Message)" -ForegroundColor Yellow
}

if ($hostsHasEntry) {
    Write-Host "      OK: hosts entry present." -ForegroundColor Green
} else {
    Write-Host "      MISSING: hosts entry not found." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "      Open a NEW PowerShell as Administrator and run:" -ForegroundColor Yellow
    Write-Host "        Add-Content -Path `"$HostsFile`" -Value `"`n$RequiredLine`"" -ForegroundColor White
    Write-Host "        ipconfig /flushdns" -ForegroundColor White
    Write-Host "        ping sleepingpassenger" -ForegroundColor White
    Write-Host ""
    Write-Host "      Or use the repo helper (also requires Administrator):" -ForegroundColor Yellow
    Write-Host "        powershell -ExecutionPolicy Bypass -File scripts\windows\add_sleepingpassenger_host_alias.ps1" -ForegroundColor White
    Write-Host ""
    Write-Host "Aborting. Add the hosts entry, then re-run this script." -ForegroundColor Red
    exit 1
}

# --- 2. Port 80 availability ------------------------------------------------
Write-Host ""
Write-Host "[2/3] Checking whether TCP port 80 is already in use..."

$portInUse = $false
$owningPid  = $null

try {
    $conn = Get-NetTCPConnection -LocalPort 80 -State Listen -ErrorAction Stop |
            Select-Object -First 1
    if ($conn) {
        $portInUse = $true
        $owningPid  = $conn.OwningProcess
    }
} catch {
    # Get-NetTCPConnection throws when no match; fall back to netstat for older shells.
    $netstat = netstat -ano | Select-String -Pattern ":80\s.*LISTENING"
    if ($netstat) {
        $portInUse = $true
        $first     = ($netstat | Select-Object -First 1).ToString().Trim() -split "\s+"
        $owningPid  = $first[-1]
    }
}

if ($portInUse) {
    $procName = "unknown"
    try {
        $proc = Get-Process -Id $owningPid -ErrorAction Stop
        $procName = $proc.ProcessName
    } catch { }
    Write-Host "      IN USE: port 80 is held by PID $owningPid ($procName)." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "      To free it (review before killing):" -ForegroundColor Yellow
    Write-Host "        Get-Process -Id $owningPid | Format-List Id, ProcessName, Path, StartTime" -ForegroundColor White
    Write-Host "        Stop-Process -Id $owningPid -Force" -ForegroundColor White
    Write-Host ""
    Write-Host "      Or use the fallback:" -ForegroundColor Yellow
    Write-Host "        cd `"$FrontendDir`"; npm run dev   # serves http://localhost:3000" -ForegroundColor White
    Write-Host ""
    Write-Host "Aborting. Free port 80 (or use the fallback), then re-run this script." -ForegroundColor Red
    exit 1
} else {
    Write-Host "      OK: port 80 is free." -ForegroundColor Green
}

# --- 3. Admin privilege hint (port 80 binds require it) ---------------------
Write-Host ""
Write-Host "[3/3] Launching Next.js on http://127.0.0.1:80 (alias http://sleepingpassenger/)..."

$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin   = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "      WARNING: this session is not Administrator." -ForegroundColor Yellow
    Write-Host "      Binding port 80 on Windows usually requires elevation." -ForegroundColor Yellow
    Write-Host "      If Next.js fails with EACCES / permission denied, re-run from an elevated PowerShell." -ForegroundColor Yellow
    Write-Host ""
}

if (-not (Test-Path $FrontendDir)) {
    Write-Error "Frontend directory not found: $FrontendDir"
    exit 1
}

Set-Location $FrontendDir
Write-Host "      Working dir: $FrontendDir"
Write-Host "      Command    : npm run dev:sleepingpassenger"
Write-Host ""
Write-Host "Open in browser once Next.js reports ready:" -ForegroundColor Cyan
Write-Host "  http://sleepingpassenger/" -ForegroundColor Cyan
Write-Host ""

npm run dev:sleepingpassenger
