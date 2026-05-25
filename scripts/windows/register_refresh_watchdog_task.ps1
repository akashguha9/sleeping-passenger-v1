<#
.SYNOPSIS
    Register the SleepingPassengerRefreshWatchdog Windows Scheduled Task
    that runs the stale-source watchdog every 30 minutes.

.DESCRIPTION
    The watchdog reconciles "scheduled task ran cleanly" against "source
    freshness actually improved". The 6-hour refresh task drives the bulk
    refresh; this 30-minute watchdog retries sources that have aged past
    the TTL and never lies about a HEALTHY status while active stale
    sources remain.

    Safety:
      * ADVISORY_ONLY. No broker contacted, no order placement, no
        execution route added by this task.
      * The watchdog only invokes local Python scripts and reads SQLite
        metadata.

.PARAMETER Force
    Overwrite an existing scheduled task with the same name without prompting.

.PARAMETER IntervalMinutes
    Watchdog cadence in minutes. Default 30.

.PARAMETER StartTime
    Time of day for the first trigger fire, "HH:mm" 24h format. Default 00:15.

.EXAMPLE
    PS> .\scripts\windows\register_refresh_watchdog_task.ps1
    PS> .\scripts\windows\register_refresh_watchdog_task.ps1 -Force
    PS> .\scripts\windows\register_refresh_watchdog_task.ps1 -IntervalMinutes 30
#>

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$Force,
    [int]$IntervalMinutes = 30,
    [string]$StartTime = "00:15"
)

$ErrorActionPreference = "Stop"

$TaskName = "SleepingPassengerRefreshWatchdog"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$OnceScript = Join-Path $RepoRoot "scripts\windows\run_refresh_watchdog_once.ps1"

if (-not (Test-Path $OnceScript)) {
    throw "expected wrapper not found: $OnceScript"
}

$argsString = "-NoProfile -ExecutionPolicy Bypass -File `"$OnceScript`""

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
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20) `
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
        -Description "Sleeping Passenger advisory-only stale-source freshness watchdog. No broker. No execution." `
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
        Write-Host "    .\scripts\windows\register_refresh_watchdog_task.ps1 -Force" -ForegroundColor Yellow
    }
    exit 1
}

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
Write-Host "Cadence:      every $IntervalMinutes minutes starting $StartTime"
Write-Host "Wrapper:      $OnceScript"
Write-Host "Summary:      $(Join-Path $RepoRoot 'runtime\refresh_watchdog_summary.json')"
Write-Host "Logs append:  $(Join-Path $RepoRoot 'logs\refresh_watchdog.log')"
Write-Host ""
Write-Host "Inspect:      Get-ScheduledTask -TaskName $TaskName"
Write-Host "Run now:      Start-ScheduledTask -TaskName $TaskName"
Write-Host "Unregister:   Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false"
Write-Host ""
Write-Host "Safety: watchdog is ADVISORY_ONLY, execution_gate=LOCKED, broker_api_called=false."
exit 0
