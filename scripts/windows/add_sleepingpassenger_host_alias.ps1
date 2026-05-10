<#
.SYNOPSIS
Phase E.1 - Add sleepingpassenger host aliases to the Windows hosts file.
Requires Administrator privileges.
Idempotent: skips any alias that is already present.

Adds:
  127.0.0.1 sleepingpassenger
  127.0.0.1 sleepingpassenger.local

Local-only setup. Does not configure public DNS or internet hosting.
#>

$HostsFile = "C:\Windows\System32\drivers\etc\hosts"
$Marker    = "# pipeline-v5.7-core sleepingpassenger"

$Entries = @(
    [pscustomobject]@{ Hostname = "sleepingpassenger";       Line = "127.0.0.1 sleepingpassenger" }
    [pscustomobject]@{ Hostname = "sleepingpassenger.local"; Line = "127.0.0.1 sleepingpassenger.local" }
)

$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "Administrator privileges required. Re-run this script as Administrator."
    exit 1
}

$hostsLines = Get-Content $HostsFile -Encoding UTF8
$toAdd      = [System.Collections.Generic.List[string]]::new()

foreach ($entry in $Entries) {
    $pattern = "^\s*127\.0\.0\.1\s+$([regex]::Escape($entry.Hostname))\s*$"
    if ($hostsLines | Where-Object { $_ -match $pattern }) {
        Write-Host "Already present : $($entry.Line)"
    } else {
        $toAdd.Add($entry.Line)
    }
}

if ($toAdd.Count -gt 0) {
    Add-Content -Path $HostsFile -Value ""         -Encoding UTF8
    Add-Content -Path $HostsFile -Value $Marker    -Encoding UTF8
    foreach ($line in $toAdd) {
        Add-Content -Path $HostsFile -Value $line  -Encoding UTF8
        Write-Host "Added           : $line"
    }
}

Write-Host ""
Write-Host "Host aliases ready. Start the port-80 proxy to use these URLs:"
Write-Host "  http://sleepingpassenger"
Write-Host "  http://sleepingpassenger.local"
Write-Host ""
Write-Host "Port-80 proxy (requires Administrator or elevated session):"
Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\windows\start_sleepingpassenger_proxy.ps1"
Write-Host ""
Write-Host "Note: This sets up local aliases on this machine only."
Write-Host "Public internet access is separate and not configured here."
