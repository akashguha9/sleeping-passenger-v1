<#
.SYNOPSIS
Phase E.5 - Stop Pipeline V5.7 advisory MVP stack processes.

Stops only MVP-related processes identified by command-line patterns:
  - Backend:  python.exe with 'uvicorn scripts.api_server'
  - Frontend: powershell.exe or node.exe running 'next dev'
  - Poller:   powershell.exe with 'poll_live_sources.ps1'
  - Proxy:    python.exe with 'local_frontend_reverse_proxy'

Does NOT kill unrelated node/python/PowerShell processes.
Advisory only. No broker API. No order placement.
#>

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
)

$LogDir = Join-Path $RepoRoot "runtime\logs"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
$StopLog = Join-Path $LogDir "silent_stop.log"

function Write-Log {
    param([string]$Message)
    $ts   = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $Message"
    Add-Content -Path $StopLog -Value $line -ErrorAction SilentlyContinue
    Write-Host $line
}

function Stop-MatchingProcesses {
    param(
        [string]$Label,
        [string]$ProcessName,
        [string]$CommandPattern
    )
    $procs = Get-CimInstance Win32_Process -Filter "Name='$ProcessName'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like $CommandPattern }
    if ($procs) {
        foreach ($p in $procs) {
            Write-Log "${Label}: stopping PID $($p.ProcessId) ..."
            try {
                Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
                Write-Log "${Label}: PID $($p.ProcessId) stopped."
            } catch {
                Write-Log "${Label}: WARNING - could not stop PID $($p.ProcessId): $_"
            }
        }
    } else {
        Write-Log "${Label}: not running."
    }
}

Write-Log "=== Silent MVP stack stop ==="
Write-Log "Advisory only. No broker API. No order placement."

# Backend: python.exe running uvicorn scripts.api_server
Stop-MatchingProcesses -Label "Backend" `
    -ProcessName "python.exe" `
    -CommandPattern "*uvicorn*scripts.api_server*"

# Frontend: powershell.exe running 'next dev' (spawned by start_mvp_stack_silent.ps1)
Stop-MatchingProcesses -Label "Frontend-shell" `
    -ProcessName "powershell.exe" `
    -CommandPattern "*next*dev*"

# Frontend: node.exe running next dev (spawned by the above PowerShell)
Stop-MatchingProcesses -Label "Frontend-node" `
    -ProcessName "node.exe" `
    -CommandPattern "*next*dev*"

# Poller: powershell.exe running poll_live_sources.ps1
Stop-MatchingProcesses -Label "Poller" `
    -ProcessName "powershell.exe" `
    -CommandPattern "*poll_live_sources.ps1*"

# Proxy: python.exe running local_frontend_reverse_proxy
Stop-MatchingProcesses -Label "Proxy" `
    -ProcessName "python.exe" `
    -CommandPattern "*local_frontend_reverse_proxy*"

Write-Log "=== Stop complete ==="
