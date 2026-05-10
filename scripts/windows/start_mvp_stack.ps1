<#
.SYNOPSIS
Phase E.1 - Start the local Pipeline V5.7 advisory MVP stack.

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
# Uses python -m uvicorn so the module is resolved through the active venv.
# If uvicorn/fastapi is missing the window shows a clear install command.
$backendCmd = "Set-Location '$RepoRoot'; Write-Host '[backend] Starting...'; python -m uvicorn scripts.api_server:app --reload; if (`$LASTEXITCODE -ne 0) { Write-Host '[backend] FAILED. Install deps: python -m pip install fastapi uvicorn'; Read-Host 'Press Enter to exit' }"
$backendEncoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($backendCmd))
Start-Process powershell.exe `
    -ArgumentList @("-NoExit", "-EncodedCommand", $backendEncoded) `
    -WindowStyle Normal
Write-Host "Backend  : http://localhost:8000 (window launched)"

# --- Frontend (Next.js) pinned to port 3000 ---
# Port 3000 is required: the sleepingpassenger reverse proxy forwards port 80 -> 3000.
# If port 3000 is busy the window exits with a clear message instead of silently
# falling back to 3001 (which would break the proxy).
$frontendCmd = "Set-Location '$RepoRoot\frontend'; Write-Host '[frontend] Checking port 3000...'; `$busy = netstat -ano 2>`$null | Select-String ':3000 '; if (`$busy) { Write-Host '[frontend] ERROR: Port 3000 is already in use.'; Write-Host '[frontend] Stop the existing Next.js process first: Get-Process node | Stop-Process'; Read-Host 'Press Enter to exit'; exit 1 }; Write-Host '[frontend] Starting on port 3000...'; npm run dev -- -p 3000"
$frontendEncoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($frontendCmd))
Start-Process powershell.exe `
    -ArgumentList @("-NoExit", "-EncodedCommand", $frontendEncoded) `
    -WindowStyle Normal
Write-Host "Frontend : http://localhost:3000 (window launched, port pinned)"

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
