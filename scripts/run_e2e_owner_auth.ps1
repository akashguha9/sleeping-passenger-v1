# Run the owner-auth Playwright E2E suite locally (Windows PowerShell).
#
# The Playwright specs are ROUTE-MOCKED: page.route stubs the backend, so
# no live API, no .env, and no real token are required for the suite
# itself. Tokens that appear inside the specs are synthetic fixtures.
#
# -RealStack additionally proves the live contract end to end: it
# generates a TEMPORARY throwaway token, boots the real backend with the
# token hash in process env only (your .env is never touched), asserts
# 401-without / 200-with / 421-foreign-host, then tears everything down.
# The raw temp token is never printed unless -VerboseTokenForDebug is
# explicitly passed (off by default).
#
# Usage:
#   .\scripts\run_e2e_owner_auth.ps1                 # build + playwright (mocked)
#   .\scripts\run_e2e_owner_auth.ps1 -RealStack      # + live 401/200/421 probe
#   .\scripts\run_e2e_owner_auth.ps1 -SkipBuild      # reuse existing .next build
#
[CmdletBinding()]
param(
    [switch]$RealStack,
    [switch]$SkipBuild,
    [switch]$VerboseTokenForDebug
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Frontend = Join-Path $RepoRoot "frontend"

Write-Host "=== Owner-auth E2E (advisory-only MVP; no broker, no execution) ==="

# ---------------------------------------------------------------------------
# 1. Preconditions
# ---------------------------------------------------------------------------
if (-not (Test-Path (Join-Path $Frontend "node_modules"))) {
    Write-Host "[next] frontend dependencies missing. Run:"
    Write-Host "       cd frontend; npm ci"
    exit 2
}
$browsersPath = Join-Path $env:USERPROFILE "AppData\Local\ms-playwright"
$browserReady = (Test-Path $browsersPath) -and ((Get-ChildItem $browsersPath -ErrorAction SilentlyContinue | Measure-Object).Count -gt 0)
if (-not $browserReady) {
    Write-Host "[next] Playwright Chromium not installed. Run:"
    Write-Host "       cd frontend; npx playwright install chromium"
    Write-Host "       then re-run this script."
    exit 2
}

$backendProc = $null
try {
    # -----------------------------------------------------------------------
    # 2. Optional real-stack probe with a throwaway token (hash in env only)
    # -----------------------------------------------------------------------
    if ($RealStack) {
        Write-Host "[real-stack] generating throwaway token (raw value not shown)"
        $tmpToken = python -c "import secrets; print(secrets.token_urlsafe(32))"
        $tmpHash  = python -c "import hashlib,sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest())" $tmpToken
        if ($VerboseTokenForDebug) { Write-Warning "DEBUG token: $tmpToken" }

        $env:MVP_SKIP_DOTENV = "1"            # never read the operator's .env
        $env:MVP_API_TOKEN_HASH = $tmpHash    # process env only; nothing on disk
        Write-Host "[real-stack] starting backend on 127.0.0.1:8377 ..."
        $backendProc = Start-Process -FilePath "python" `
            -ArgumentList @("-m","uvicorn","scripts.api_server:app","--host","127.0.0.1","--port","8377") `
            -WorkingDirectory $RepoRoot -WindowStyle Hidden -PassThru
        Start-Sleep -Seconds 5

        $codeNoTok = (Invoke-WebRequest -Uri "http://127.0.0.1:8377/manual-trades" -SkipHttpErrorCheck -UseBasicParsing).StatusCode
        $codeTok   = (Invoke-WebRequest -Uri "http://127.0.0.1:8377/manual-trades" -Headers @{Authorization="Bearer $tmpToken"} -SkipHttpErrorCheck -UseBasicParsing).StatusCode
        $codeHost  = (Invoke-WebRequest -Uri "http://127.0.0.1:8377/health" -Headers @{Host="rebind.attacker.example"} -SkipHttpErrorCheck -UseBasicParsing).StatusCode
        Write-Host "[real-stack] no-token=$codeNoTok (want 401)  with-token=$codeTok (want 200)  foreign-host=$codeHost (want 421)"
        if ($codeNoTok -ne 401 -or $codeTok -ne 200 -or $codeHost -ne 421) {
            Write-Error "real-stack owner-auth probe FAILED"
            exit 1
        }
        Write-Host "[real-stack] PASS"
    }

    # -----------------------------------------------------------------------
    # 3. Hermetic Playwright suite (config starts its own Next server)
    # -----------------------------------------------------------------------
    Push-Location $Frontend
    if (-not $SkipBuild) {
        Write-Host "[e2e] building production frontend ..."
        $env:NEXT_TELEMETRY_DISABLED = "1"
        npm run build
        if ($LASTEXITCODE -ne 0) { Write-Error "build failed"; exit 1 }
    }
    Write-Host "[e2e] running Playwright (route-mocked; no live backend needed) ..."
    npm run test:e2e
    $pwExit = $LASTEXITCODE
    Pop-Location
    if ($pwExit -ne 0) { Write-Error "playwright suite failed"; exit $pwExit }
    Write-Host "[e2e] PASS"
    exit 0
}
finally {
    # -----------------------------------------------------------------------
    # 4. Cleanup: kill backend, scrub token material from this session
    # -----------------------------------------------------------------------
    if ($backendProc -and -not $backendProc.HasExited) {
        Stop-Process -Id $backendProc.Id -Force -ErrorAction SilentlyContinue
        Write-Host "[cleanup] backend stopped"
    }
    Remove-Item Env:\MVP_API_TOKEN_HASH -ErrorAction SilentlyContinue
    Remove-Item Env:\MVP_SKIP_DOTENV -ErrorAction SilentlyContinue
    $tmpToken = $null; $tmpHash = $null
}
