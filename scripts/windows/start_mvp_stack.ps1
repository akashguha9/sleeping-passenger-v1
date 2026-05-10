<#
.SYNOPSIS
Phase E.1 — Start the local Pipeline V5.7 advisory MVP stack.

Launches backend (FastAPI), frontend (Next.js), live-source poller, and
sleepingpassenger reverse proxy each in a separate PowerShell window.
Advisory only. No broker API. No order placement.
#>

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
)

$LogDir = Join-Path $RepoRoot "runtime\logs"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    Write-Host "Created log directory: $LogDir"
}

Write-Host "Pipeline V5.7 Local Advisory MVP Stack"
Write-Host "Repo root : $RepoRoot"
Write-Host "Logs      : $LogDir"
Write-Host ""

# --- Backend (FastAPI via uvicorn) ---
$backendCmd = "Set-Location '$RepoRoot'; Write-Host '[backend] Starting...'; uvicorn scripts.api_server:app --reload"
$backendEncoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($backendCmd))
Start-Process powershell.exe `
    -ArgumentList @("-NoExit", "-EncodedCommand", $backendEncoded) `
    -WindowStyle Normal
Write-Host "Backend  : http://localhost:8000 (window launched)"

# --- Frontend (Next.js) ---
$frontendCmd = "Set-Location '$RepoRoot\frontend'; Write-Host '[frontend] Starting...'; npm run dev"
$frontendEncoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($frontendCmd))
Start-Process powershell.exe `
    -ArgumentList @("-NoExit", "-EncodedCommand", $frontendEncoded) `
    -WindowStyle Normal
Write-Host "Frontend : http://localhost:3000 (window launched)"

# --- Live source poller ---
$pollerScript = Join-Path $PSScriptRoot "poll_live_sources.ps1"
Start-Process powershell.exe `
    -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-File", $pollerScript, "-RepoRoot", $RepoRoot) `
    -WindowStyle Normal
Write-Host "Poller   : polymarket, gdelt, market_data every 300 s (window launched)"

# --- sleepingpassenger reverse proxy ---
$proxyScript = Join-Path $PSScriptRoot "start_sleepingpassenger_proxy.ps1"
Start-Process powershell.exe `
    -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-File", $proxyScript, "-RepoRoot", $RepoRoot) `
    -WindowStyle Normal
Write-Host "Proxy    : http://sleepingpassenger -> http://localhost:3000 (window launched)"

Write-Host ""
Write-Host "URLs:"
Write-Host "  http://sleepingpassenger         (requires host alias + port-80 proxy)"
Write-Host "  http://sleepingpassenger.local   (requires host alias + port-80 proxy)"
Write-Host "  http://localhost:3000            (direct, always available)"
Write-Host "  http://localhost:8000            (backend API)"
Write-Host "  http://localhost:8000/docs       (API docs)"
Write-Host ""
Write-Host "Logs: $LogDir"
Write-Host "Advisory only. No broker API. No order placement."
