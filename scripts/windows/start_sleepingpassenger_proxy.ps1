<#
.SYNOPSIS
Phase E.1 — Start the sleepingpassenger reverse proxy.
Forwards http://127.0.0.1:80 to http://127.0.0.1:3000 (Next.js frontend).
Advisory frontend mirror only. No backend or financial logic.

NOTE: Port 80 requires Administrator privileges on Windows.
If the proxy fails to bind, re-run PowerShell as Administrator,
or use http://localhost:3000 directly.
#>

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
)

$LogDir = Join-Path $RepoRoot "runtime\logs"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
$LogFile     = Join-Path $LogDir "sleepingpassenger_proxy.log"
$ProxyScript = Join-Path $PSScriptRoot "local_frontend_reverse_proxy.py"

Write-Host "sleepingpassenger reverse proxy"
Write-Host "Proxy : http://127.0.0.1:80 -> http://127.0.0.1:3000"
Write-Host "Log   : $LogFile"
Write-Host ""
Write-Host "NOTE: Binding port 80 requires Administrator privileges on Windows."
Write-Host "If this fails, re-run PowerShell as Administrator,"
Write-Host "or use http://localhost:3000 directly (no proxy needed)."
Write-Host ""

& python $ProxyScript | Tee-Object -FilePath $LogFile -Append
