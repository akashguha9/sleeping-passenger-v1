<#
.SYNOPSIS
Phase E.5 - Unregister scheduled task PipelineV57LocalMVPSilent.

Idempotent: no-ops if the task does not exist.
Requires Administrator to unregister tasks registered with Highest privilege.
Prints a clear error (and exits 1) if unregistration fails rather than
claiming false success.

Advisory only. No broker API. No order placement.
#>

$TaskName = "PipelineV57LocalMVPSilent"

# Check for Administrator privileges
$currentPrincipal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERROR: Administrator privileges required to unregister scheduled tasks."
    Write-Host "Re-run in an elevated PowerShell prompt:"
    Write-Host "  Right-click PowerShell -> 'Run as Administrator'"
    Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\windows\unregister_mvp_silent_startup_task.ps1"
    exit 1
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Host "Not found (already unregistered): $TaskName"
    exit 0
}

try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
    Write-Host "Unregistered: $TaskName"
} catch {
    Write-Host "ERROR: Failed to unregister '$TaskName': $_"
    exit 1
}
