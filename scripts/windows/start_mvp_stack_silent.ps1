<#
.SYNOPSIS
Phase E.5 - Silent background startup for the local Pipeline V5.7 advisory MVP stack.

Starts backend, frontend, poller, and sleepingpassenger proxy silently
(no visible PowerShell windows). All output redirected to runtime\logs\.

Idempotent: components already listening on their ports are skipped.

Requirements:
  - One-time host alias setup (Administrator):
      powershell -ExecutionPolicy Bypass -File scripts\windows\add_sleepingpassenger_host_alias.ps1
  - Port 80 proxy requires Administrator.
  - Backend/frontend work without Administrator.

Advisory only. No broker API. No order placement.
#>

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
)

Set-Location $RepoRoot

$LogDir = Join-Path $RepoRoot "runtime\logs"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
$StartupLog = Join-Path $LogDir "silent_startup.log"

function Write-Log {
    param([string]$Message)
    $ts   = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $Message"
    Add-Content -Path $StartupLog -Value $line -ErrorAction SilentlyContinue
    Write-Host $line
}

function Test-PortListening {
    param([int]$Port)
    $props     = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties()
    $listeners = $props.GetActiveTcpListeners()
    foreach ($l in $listeners) {
        if ($l.Port -eq $Port) { return $true }
    }
    return $false
}

function Wait-ForPort {
    param([int]$Port, [int]$TimeoutSeconds = 30)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-PortListening -Port $Port) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Test-ProcessRunning {
    param([string]$ProcessName, [string]$CommandPattern)
    $procs = Get-CimInstance Win32_Process -Filter "Name='$ProcessName'" -ErrorAction SilentlyContinue
    if (-not $procs) { return $false }
    foreach ($p in $procs) {
        if ($p.CommandLine -like $CommandPattern) { return $true }
    }
    return $false
}

Write-Log "=== Silent MVP stack startup ==="
Write-Log "Repo root : $RepoRoot"
Write-Log "Log dir   : $LogDir"
Write-Log "Advisory only. No broker API. No order placement."

# ---------------------------------------------------------------------------
# Backend: python -m uvicorn scripts.api_server:app --host 127.0.0.1 --port 8000
# ---------------------------------------------------------------------------
if (Test-PortListening -Port 8000) {
    Write-Log "Backend: already running on port 8000. Skipping."
} else {
    Write-Log "Backend: starting on http://127.0.0.1:8000 ..."
    Start-Process -FilePath "python" `
        -ArgumentList @("-m", "uvicorn", "scripts.api_server:app", "--host", "127.0.0.1", "--port", "8000") `
        -WorkingDirectory $RepoRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $LogDir "backend_stdout.log") `
        -RedirectStandardError  (Join-Path $LogDir "backend_stderr.log")
    if (Wait-ForPort -Port 8000 -TimeoutSeconds 30) {
        Write-Log "Backend: ready at http://127.0.0.1:8000/health"
    } else {
        Write-Log "Backend: WARNING - port 8000 not responding within 30s. Check backend_stderr.log."
    }
}

# ---------------------------------------------------------------------------
# Frontend: npx next dev -p 3000  (port 3000 required by sleepingpassenger proxy)
# ---------------------------------------------------------------------------
if (Test-PortListening -Port 3000) {
    Write-Log "Frontend: already running on port 3000. Skipping."
} else {
    Write-Log "Frontend: starting on http://localhost:3000 ..."
    $frontendDir = Join-Path $RepoRoot "frontend"
    $frontendCmd = "Set-Location '$frontendDir'; npx next dev -p 3000"
    $frontendEnc = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($frontendCmd))
    Start-Process -FilePath "powershell.exe" `
        -ArgumentList @("-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-EncodedCommand", $frontendEnc) `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $LogDir "frontend_stdout.log") `
        -RedirectStandardError  (Join-Path $LogDir "frontend_stderr.log")
    if (Wait-ForPort -Port 3000 -TimeoutSeconds 60) {
        Write-Log "Frontend: ready at http://localhost:3000"
    } else {
        Write-Log "Frontend: WARNING - port 3000 not responding within 60s. Check frontend_stderr.log."
    }
}

# ---------------------------------------------------------------------------
# Poller: poll_live_sources.ps1 every 300 seconds
# ---------------------------------------------------------------------------
if (Test-ProcessRunning -ProcessName "powershell.exe" -CommandPattern "*poll_live_sources.ps1*") {
    Write-Log "Poller: already running. Skipping."
} else {
    Write-Log "Poller: starting poll_live_sources.ps1 ..."
    $pollerScript = Join-Path $PSScriptRoot "poll_live_sources.ps1"
    Start-Process -FilePath "powershell.exe" `
        -ArgumentList @("-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", $pollerScript, "-RepoRoot", $RepoRoot) `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $LogDir "poller_stdout.log") `
        -RedirectStandardError  (Join-Path $LogDir "poller_stderr.log")
    Write-Log "Poller: started."
}

# ---------------------------------------------------------------------------
# sleepingpassenger proxy: port 80 -> port 3000 (requires Administrator for port 80)
# ---------------------------------------------------------------------------
if (Test-ProcessRunning -ProcessName "python.exe" -CommandPattern "*local_frontend_reverse_proxy*") {
    Write-Log "Proxy: already running. Skipping."
} else {
    Write-Log "Proxy: starting sleepingpassenger proxy (port 80 -> 3000) ..."
    $proxyScript = Join-Path $PSScriptRoot "start_sleepingpassenger_proxy.ps1"
    Start-Process -FilePath "powershell.exe" `
        -ArgumentList @("-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", $proxyScript, "-RepoRoot", $RepoRoot) `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $LogDir "proxy_stdout.log") `
        -RedirectStandardError  (Join-Path $LogDir "proxy_stderr.log")
    Write-Log "Proxy: started (port 80 requires Administrator)."
}

Write-Log "=== Startup complete ==="
Write-Log ""
Write-Log "  http://sleepingpassenger        (requires host alias + port-80 proxy)"
Write-Log "  http://sleepingpassenger.local  (requires host alias + port-80 proxy)"
Write-Log "  http://localhost:3000           (frontend direct)"
Write-Log "  http://localhost:8000/health    (backend health check)"
Write-Log "  Logs: $LogDir"
Write-Log "  Advisory only. No broker API. No order placement."
