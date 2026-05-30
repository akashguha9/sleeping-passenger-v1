# Daily discovery refresh launcher (advisory-only; no broker, no execution).
#
# Thin wrapper around scripts/run_daily_discovery_refresh.py. Refreshes price
# marks, attempts read-only UK disclosures, rebuilds the daily payloads, and
# computes country coverage before discovery/synthesis. It NEVER calls a broker,
# NEVER places or modifies an order, and NEVER runs autonomous execution.
#
# Network is touched ONLY with -AllowNetwork. -UseMockProviders runs a
# deterministic offline fixture. Secret values are never printed.
#
# Examples:
#   .\scripts\run_daily_discovery_refresh.ps1                       # default-safe, no network
#   .\scripts\run_daily_discovery_refresh.ps1 -UseMockProviders     # offline deterministic fixture
#   .\scripts\run_daily_discovery_refresh.ps1 -CountryFocus Germany -TargetTicker RHM.DE
#   .\scripts\run_daily_discovery_refresh.ps1 -AllowNetwork -Provider yahoo -Json
[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$SkipNetwork,
    [switch]$SkipSynthesis = $true,
    [switch]$UseMockProviders,
    [switch]$AllowNetwork,
    [switch]$NoSecretsInLogs = $true,
    [string]$DbPath,
    [string]$OutputDir,
    [string]$Provider,
    [int]$MaxRows = 100,
    [string]$CountryFocus,
    [string]$TargetTicker,
    [string]$Holdings = "",
    [string]$Candidates = "",
    [ValidateSet("open", "closed", "unknown")]
    [string]$MarketState = "unknown",
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$script = Join-Path $repoRoot "scripts\run_daily_discovery_refresh.py"

$pyArgs = @($script)
if ($DryRun)            { $pyArgs += "--dry-run" }
if ($SkipNetwork)       { $pyArgs += "--skip-network" }
if ($UseMockProviders)  { $pyArgs += "--use-mock-providers" }
if ($AllowNetwork)      { $pyArgs += "--allow-network" }
if ($NoSecretsInLogs)   { $pyArgs += "--no-secrets-in-logs" }
if ($DbPath)            { $pyArgs += @("--db-path", $DbPath) }
if ($OutputDir)         { $pyArgs += @("--output-dir", $OutputDir) }
if ($Provider)          { $pyArgs += @("--provider", $Provider) }
if ($MaxRows)           { $pyArgs += @("--max-rows", "$MaxRows") }
if ($CountryFocus)      { $pyArgs += @("--country-focus", $CountryFocus) }
if ($TargetTicker)      { $pyArgs += @("--target-ticker", $TargetTicker) }
if ($Holdings)          { $pyArgs += @("--holdings", $Holdings) }
if ($Candidates)        { $pyArgs += @("--candidates", $Candidates) }
if ($MarketState)       { $pyArgs += @("--market-state", $MarketState) }
if ($Json)              { $pyArgs += "--json" }

python @pyArgs
exit $LASTEXITCODE
