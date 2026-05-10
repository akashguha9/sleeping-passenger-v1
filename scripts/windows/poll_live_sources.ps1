<#
.SYNOPSIS
Phase E.1 - Live source poller. Runs advisory ingestion every 300 seconds.
Advisory only. No broker API. No order placement.
Sources: polymarket, gdelt, market_data.
#>

param(
    [string]$RepoRoot          = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [int]   $PollIntervalSeconds = 300
)

$LogDir = Join-Path $RepoRoot "runtime\logs"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
$LogFile = Join-Path $LogDir "live_source_poller.log"

function Write-Log {
    param([string]$Message)
    $ts   = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $Message"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -ErrorAction SilentlyContinue
}

Write-Log "=== Live source poller started ==="
Write-Log "Repo root      : $RepoRoot"
Write-Log "Poll interval  : $PollIntervalSeconds seconds"
Write-Log "Log file       : $LogFile"
Write-Log "Advisory only. No broker API. No order placement."

$Sources = @(
    [pscustomobject]@{ Label = "polymarket";  Script = "run_live_sources_phase1.py"; Source = "polymarket" }
    [pscustomobject]@{ Label = "gdelt";       Script = "run_live_sources_phase1.py"; Source = "gdelt" }
    [pscustomobject]@{ Label = "market_data"; Script = "run_live_sources_phase2.py"; Source = "market_data" }
)

while ($true) {
    Write-Log "--- Poll run starting ---"

    foreach ($entry in $Sources) {
        $scriptPath = Join-Path $RepoRoot "scripts\$($entry.Script)"
        Write-Log "Running $($entry.Label) ..."
        try {
            $output   = & python $scriptPath --source $entry.Source --write
            $exitCode = $LASTEXITCODE
            foreach ($line in $output) {
                Write-Log "  [$($entry.Label)] $line"
            }
            if ($exitCode -ne 0) {
                Write-Log "$($entry.Label): exited with code $exitCode"
            } else {
                Write-Log "$($entry.Label): OK"
            }
        } catch {
            Write-Log "$($entry.Label): FAILED - $_"
        }
    }

    Write-Log "--- Poll run complete. Sleeping $PollIntervalSeconds s. ---"
    Start-Sleep -Seconds $PollIntervalSeconds
}
