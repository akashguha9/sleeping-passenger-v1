<#
.SYNOPSIS
    Register the SleepingPassengerLiveSignalRefresh Windows Scheduled Task
    that runs the local refresh orchestrator every 6 hours.

.DESCRIPTION
    The registered task wraps:
        scripts\windows\run_live_signal_refresh_once.ps1

    Default mode is --write so the cadence actually populates fresh signal
    rows. The task runs under the current user's context with the lowest
    privilege required. No secrets are stored in the task definition.

    Safety:
      * No broker is contacted by the orchestrator.
      * Advisory-only: ADVISORY_ONLY, execution_gate=LOCKED, can_execute=false,
        broker_api_called=false on every persisted row and report.
      * The task only invokes a local PowerShell wrapper which only invokes a
        local Python orchestrator. Nothing trades.

.PARAMETER Force
    Overwrite an existing scheduled task with the same name without prompting.

.PARAMETER DryRunOnly
    Register the task with --dry-run instead of --write. Default is --write.

.PARAMETER StartTime
    Time of day to start the first run, "HH:mm" 24h format. Default 00:00.
    Task then repeats every 6 hours.

.EXAMPLE
    PS> .\scripts\windows\register_live_signal_refresh_task.ps1
    PS> .\scripts\windows\register_live_signal_refresh_task.ps1 -Force
    PS> .\scripts\windows\register_live_signal_refresh_task.ps1 -DryRunOnly
    PS> .\scripts\windows\register_live_signal_refresh_task.ps1 -StartTime "03:00"

.NOTES
    To view the task:
        Get-ScheduledTask -TaskName SleepingPassengerLiveSignalRefresh

    To unregister the task:
        Unregister-ScheduledTask -TaskName SleepingPassengerLiveSignalRefresh -Confirm:$false

    The schtasks.exe equivalent is included below for environments where
    Register-ScheduledTask is restricted:
        schtasks /Create /TN "SleepingPassengerLiveSignalRefresh" `
            /TR "powershell -NoProfile -ExecutionPolicy Bypass -File `"<repo>\scripts\windows\run_live_signal_refresh_once.ps1`" -WriteMode" `
            /SC HOURLY /MO 6 /F
#>

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$Force,
    [switch]$DryRunOnly,
    [string]$StartTime = "00:00"
)

$ErrorActionPreference = "Stop"

$TaskName = "SleepingPassengerLiveSignalRefresh"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$OnceScript = Join-Path $RepoRoot "scripts\windows\run_live_signal_refresh_once.ps1"

if (-not (Test-Path $OnceScript)) {
    throw "expected wrapper not found: $OnceScript"
}

$argsString = "-NoProfile -ExecutionPolicy Bypass -File `"$OnceScript`""
if (-not $DryRunOnly) {
    $argsString += " -WriteMode"
}

$existing = $null
try {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
} catch {
    $existing = $null
}

if ($existing -and -not $Force) {
    Write-Host "Task '$TaskName' already exists. Re-run with -Force to overwrite."
    Write-Host "Inspect:    Get-ScheduledTask -TaskName $TaskName"
    Write-Host "Unregister: Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false"
    exit 0
}

if ($existing -and $Force) {
    if ($PSCmdlet.ShouldProcess($TaskName, "Unregister existing task")) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument $argsString `
    -WorkingDirectory $RepoRoot

$trigger = New-ScheduledTaskTrigger -Once -At $StartTime `
    -RepetitionInterval (New-TimeSpan -Hours 6)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U

if (-not $PSCmdlet.ShouldProcess($TaskName, "Register scheduled task")) {
    exit 0
}

$registered = $null
try {
    $registered = Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description "Sleeping Passenger advisory-only live signal refresh (every 6 hours). No broker. No execution." `
        -ErrorAction Stop
} catch {
    $msg = $_.Exception.Message
    $accessDenied = $msg -match '(?i)access\s*is\s*denied|unauthorized|denied|permission|0x80070005'
    Write-Host ""
    Write-Host "[FAIL] Register-ScheduledTask failed: $msg" -ForegroundColor Red
    if ($accessDenied) {
        Write-Host ""
        Write-Host "Access denied. Windows requires an elevated PowerShell to register" -ForegroundColor Yellow
        Write-Host "scheduled tasks under this principal." -ForegroundColor Yellow
        Write-Host ""
        Write-Host "  Re-run this script in an Administrator PowerShell:" -ForegroundColor Yellow
        Write-Host "    Start-Process powershell -Verb RunAs" -ForegroundColor Yellow
        Write-Host "    cd `"$RepoRoot`"" -ForegroundColor Yellow
        Write-Host "    .\scripts\windows\register_live_signal_refresh_task.ps1 -Force" -ForegroundColor Yellow
    }
    exit 1
}

# Verify the task actually exists before declaring success. Register-ScheduledTask
# can succeed superficially but the task may not be reachable via the task store
# under certain principals/profiles; we re-query to confirm.
$verified = $null
try {
    $verified = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
} catch {
    Write-Host "[FAIL] Task '$TaskName' could not be verified after registration." -ForegroundColor Red
    Write-Host "       $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

if (-not $verified) {
    Write-Host "[FAIL] Task '$TaskName' missing after registration; aborting." -ForegroundColor Red
    exit 1
}

Write-Host "Registered scheduled task '$TaskName' (state=$($verified.State))."
Write-Host "Mode:         $(if ($DryRunOnly) { '--dry-run' } else { '--write' })"
Write-Host "Cadence:      every 6 hours starting $StartTime"
Write-Host "Wrapper:      $OnceScript"
Write-Host "Logs append:  $(Join-Path $RepoRoot 'logs\live_signal_refresh.log')"
Write-Host ""
Write-Host "Inspect:      Get-ScheduledTask -TaskName $TaskName"
Write-Host "Run now:      Start-ScheduledTask -TaskName $TaskName"
Write-Host "Unregister:   Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false"
Write-Host ""
Write-Host "Safety: orchestrator is ADVISORY_ONLY, execution_gate=LOCKED, broker_api_called=false."
exit 0
