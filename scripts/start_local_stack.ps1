<#
.SYNOPSIS
    Start the local advisory MVP stack (backend + optional frontend) after a
    safety gate.  Advisory-only — never places, modifies, or cancels any
    broker order.

.DESCRIPTION
    1. Runs scripts/release_gate.py.  Aborts on a FAIL verdict.
    2. Starts the FastAPI backend (uvicorn) on API_HOST:API_PORT.
    3. Optionally starts the Next.js frontend (skipped automatically if node
       is not on PATH, or with -NoFrontend).

    This script reads the gate verdict and refuses to launch on a hard
    failure (e.g. fake Moltbook pollution, an unlocked execution flag, a
    missing DB).  It does not bypass any safety invariant.

.PARAMETER NoFrontend
    Skip starting the frontend even if node/npm are available.

.PARAMETER Force
    Start the backend even if the release gate reports WARN (never on FAIL).

.EXAMPLE
    powershell -File scripts/start_local_stack.ps1
    powershell -File scripts/start_local_stack.ps1 -NoFrontend
#>
[CmdletBinding()]
param(
    [switch]$NoFrontend,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

$ApiHost = if ($env:API_HOST) { $env:API_HOST } else { "127.0.0.1" }
$ApiPort = if ($env:API_PORT) { $env:API_PORT } else { "8000" }

Write-Host "== Sleeping Passenger — local stack launcher (advisory-only) ==" -ForegroundColor Cyan

# 1. Safety gate ------------------------------------------------------------
Write-Host "Running release gate..." -ForegroundColor Yellow
Push-Location $RepoRoot
try {
    $gateJson = python -m scripts.release_gate --json
    $exit = $LASTEXITCODE
} finally {
    Pop-Location
}

$verdict = "UNKNOWN"
try {
    $gate = $gateJson | ConvertFrom-Json
    $verdict = $gate.verdict
    Write-Host ("Release gate verdict: {0} (fails={1}, warns={2})" -f `
        $gate.verdict, $gate.fail_count, $gate.warn_count)
    foreach ($r in $gate.reasons) { Write-Host ("  - {0}" -f $r) }
} catch {
    Write-Host "Could not parse release gate output; aborting." -ForegroundColor Red
    exit 1
}

if ($verdict -eq "FAIL" -or $exit -eq 1) {
    Write-Host "Release gate FAILED — not starting the stack." -ForegroundColor Red
    exit 1
}
if ($verdict -eq "WARN" -and -not $Force) {
    Write-Host "Release gate WARN — re-run with -Force to start anyway." -ForegroundColor Yellow
    exit 2
}

# 2. Backend ----------------------------------------------------------------
Write-Host ("Starting backend on http://{0}:{1} ..." -f $ApiHost, $ApiPort) -ForegroundColor Green
Push-Location $RepoRoot
try {
    Start-Process -FilePath "python" `
        -ArgumentList @("-m", "uvicorn", "scripts.api_server:app",
                        "--host", $ApiHost, "--port", $ApiPort) `
        -WorkingDirectory $RepoRoot
} finally {
    Pop-Location
}

# 3. Frontend (optional) ----------------------------------------------------
$node = Get-Command node -ErrorAction SilentlyContinue
if ($NoFrontend) {
    Write-Host "Frontend skipped (-NoFrontend)." -ForegroundColor DarkGray
} elseif (-not $node) {
    Write-Host "node not found on PATH — frontend skipped." -ForegroundColor DarkGray
} else {
    $frontend = Join-Path $RepoRoot "frontend"
    Write-Host "Starting frontend (npm run dev) ..." -ForegroundColor Green
    Start-Process -FilePath "npm" -ArgumentList @("run", "dev") -WorkingDirectory $frontend
}

Write-Host "Stack launch requested.  This MVP is advisory-only — no broker execution." -ForegroundColor Cyan
