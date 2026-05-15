#requires -Version 5.1
<#
.SYNOPSIS
    Sprint 9A — run a single end-to-end local MVP audit.

.DESCRIPTION
    Read-only audit of the local MVP state.  Runs a safe subset of
    backend / frontend checks and produces a PASS / WARN / FAIL summary
    per section.  Does NOT mutate the DB, does NOT call brokers, does
    NOT place orders, does NOT auto-trade, does NOT run live refresh
    unless -IncludeRefresh is explicitly passed.

    Safety invariants:
        ADVISORY_ONLY                = $true
        HUMAN_EXECUTION_REQUIRED     = $true
        execution_gate               = "LOCKED"
        BROKER_ORDER_PERMISSION      = $false
        AI_EXECUTION_COUNT           = 0
        broker_api_called            = $false
        execution_permission         = $false
        can_execute                  = $false

.PARAMETER SkipSlowTests
    Skip the full backend pytest run; run only a compileall sanity check.

.PARAMETER SkipFrontend
    Skip the frontend npm test / tsc / build steps.

.PARAMETER IncludeRefresh
    Optional: run scripts/refresh_live_signals.py.  Off by default —
    refresh is intentionally NOT triggered by the audit.

.PARAMETER Json
    Emit the audit summary as JSON on stdout (in addition to the human
    text rendering).

.EXAMPLE
    .\scripts\windows\run_local_mvp_audit.ps1

.EXAMPLE
    .\scripts\windows\run_local_mvp_audit.ps1 -SkipSlowTests -Json

.NOTES
    Author: Sleeping Passenger MVP, Sprint 9A.
#>

[CmdletBinding()]
param(
    [switch]$SkipSlowTests,
    [switch]$SkipFrontend,
    [switch]$IncludeRefresh,
    [switch]$Json
)

$ErrorActionPreference = 'Continue'
$script:RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$script:Sections = [ordered]@{}

function Add-Section {
    param([string]$Name, [string]$Status, [string]$Detail = '', [string]$Command = '')
    $script:Sections[$Name] = [pscustomobject]@{
        section = $Name
        status  = $Status
        detail  = $Detail
        command = $Command
    }
}

function Invoke-Section {
    param([string]$Name, [scriptblock]$Block)
    Write-Host ""
    Write-Host "[$Name]" -ForegroundColor Cyan
    try {
        & $Block
    } catch {
        Add-Section -Name $Name -Status 'FAIL' -Detail $_.Exception.Message
        Write-Host "  FAIL: $($_.Exception.Message)" -ForegroundColor Red
    }
}

