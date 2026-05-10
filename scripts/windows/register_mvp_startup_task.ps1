<#
.SYNOPSIS
Phase E.1 - Register Windows Scheduled Task: PipelineV57LocalMVP.
Triggers start_mvp_stack.ps1 at user logon with highest privileges
so the port-80 reverse proxy can bind.
#>

$TaskName = "PipelineV57LocalMVP"
$RepoRoot = "C:\Users\akash\pipeline-v5.7-core"
$Script   = Join-Path $RepoRoot "scripts\windows\start_mvp_stack.ps1"

$action = New-ScheduledTaskAction `
    -Execute        "powershell.exe" `
    -Argument       "-ExecutionPolicy Bypass -File `"$Script`"" `
    -WorkingDirectory $RepoRoot

$trigger = New-ScheduledTaskTrigger -AtLogon -User $env:USERNAME

$principal = New-ScheduledTaskPrincipal `
    -UserId    $env:USERNAME `
    -LogonType Interactive `
    -RunLevel  Highest

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

# Idempotent: remove existing task first
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask `
    -TaskName    $TaskName `
    -Action      $action `
    -Trigger     $trigger `
    -Principal   $principal `
    -Settings    $settings `
    -Description "Pipeline V5.7 local advisory MVP stack - auto-start at logon." `
    -Force | Out-Null

Write-Host "Registered : $TaskName"
Write-Host "Trigger    : At logon for $($env:USERNAME)"
Write-Host "Action     : powershell.exe -ExecutionPolicy Bypass -File `"$Script`""
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. One-time host alias setup (run as Administrator):"
Write-Host "       powershell -ExecutionPolicy Bypass -File scripts\windows\add_sleepingpassenger_host_alias.ps1"
Write-Host "  2. Log off and back on to trigger auto-start, or run manually:"
Write-Host "       powershell -ExecutionPolicy Bypass -File scripts\windows\start_mvp_stack.ps1"
Write-Host "  3. Unregister later:"
Write-Host "       powershell -ExecutionPolicy Bypass -File scripts\windows\unregister_mvp_startup_task.ps1"
