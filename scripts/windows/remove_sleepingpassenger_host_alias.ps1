<#
.SYNOPSIS
Phase E.1 — Remove sleepingpassenger host aliases from the Windows hosts file.
Requires Administrator privileges.
Idempotent: no-ops if aliases are already absent.
#>

$HostsFile    = "C:\Windows\System32\drivers\etc\hosts"
$Marker       = "# pipeline-v5.7-core sleepingpassenger"
$HostsToStrip = @("sleepingpassenger", "sleepingpassenger.local")

$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "Administrator privileges required. Re-run this script as Administrator."
    exit 1
}

$hostsLines = Get-Content $HostsFile -Encoding UTF8
$filtered   = $hostsLines | Where-Object {
    $line = $_.Trim()
    if ($line -eq $Marker) { return $false }
    foreach ($h in $HostsToStrip) {
        if ($line -match "^\s*127\.0\.0\.1\s+$([regex]::Escape($h))\s*$") { return $false }
    }
    return $true
}

$filtered | Set-Content -Path $HostsFile -Encoding UTF8
Write-Host "Removed sleepingpassenger aliases from: $HostsFile"
