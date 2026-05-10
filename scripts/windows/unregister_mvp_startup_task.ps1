<#
.SYNOPSIS
Phase E.1 — Unregister scheduled task PipelineV57LocalMVP.
Idempotent: no-ops if the task does not exist.
#>

$TaskName = "PipelineV57LocalMVP"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Unregistered: $TaskName"
} else {
    Write-Host "Not found (already unregistered): $TaskName"
}
