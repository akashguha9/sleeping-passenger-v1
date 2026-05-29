# Daily discovery refresh launcher (advisory-only; no broker, no execution).
#
# Thin wrapper around scripts/run_daily_discovery_refresh.py. Refreshes
# market_data price marks before discovery/synthesis. It NEVER calls a broker,
# NEVER places or modifies an order, and NEVER runs autonomous execution.
#
# Examples:
#   .\scripts\run_daily_discovery_refresh.ps1                      # dry: no provider, C_price stays 0
#   .\scripts\run_daily_discovery_refresh.ps1 -UseMockProviders    # offline deterministic fixture
#   .\scripts\run_daily_discovery_refresh.ps1 -DbPath runtime\mvp_local.db -Json
[CmdletBinding()]
param(
    [switch]$DryRun = $true,
    [switch]$UseMockProviders,
    [switch]$SkipNetwork,
    [switch]$SkipSynthesis = $true,
    [switch]$RunSynthesis,
    [string]$DbPath,
    [string]$Holdings = "",
    [string]$Candidates = "",
    [string]$OutputDir,
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$script = Join-Path $repoRoot "scripts\run_daily_discovery_refresh.py"

$pyArgs = @($script)
if ($UseMockProviders) { $pyArgs += "--use-mock-providers" }
if ($SkipNetwork)      { $pyArgs += "--skip-network" }
if ($RunSynthesis)     { $pyArgs += "--run-synthesis" }
if ($DbPath)           { $pyArgs += @("--db-path", $DbPath) }
if ($Holdings)         { $pyArgs += @("--holdings", $Holdings) }
if ($Candidates)       { $pyArgs += @("--candidates", $Candidates) }
if ($OutputDir)        { $pyArgs += @("--output-dir", $OutputDir) }
if ($Json)             { $pyArgs += "--json" }

python @pyArgs
exit $LASTEXITCODE