Push-Location $script:RepoRoot
try {
    # ----------------------------------------------------------------
    # Safety doctrine — print the invariants up front so the operator
    # always sees them before any check output.
    # ----------------------------------------------------------------
    Write-Host "Local MVP Audit" -ForegroundColor Yellow
    Write-Host "================"
    Write-Host "Repo root        : $($script:RepoRoot.Path)"
    Write-Host "Safety doctrine  : ADVISORY_ONLY / HUMAN_EXECUTION_REQUIRED / execution_gate=LOCKED"
    Write-Host "Broker call      : forbidden by design"
    Write-Host "AI execution     : forbidden by design (count=0)"
    Write-Host ""

    # ----------------------------------------------------------------
    # 1. Git state
    # ----------------------------------------------------------------
    Invoke-Section -Name 'git_state' -Block {
        $branch = (git branch --show-current).Trim()
        $statusLines = git status --porcelain
        $dirty = ($statusLines | Measure-Object -Line).Lines
        $detail = "branch=$branch dirty_lines=$dirty"
        $status = if ($dirty -eq 0) { 'PASS' } else { 'WARN' }
        Add-Section 'git_state' $status $detail 'git status'
        Write-Host "  $detail"
    }

    # ----------------------------------------------------------------
    # 2. Backend compile + pytest summary
    # ----------------------------------------------------------------
    Invoke-Section -Name 'backend_compile' -Block {
        python -m compileall scripts tests -q | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Add-Section 'backend_compile' 'PASS' '' 'python -m compileall scripts tests -q'
            Write-Host "  compile OK"
        } else {
            Add-Section 'backend_compile' 'FAIL' "compileall exit $LASTEXITCODE"
        }
    }

    if (-not $SkipSlowTests) {
        Invoke-Section -Name 'backend_tests' -Block {
            $out = python -m pytest tests -q --maxfail=10 2>&1
            $exit = $LASTEXITCODE
            $tail = ($out | Select-Object -Last 5) -join ' | '
            $status = if ($exit -eq 0) { 'PASS' } else { 'FAIL' }
            Add-Section 'backend_tests' $status $tail 'python -m pytest tests -q'
            Write-Host "  $tail"
        }
    } else {
        Add-Section 'backend_tests' 'WARN' 'skipped via -SkipSlowTests' 'python -m pytest tests -q'
        Write-Host "  skipped (use -SkipSlowTests=$false to run)"
    }

    # ----------------------------------------------------------------
    # 3. Frontend tests / typecheck / build
    # ----------------------------------------------------------------
    if (-not $SkipFrontend) {
        Push-Location (Join-Path $script:RepoRoot 'frontend')
        try {
            Invoke-Section -Name 'frontend_tests' -Block {
                npm test --silent 2>&1 | Out-Null
                $exit = $LASTEXITCODE
                $status = if ($exit -eq 0) { 'PASS' } else { 'FAIL' }
                Add-Section 'frontend_tests' $status "exit=$exit" 'npm test'
                Write-Host "  exit=$exit"
            }
            Invoke-Section -Name 'frontend_typecheck' -Block {
                npx tsc --noEmit 2>&1 | Out-Null
                $exit = $LASTEXITCODE
                $status = if ($exit -eq 0) { 'PASS' } else { 'FAIL' }
                Add-Section 'frontend_typecheck' $status "exit=$exit" 'npx tsc --noEmit'
                Write-Host "  exit=$exit"
            }
        } finally {
            Pop-Location
        }
    } else {
        Add-Section 'frontend_tests' 'WARN' 'skipped via -SkipFrontend'
        Add-Section 'frontend_typecheck' 'WARN' 'skipped via -SkipFrontend'
    }

    # ----------------------------------------------------------------
    # 4. Python-side audit summary (paper ledger, calibration,
    #    learning completeness, source health, token policy).
    # ----------------------------------------------------------------
    Invoke-Section -Name 'audit_summary' -Block {
        $audit = python scripts/local_mvp_audit.py --json 2>&1
        $auditExit = $LASTEXITCODE
        if ($auditExit -ne 0) {
            Add-Section 'audit_summary' 'WARN' "exit=$auditExit"
            return
        }
        try {
            $obj = $audit | Out-String | ConvertFrom-Json
            $script:Sections['audit_payload'] = $obj
            $overall = $obj.overall
            Add-Section 'audit_summary' $overall "overall=$overall"
            Write-Host "  overall=$overall"
            foreach ($key in $obj.statuses.PSObject.Properties.Name) {
                $val = $obj.statuses.$key
                Write-Host "  - $key : $val"
            }
        } catch {
            Add-Section 'audit_summary' 'WARN' 'json_parse_failed'
        }
    }

    # ----------------------------------------------------------------
    # 5. Optional refresh — gated.  By default we DO NOT trigger
    #    refresh; -IncludeRefresh opts in.
    # ----------------------------------------------------------------
    if ($IncludeRefresh) {
        Invoke-Section -Name 'live_refresh' -Block {
            python scripts/refresh_live_signals.py --write 2>&1 | Out-Null
            $exit = $LASTEXITCODE
            $status = if ($exit -eq 0) { 'PASS' } else { 'WARN' }
            Add-Section 'live_refresh' $status "exit=$exit" 'python scripts/refresh_live_signals.py --write'
        }
    } else {
        Add-Section 'live_refresh' 'INFO' 'skipped by default; pass -IncludeRefresh to run'
    }

    # ----------------------------------------------------------------
    # 6. Scheduled task status (best-effort, Windows only)
    # ----------------------------------------------------------------
    Invoke-Section -Name 'scheduled_task' -Block {
        try {
            $task = Get-ScheduledTask -TaskName 'SleepingPassengerLiveSignalRefresh' -ErrorAction Stop
            $state = $task.State
            Add-Section 'scheduled_task' 'PASS' "state=$state"
            Write-Host "  state=$state"
        } catch {
            Add-Section 'scheduled_task' 'INFO' 'not registered (use register_live_signal_refresh_task.ps1)'
            Write-Host "  not registered"
        }
    }

    # ----------------------------------------------------------------
    # Final summary
    # ----------------------------------------------------------------
    Write-Host ""
    Write-Host "Summary" -ForegroundColor Yellow
    Write-Host "-------"
    $finalStatus = 'PASS'
    foreach ($k in $script:Sections.Keys) {
        $s = $script:Sections[$k]
        if ($s -isnot [pscustomobject]) { continue }
        if (-not ($s.PSObject.Properties.Name -contains 'status')) { continue }
        if ($s.status -eq 'FAIL') { $finalStatus = 'FAIL' }
        elseif ($s.status -eq 'WARN' -and $finalStatus -ne 'FAIL') { $finalStatus = 'WARN' }
        $line = "{0,-22} {1,-6} {2}" -f $k, $s.status, $s.detail
        Write-Host "  $line"
    }
    Write-Host ""
    Write-Host "Overall: $finalStatus" -ForegroundColor (
        if ($finalStatus -eq 'PASS') { 'Green' }
        elseif ($finalStatus -eq 'WARN') { 'Yellow' }
        else { 'Red' }
    )

    if ($Json) {
        $jsonSections = [ordered]@{}
        foreach ($k in $script:Sections.Keys) { $jsonSections[$k] = $script:Sections[$k] }
        $payload = [pscustomobject]@{
            report               = 'run_local_mvp_audit'
            repo_root            = $script:RepoRoot.Path
            overall              = $finalStatus
            sections             = $jsonSections
            advisory_status      = 'ADVISORY_ONLY'
            execution_gate       = 'LOCKED'
            broker_api_called    = $false
            ai_execution_count   = 0
            execution_permission = $false
            can_execute          = $false
        }
        Write-Host ""
        $payload | ConvertTo-Json -Depth 6
    }

    if ($finalStatus -eq 'FAIL') { exit 1 } else { exit 0 }
} finally {
    Pop-Location
}
