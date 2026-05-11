<#
.SYNOPSIS
Phase E.5 - Register Windows Scheduled Task: PipelineV57LocalMVPSilent.

Triggers start_mvp_stack_silent.ps1 at user logon with no visible windows.
Uses Highest privilege level so the port-80 reverse proxy can bind.

Idempotent: removes existing task of the same name before re-registering.

Advisory only. No broker API. No order placement.
#>

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
)

$TaskName = "PipelineV57LocalMVPSilent"
$Script   = Join-Path $RepoRoot "scripts\windows\start_mvp_stack_silent.ps1"

if (-not (Test-Path $Script)) {
    Write-Host "ERROR: start_mvp_stack_silent.ps1 not found at: $Script"
    exit 1
}

$action = New-ScheduledTaskAction `
    -Execute          "powershell.exe" `
    -Argument         "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Script`" -RepoRoot `"$RepoRoot`"" `
    -WorkingDirectory $RepoRoot

$trigger = New-ScheduledTaskTrigger -AtLogon -User $env:USERNAME

$principal = New-ScheduledTaskPrincipal `
    -UserId    $env:USERNAME `
    -LogonType Interactive `
    -RunLevel  Highest

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -Hidden

# Idempotent: remove existing task first (silently)
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

try {
    Register-ScheduledTask `
        -TaskName    $TaskName `
        -Action      $action `
        -Trigger     $trigger `
        -Principal   $principal `
        -Settings    $settings `
        -Description "Pipeline V5.7 local advisory MVP stack - silent auto-start at logon. Advisory only." `
        -Force -ErrorAction Stop | Out-Null
} catch {
    Write-Host "ERROR: Failed to register scheduled task: $_"
    Write-Host "Note: If port 80 proxy is needed, run this script as Administrator."
    exit 1
}

Write-Host "Registered : $TaskName"
Write-Host "Trigger    : At logon for $($env:USERNAME)"
Write-Host "Action     : powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Script`""
Write-Host "Mode       : Silent (no visible windows)"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. One-time host alias setup (run as Administrator):"
Write-Host "       powershell -ExecutionPolicy Bypass -File scripts\windows\add_sleepingpassenger_host_alias.ps1"
Write-Host "  2. Log off and back on to trigger auto-start, or run manually:"
Write-Host "       powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File scripts\windows\start_mvp_stack_silent.ps1"
Write-Host "  3. Check logs: runtime\logs\"
Write-Host "  4. Unregister later:"
Write-Host "       powershell -ExecutionPolicy Bypass -File scripts\windows\unregister_mvp_silent_startup_task.ps1"
Write-Host ""
Write-Host "Advisory only. No broker API. No order placement."
