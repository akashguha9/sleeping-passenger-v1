# ============================================================
# REPO-ROOT GUARD (advisory-only; no execution surface)
# ============================================================
# Auto-locate the repo root from this script's own path so the workflow runs
# correctly regardless of the caller's working directory.
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

# Verify we are actually at the repo root before doing anything else.
$repoMarkers = @(
  (Join-Path $RepoRoot "scripts\run_five_model_synthesis.ps1"),
  (Join-Path $RepoRoot "scripts\frontier_model_resolver.py"),
  (Join-Path $RepoRoot "data")
)
foreach ($marker in $repoMarkers) {
  if (-not (Test-Path $marker)) {
    throw "Run from $RepoRoot or launch using the full script path. Missing repo marker: $marker"
  }
}

# Shared, secret-safe API-key leak detection helpers (Get-FirstSecretMatch /
# Find-SecretMatchLines / Assert-NoSecretText / Get-SecretRedactionRegex).
# Dot-source the library so it is the SINGLE source of truth; an inline fallback
# (below) is defined only if the library is unavailable. Never prints secrets.
$secretScanLib = Join-Path $PSScriptRoot "secret_scan_lib.ps1"
if (Test-Path $secretScanLib) {
  . $secretScanLib
} else {
  Write-Host "secret_scan_lib.ps1 not found; using inline fallback secret detector."
}

# Pure, side-effect-free provider helpers (model-aware Claude body, Gemini model
# normalization, secret-safe error extraction, Mistral retry schedule, provider
# availability/placeholder text). Dot-sourced as the single source of truth so
# the orchestration is testable and never relies on a manual one-off edit.
$providerLib = Join-Path $PSScriptRoot "provider_lib.ps1"
if (Test-Path $providerLib) {
  . $providerLib
} else {
  throw "provider_lib.ps1 not found next to run_five_model_synthesis.ps1; cannot run provider-safe orchestration."
}

# ------------------------------------------------------------
# PROVIDER-SAFE ORCHESTRATION CONTROLS (env-tunable, safe defaults)
# ------------------------------------------------------------
# SP_ALLOW_PROVIDER_FAILURES  (default true)  - one provider failing does NOT
#                                                crash the whole run.
# SP_MIN_SYNTHESIS_PROVIDERS  (default 4)     - minimum successful providers
#                                                required before final synthesis.
# SP_FORCE_PROVIDER_RERUN     (default false) - ignore cached outputs, re-call.
# SP_REUSE_PROVIDER_OUTPUTS   (default true)  - reuse a cached, secret-clean
#                                                provider output instead of
#                                                re-calling that provider.
$AllowProviderFailures = ($env:SP_ALLOW_PROVIDER_FAILURES -ne 'false')
$ReuseProviderOutputs  = ($env:SP_REUSE_PROVIDER_OUTPUTS -ne 'false')
$ForceProviderRerun    = ($env:SP_FORCE_PROVIDER_RERUN -eq 'true')
$MinSynthesisProviders = 4
if ($env:SP_MIN_SYNTHESIS_PROVIDERS) {
  $parsedMin = 0
  if ([int]::TryParse($env:SP_MIN_SYNTHESIS_PROVIDERS, [ref]$parsedMin) -and $parsedMin -ge 1 -and $parsedMin -le 5) {
    $MinSynthesisProviders = $parsedMin
  }
}

$ErrorActionPreference = "Stop"

Remove-Variable response -ErrorAction SilentlyContinue
Remove-Variable result -ErrorAction SilentlyContinue
Remove-Variable gptResult -ErrorAction SilentlyContinue
Remove-Variable claudeResult -ErrorAction SilentlyContinue
Remove-Variable geminiResult -ErrorAction SilentlyContinue
Remove-Variable grokResult -ErrorAction SilentlyContinue
Remove-Variable mistralResult -ErrorAction SilentlyContinue
Remove-Variable synthesisResult -ErrorAction SilentlyContinue

$runDate = Get-Date -Format "yyyy-MM-dd"

# ============================================================
# MODEL IDS
# ============================================================
#
# Hardcoded seed defaults (used only if the frontier resolver is unavailable).
# These are NOT the source of truth â€” the resolver below selects the highest
# AVAILABLE model per provider from config/frontier_models.json, falls back
# honestly (never silently), and honours *_MODEL_OVERRIDE env vars. No code
# rewrite is needed to bump a model id; edit the registry config instead.

$OPENAI_ANALYST_MODEL  = "gpt-5.5"
$OPENAI_SYNTH_MODEL    = "gpt-5.5"
$CLAUDE_MODEL          = "claude-sonnet-4-6"
$GROK_MODEL            = "grok-4.3"
$GEMINI_MODEL          = "gemini-3.1-pro-preview"
$MISTRAL_MODEL         = "mistral-large-latest"

# ------------------------------------------------------------
# FRONTIER MODEL RESOLVER â€” highest-available-model-per-provider.
# Advisory/read-only: offline registry, no network, no broker, no secrets.
# Overrides the hardcoded defaults above ONLY when the resolver returns a
# non-empty model id; otherwise the hardcoded default is preserved (honest
# degrade). Fallback reasons are surfaced so a silent downgrade is impossible.
# ------------------------------------------------------------
try {
  $resolvedRaw = & python ".\scripts\frontier_model_resolver.py" --emit-shell-env 2>$null
  if ($resolvedRaw) {
    $resolved = @{}
    foreach ($line in $resolvedRaw) {
      if ($line -match "^([A-Z_]+)=(.*)$") { $resolved[$matches[1]] = $matches[2] }
    }
    if ($resolved["OPENAI_RESOLVED_MODEL"]) {
      $OPENAI_ANALYST_MODEL = $resolved["OPENAI_RESOLVED_MODEL"]
      $OPENAI_SYNTH_MODEL   = $resolved["OPENAI_RESOLVED_MODEL"]
    }
    if ($resolved["ANTHROPIC_RESOLVED_MODEL"]) { $CLAUDE_MODEL  = $resolved["ANTHROPIC_RESOLVED_MODEL"] }
    if ($resolved["XAI_RESOLVED_MODEL"])       { $GROK_MODEL    = $resolved["XAI_RESOLVED_MODEL"] }
    if ($resolved["GOOGLE_GEMINI_RESOLVED_MODEL"]) { $GEMINI_MODEL = $resolved["GOOGLE_GEMINI_RESOLVED_MODEL"] }
    if ($resolved["MISTRAL_RESOLVED_MODEL"])   { $MISTRAL_MODEL = $resolved["MISTRAL_RESOLVED_MODEL"] }
    foreach ($p in @("OPENAI","ANTHROPIC","XAI","GOOGLE_GEMINI","MISTRAL")) {
      $fallbackKey = "${p}_FALLBACK_USED"
      $reasonKey = "${p}_FALLBACK_REASON"
      if ($resolved[$fallbackKey] -eq "true") {
        $reason = $resolved[$reasonKey]
        Write-Host "  ! $p fallback in effect - reason: $reason (not a silent downgrade)"
      }
    }
  } else {
    Write-Host "Frontier resolver returned nothing; using hardcoded seed model ids."
  }
} catch {
  Write-Host "Frontier resolver unavailable; using hardcoded seed model ids."
}

# ------------------------------------------------------------
# MODEL-ID OVERRIDES + NORMALIZATION (applied regardless of resolver outcome).
# SP_CLAUDE_MODEL / SP_GEMINI_MODEL override resolver output; Resolve-GeminiModel
# also fixes the resolver-vs-served "gemini-3.1-pro" -> "gemini-3.1-pro-preview"
# 404 mismatch. Done in code (not a manual edit) so it is deterministic.
# ------------------------------------------------------------
if ($env:SP_CLAUDE_MODEL) {
  $CLAUDE_MODEL = $env:SP_CLAUDE_MODEL
  Write-Host "Claude model overridden by SP_CLAUDE_MODEL=$CLAUDE_MODEL"
}
$GEMINI_MODEL = Resolve-GeminiModel -ModelName $GEMINI_MODEL
if ($env:SP_GEMINI_MODEL) {
  Write-Host "Gemini model overridden by SP_GEMINI_MODEL=$GEMINI_MODEL"
}
Write-Host "Models in effect: OpenAI=$OPENAI_ANALYST_MODEL Claude=$CLAUDE_MODEL Grok=$GROK_MODEL Gemini=$GEMINI_MODEL Mistral=$MISTRAL_MODEL"

# ============================================================
# KEY VALIDATION
# ============================================================

if (-not $env:OPENAI_API_KEY) {
  throw "OPENAI_API_KEY is missing. Set it in this PowerShell window before running."
}

if (-not $env:OPENAI_API_KEY.StartsWith("sk-")) {
  throw "OPENAI_API_KEY exists but does not start with sk-."
}

if (-not $env:ANTHROPIC_API_KEY) {
  throw "ANTHROPIC_API_KEY is missing. Set it in this PowerShell window before running."
}

if (-not $env:ANTHROPIC_API_KEY.StartsWith("sk-ant-")) {
  throw "ANTHROPIC_API_KEY exists but does not start with sk-ant-."
}

if (-not $env:XAI_API_KEY) {
  throw "XAI_API_KEY is missing."
}

if (-not $env:XAI_API_KEY.StartsWith("xai-")) {
  throw "XAI_API_KEY exists but does not start with xai-."
}

if (-not $env:GEMINI_API_KEY) {
  throw "GEMINI_API_KEY is missing."
}

if (-not $env:MISTRAL_API_KEY) {
  throw "MISTRAL_API_KEY is missing."
}

Write-Host "All five API keys are available in this PowerShell session."

# ============================================================
# LOAD PROMPT FILES
# ============================================================

$gptPrompt     = Get-Content ".\prompts\gpt_daily_prompt.txt" -Raw -Encoding UTF8
$claudePrompt  = Get-Content ".\prompts\claude_daily_prompt.txt" -Raw -Encoding UTF8
$geminiPrompt  = Get-Content ".\prompts\gemini_daily_prompt.txt" -Raw -Encoding UTF8
$grokPrompt    = Get-Content ".\prompts\grok_daily_prompt.txt" -Raw -Encoding UTF8
$mistralPrompt = Get-Content ".\prompts\mistral_daily_prompt.txt" -Raw -Encoding UTF8

$gptPrompt     = $gptPrompt.Replace("{{RUN_DATE}}", $runDate)
$claudePrompt  = $claudePrompt.Replace("{{RUN_DATE}}", $runDate)
$geminiPrompt  = $geminiPrompt.Replace("{{RUN_DATE}}", $runDate)
$grokPrompt    = $grokPrompt.Replace("{{RUN_DATE}}", $runDate)
$mistralPrompt = $mistralPrompt.Replace("{{RUN_DATE}}", $runDate)

# ============================================================
# LOAD SHARED REPO CONTEXT
# ============================================================

$openPositions = ""
$signalLedger  = ""
$thresholds    = ""

if (Test-Path ".\moltbook\open_positions.json") {
  $openPositions = Get-Content ".\moltbook\open_positions.json" -Raw -Encoding UTF8
}

if (Test-Path ".\moltbook\signal_ledger.json") {
  $signalLedger = Get-Content ".\moltbook\signal_ledger.json" -Raw -Encoding UTF8
}

if (Test-Path ".\config\thresholds.yaml") {
  $thresholds = Get-Content ".\config\thresholds.yaml" -Raw -Encoding UTF8
}

# ------------------------------------------------------------
# DAILY PAYLOAD (v2) â€” verified truth + fresh discovery seeds
# ------------------------------------------------------------
# These nine files are the authoritative current-holdings/discovery inputs.
# moltbook/open_positions.json and signal_ledger.json are now demoted to
# HISTORICAL CONTEXT ONLY and may never override verified portfolio truth.

function Read-PayloadFile {
  param([string]$RelPath)
  if (Test-Path $RelPath) {
    return Get-Content $RelPath -Raw -Encoding UTF8
  }
  return "MISSING_FILE"
}

# ------------------------------------------------------------
# REFRESH DAILY PAYLOADS via the live bridges (signal_events + price).
# Advisory/read-only: this only rebuilds the regenerable today_* payload
# JSON inputs from canonical SQLite signal_events + market_data marks. It
# never calls a broker, never executes, and degrades honestly to the static
# fallback when no fresh live data exists.
# ------------------------------------------------------------
$payloadDir = Join-Path $RepoRoot "data\daily_payload"
$bridgeScript = Join-Path $RepoRoot "scripts\build_daily_payloads.py"
Write-Host "Rebuilding daily payloads via signal_events + price bridges (honest fallback if no live data)..."
if (Test-Path $bridgeScript) {
  # Run with ErrorActionPreference relaxed: a native command writing to stderr
  # must NOT be turned into a terminating error (the old "2>$null" under
  # ErrorActionPreference=Stop is exactly what produced the spurious
  # "bridge unavailable" message even on success). Success is judged by the
  # process exit code, not by stderr output.
  $prevEAP = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    $null = & python $bridgeScript 2>&1
    if ($LASTEXITCODE -eq 0) {
      Write-Host "Daily payloads rebuilt from live bridges (or honest static fallback)."
    } else {
      Write-Host "build_daily_payloads exited with code $LASTEXITCODE; reusing existing payload files from $payloadDir."
    }
  } catch {
    Write-Host "build_daily_payloads bridge unavailable; reusing existing payload files from $payloadDir."
  } finally {
    $ErrorActionPreference = $prevEAP
  }
} else {
  Write-Host "build_daily_payloads bridge unavailable; reusing existing payload files from $payloadDir."
}

# Stale-input warning: flag regenerable payload files older than 24h so the
# operator knows discovery may be running on stale inputs.
$staleThreshold = (Get-Date).AddHours(-24)
$regenerablePayloads = @(
  "today_market_snapshot.json",
  "today_price_movers.json",
  "today_news_events.json",
  "today_filings_events.json",
  "yesterday_final_candidates.json"
)
foreach ($pf in $regenerablePayloads) {
  $pfFull = Join-Path $payloadDir $pf
  if (Test-Path $pfFull) {
    $lastWrite = (Get-Item $pfFull).LastWriteTime
    if ($lastWrite -lt $staleThreshold) {
      Write-Host ("  ! STALE: {0} last updated {1:yyyy-MM-dd HH:mm} (>24h old) - discovery may be using stale inputs." -f $pf, $lastWrite)
    }
  } else {
    Write-Host ("  ! MISSING: {0} not found in {1}." -f $pf, $payloadDir)
  }
}

$verifiedHoldings   = Read-PayloadFile ".\data\daily_payload\verified_current_holdings.json"
$closedPositions    = Read-PayloadFile ".\data\daily_payload\closed_positions.json"
$soldPositions      = Read-PayloadFile ".\data\daily_payload\sold_positions.json"
$doNotTreatAsOpen   = Read-PayloadFile ".\data\daily_payload\do_not_treat_as_open.json"
$marketSnapshot     = Read-PayloadFile ".\data\daily_payload\today_market_snapshot.json"
$priceMovers        = Read-PayloadFile ".\data\daily_payload\today_price_movers.json"
$newsEvents         = Read-PayloadFile ".\data\daily_payload\today_news_events.json"
$filingsEvents      = Read-PayloadFile ".\data\daily_payload\today_filings_events.json"
$yesterdayCandidates = Read-PayloadFile ".\data\daily_payload\yesterday_final_candidates.json"

# Compute the Portfolio Truth Gate + discovery context block in Python so all
# five models receive the SAME authoritative truth header.
$portfolioTruthContext = ""
try {
  $portfolioTruthContext = & python ".\scripts\daily_synthesis_pipeline.py" --write 2>$null | Out-String
} catch {
  $portfolioTruthContext = "PORTFOLIO_TRUTH_GATE_UNAVAILABLE: could not run scripts/daily_synthesis_pipeline.py"
}
if ([string]::IsNullOrWhiteSpace($portfolioTruthContext)) {
  $portfolioTruthContext = "PORTFOLIO_TRUTH_GATE_UNAVAILABLE: empty output from daily_synthesis_pipeline.py"
}

$sharedContext = @"

$portfolioTruthContext

============================================================
DAILY PAYLOAD (v2) â€” VERIFIED TRUTH IS AUTHORITATIVE
============================================================

data/daily_payload/verified_current_holdings.json:
$verifiedHoldings

data/daily_payload/closed_positions.json:
$closedPositions

data/daily_payload/sold_positions.json:
$soldPositions

data/daily_payload/do_not_treat_as_open.json:
$doNotTreatAsOpen

data/daily_payload/today_market_snapshot.json:
$marketSnapshot

data/daily_payload/today_price_movers.json:
$priceMovers

data/daily_payload/today_news_events.json:
$newsEvents

data/daily_payload/today_filings_events.json:
$filingsEvents

data/daily_payload/yesterday_final_candidates.json:
$yesterdayCandidates

============================================================
HISTORICAL CONTEXT ONLY (NOT portfolio truth â€” never manage from these)
============================================================

moltbook/open_positions.json (STALE â€” historical/contaminated; do NOT treat as open):
$openPositions

============================================================

moltbook/signal_ledger.json (historical signal memory only):
$signalLedger

============================================================

config/thresholds.yaml:
$thresholds
"@

$sharedContext = [regex]::Replace($sharedContext, '[\uD800-\uDFFF]', '')

# ------------------------------------------------------------
# Secret-scan helpers. The dot-sourced scripts/secret_scan_lib.ps1 is the SINGLE
# source of truth (Get-FirstSecretMatch / Get-SecretClassPatterns /
# Assert-NoSecretText). These INLINE definitions are a fallback that is ONLY
# installed when the library is unavailable, so the main script and the library
# can never drift apart. Patterns are kept byte-identical to the library: STRICT
# base62 bodies + negative lookbehind/lookahead + same-line Bearer; matching via
# the explicit case-sensitive [regex]::IsMatch; single-object/$null return.
# Matched secret VALUES are never printed or returned.
# ------------------------------------------------------------
if (-not (Get-Command Get-FirstSecretMatch -ErrorAction SilentlyContinue)) {
  function Get-SecretClassPatterns {
    return [ordered]@{
      'ANTHROPIC_STYLE_KEY' = '(?<![A-Za-z0-9/_.\-])sk-ant-[A-Za-z0-9_\-]{20,}(?![A-Za-z0-9_\-])'
      'OPENAI_PROJECT_KEY'  = '(?<![A-Za-z0-9/_.\-])sk-(?:proj|svcacct|admin)-[A-Za-z0-9_\-]{20,}(?![A-Za-z0-9_\-])'
      'OPENAI_STYLE_KEY'    = '(?<![A-Za-z0-9/_.\-])sk-[A-Za-z0-9]{32,}(?![A-Za-z0-9_\-])'
      'XAI_STYLE_KEY'       = '(?<![A-Za-z0-9/_.\-])xai-[A-Za-z0-9]{20,}(?![A-Za-z0-9_\-])'
      'GOOGLE_STYLE_KEY'    = '(?<![A-Za-z0-9/_.\-])AIza[A-Za-z0-9_\-]{20,}(?![A-Za-z0-9_\-])'
      'BEARER_TOKEN'        = 'Bearer[ \t]+[A-Za-z0-9_\-]{20,}(?![A-Za-z0-9_\-])'
    }
  }
  function Get-FirstSecretMatch {
    param(
      [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text,
      [string]$Source = '<text>'
    )
    if ([string]::IsNullOrEmpty($Text)) { return $null }
    $patterns = Get-SecretClassPatterns
    $lineNo = 0
    foreach ($line in ($Text -split "`n")) {
      $lineNo++
      foreach ($cls in $patterns.Keys) {
        if ([regex]::IsMatch($line, $patterns[$cls])) {
          return [pscustomobject]@{ Source = $Source; Line = $lineNo; Class = $cls }
        }
      }
    }
    return $null
  }
  function Assert-NoSecretText {
    param(
      [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text,
      [Parameter(Mandatory = $true)][string]$Source
    )
    $hit = Get-FirstSecretMatch -Text $Text -Source $Source
    if ($null -ne $hit) {
      throw @"
ABORTED: prompt/context contains API-key-like text.
Matched source: $($hit.Source) (line $($hit.Line))
Pattern class: $($hit.Class)
Secret value was not printed.
Fix: run scripts/sanitize_generated_context.ps1 or delete stale generated payloads and rerun.
"@
    }
  }
}

# ============================================================
# SAFETY SCAN (secret-safe, line-by-line, named sources)
# ============================================================
# Scan ONLY the actual prompt/context strings that are about to be sent, plus
# the generated payload/context files they are built from. We never scan the
# whole repo, never .env, and never environment-variable dumps. Each source is
# scanned line-by-line so a match can never span two unrelated lines, and on a
# hit we name the exact file/line/pattern-class WITHOUT printing the secret.
$contextSources = [ordered]@{
  "prompts/gpt_daily_prompt.txt"                              = $gptPrompt
  "prompts/claude_daily_prompt.txt"                           = $claudePrompt
  "prompts/gemini_daily_prompt.txt"                           = $geminiPrompt
  "prompts/grok_daily_prompt.txt"                             = $grokPrompt
  "prompts/mistral_daily_prompt.txt"                          = $mistralPrompt
  "generated: daily_synthesis_pipeline.py (portfolio truth)"  = $portfolioTruthContext
  "data/daily_payload/verified_current_holdings.json"         = $verifiedHoldings
  "data/daily_payload/closed_positions.json"                  = $closedPositions
  "data/daily_payload/sold_positions.json"                    = $soldPositions
  "data/daily_payload/do_not_treat_as_open.json"              = $doNotTreatAsOpen
  "data/daily_payload/today_market_snapshot.json"             = $marketSnapshot
  "data/daily_payload/today_price_movers.json"                = $priceMovers
  "data/daily_payload/today_news_events.json"                 = $newsEvents
  "data/daily_payload/today_filings_events.json"              = $filingsEvents
  "data/daily_payload/yesterday_final_candidates.json"        = $yesterdayCandidates
  "moltbook/open_positions.json"                              = $openPositions
  "moltbook/signal_ledger.json"                               = $signalLedger
  "config/thresholds.yaml"                                    = $thresholds
}

$secretScanPassed = $true
foreach ($srcName in $contextSources.Keys) {
  $hit = Get-FirstSecretMatch -Text ([string]$contextSources[$srcName]) -Source $srcName
  if ($null -ne $hit) {
    $secretScanPassed = $false
    throw @"
ABORTED: prompt/context contains API-key-like text.
Matched source: $($hit.Source) (line $($hit.Line))
Pattern class: $($hit.Class)
Secret value was not printed.
Fix: run scripts/sanitize_generated_context.ps1 or delete stale generated payloads and rerun.
"@
  }
}

# ============================================================
# PREFLIGHT (no prompt contents, no secrets)
# ============================================================
$promptFilesToSend = @(
  "prompts/gpt_daily_prompt.txt",
  "prompts/claude_daily_prompt.txt",
  "prompts/gemini_daily_prompt.txt",
  "prompts/grok_daily_prompt.txt",
  "prompts/mistral_daily_prompt.txt"
)
Write-Host ""
Write-Host "============================================================"
Write-Host "PREFLIGHT"
Write-Host "============================================================"
Write-Host ("  Working directory : {0}" -f (Get-Location).Path)
Write-Host ("  Repo root         : {0}" -f $RepoRoot)
Write-Host "  Generated folders :"
foreach ($d in @("data", "data\daily_payload", "moltbook", "reports", "outputs", "tmp", "runtime")) {
  $exists = Test-Path (Join-Path $RepoRoot $d)
  Write-Host ("      {0,-22} {1}" -f $d, $(if ($exists) { "present" } else { "absent" }))
}
Write-Host "  Prompt/context files to be sent:"
foreach ($pf in $promptFilesToSend) { Write-Host ("      {0}" -f $pf) }
Write-Host ("      (+ assembled daily-payload context: {0} generated JSON inputs)" -f $regenerablePayloads.Count)
Write-Host ("  Secret scan       : {0}" -f $(if ($secretScanPassed) { "PASSED (no API-key-like text in prompt/context)" } else { "FAILED" }))
Write-Host ("  Models selected   : OpenAI={0} Claude={1} Grok={2} Gemini={3} Mistral={4}" -f $OPENAI_ANALYST_MODEL, $CLAUDE_MODEL, $GROK_MODEL, $GEMINI_MODEL, $MISTRAL_MODEL)
Write-Host "  NOTE: prompt contents are NOT printed (may contain advisory context); API keys are never printed."
Write-Host "============================================================"
Write-Host ""

# ============================================================
# HELPER FUNCTIONS
# ============================================================

function Get-OpenAIResponseText {
  param (
    [string]$PromptText,
    [string]$ModelName,
    [string]$SystemText,
    [string]$RawOutFile = ""
  )

  $headers = @{
    "Authorization" = "Bearer $env:OPENAI_API_KEY"
    "Content-Type"  = "application/json; charset=utf-8"
  }

  $bodyObj = @{
    model = $ModelName
    input = @(
      @{
        role = "system"
        content = $SystemText
      },
      @{
        role = "user"
        content = $PromptText
      }
    )
    reasoning = @{
      effort = "high"
    }
    max_output_tokens = 12000
  }

  $body = $bodyObj | ConvertTo-Json -Depth 60 -Compress

  $response = Invoke-RestMethod `
    -Uri "https://api.openai.com/v1/responses" `
    -Method Post `
    -Headers $headers `
    -Body ([System.Text.Encoding]::UTF8.GetBytes($body))

  if ($RawOutFile -and $RawOutFile.Trim().Length -gt 0) {
    $response | ConvertTo-Json -Depth 100 | Set-Content $RawOutFile -Encoding UTF8
  }

  $texts = New-Object System.Collections.Generic.List[string]

  if ($response.output_text) {
    $texts.Add([string]$response.output_text)
  }

  if ($response.output) {
    foreach ($item in $response.output) {
      if ($item.content) {
        foreach ($contentItem in $item.content) {
          if ($contentItem.text) {
            $texts.Add([string]$contentItem.text)
          }
          if ($contentItem.type -eq "output_text" -and $contentItem.text) {
            $texts.Add([string]$contentItem.text)
          }
        }
      }
    }
  }

  $text = ($texts | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) -join "`n"

  return $text
}

function Get-ClaudeResponseText {
  param (
    [string]$PromptText,
    [string]$ModelName
  )

  $headers = @{
    "x-api-key"          = $env:ANTHROPIC_API_KEY
    "anthropic-version" = "2023-06-01"
    "Content-Type"      = "application/json; charset=utf-8"
  }

  # Model-aware body (Get-ClaudeRequestBody from provider_lib.ps1): for Opus
  # 4.7+/4.8-style ids it omits temperature/top_p/top_k and old thinking-budget
  # shapes (which return 400); older Claude models keep temperature. A 400
  # model/parameter-compatibility error is caught by the safe provider runner,
  # which marks Claude unavailable (when SP_ALLOW_PROVIDER_FAILURES=true) instead
  # of crashing the whole run.
  $bodyObj = Get-ClaudeRequestBody -PromptText $PromptText -ModelName $ModelName

  $body = $bodyObj | ConvertTo-Json -Depth 60 -Compress

  $response = Invoke-RestMethod `
    -Uri "https://api.anthropic.com/v1/messages" `
    -Method Post `
    -Headers $headers `
    -Body ([System.Text.Encoding]::UTF8.GetBytes($body))

  $text = ""

  if ($response.content) {
    $text = ($response.content | Where-Object { $_.text } | ForEach-Object { $_.text }) -join "`n"
  }

  return $text
}

function Get-GrokResponseText {
  param (
    [string]$PromptText,
    [string]$ModelName
  )

  $headers = @{
    "Authorization" = "Bearer $env:XAI_API_KEY"
    "Content-Type"  = "application/json; charset=utf-8"
  }

  $bodyObj = @{
    model = $ModelName
    messages = @(
      @{
        role = "system"
        content = "You are Grok, an independent advisory-only narrative/crowd-pressure analyst for zzz_passenger's MVP. No execution. No broker action. No repository modification. No database update. Use only pasted context. Never reveal, infer, repeat, transform, summarize, or request API keys, secrets, tokens, Bearer headers, or environment variables."
      },
      @{
        role = "user"
        content = $PromptText
      }
    )
    temperature = 0.2
    max_tokens = 8000
  }

  $body = $bodyObj | ConvertTo-Json -Depth 60 -Compress

  $response = Invoke-RestMethod `
    -Uri "https://api.x.ai/v1/chat/completions" `
    -Method Post `
    -Headers $headers `
    -Body ([System.Text.Encoding]::UTF8.GetBytes($body))

  $text = ""

  if ($response.choices -and $response.choices[0].message -and $response.choices[0].message.content) {
    $text = $response.choices[0].message.content
  }

  return $text
}

function Get-GeminiResponseText {
  param (
    [string]$PromptText,
    [string]$ModelName
  )

  $bodyObj = @{
    contents = @(
      @{
        parts = @(
          @{
            text = @"
System instruction:
You are Gemini, an independent long-context synthesis analyst for zzz_passenger's MVP.
No execution.
No broker action.
No repository modification.
No database update.
Use only pasted context.
Never reveal, infer, repeat, transform, summarize, or request API keys, secrets, tokens, Bearer headers, or environment variables.

User prompt:
$PromptText
"@
          }
        )
      }
    )
    generationConfig = @{
      temperature = 0.2
      maxOutputTokens = 8000
    }
  }

  $body = $bodyObj | ConvertTo-Json -Depth 60 -Compress

  $response = Invoke-RestMethod `
    -Uri "https://generativelanguage.googleapis.com/v1beta/models/$ModelName`:generateContent?key=$env:GEMINI_API_KEY" `
    -Method Post `
    -ContentType "application/json; charset=utf-8" `
    -Body ([System.Text.Encoding]::UTF8.GetBytes($body))

  $text = ""

  if ($response.candidates -and $response.candidates[0].content -and $response.candidates[0].content.parts) {
    $text = ($response.candidates[0].content.parts | ForEach-Object { $_.text }) -join "`n"
  }

  return $text
}

function Get-MistralResponseText {
  param (
    [string]$PromptText,
    [string]$ModelName
  )

  $headers = @{
    "Authorization" = "Bearer $env:MISTRAL_API_KEY"
    "Content-Type"  = "application/json; charset=utf-8"
  }

  $bodyObj = @{
    model = $ModelName
    messages = @(
      @{
        role = "system"
        content = "You are Mistral, an independent European/international reasoning lens for zzz_passenger's MVP. No execution. No broker action. No repository modification. No database update. Use only pasted context. Never reveal, infer, repeat, transform, summarize, or request API keys, secrets, tokens, Bearer headers, or environment variables."
      },
      @{
        role = "user"
        content = $PromptText
      }
    )
    temperature = 0.2
    max_tokens = 8000
  }

  $body = $bodyObj | ConvertTo-Json -Depth 60 -Compress

  # Retry on rate limiting (HTTP 429 / type rate_limited / code 1300) with the
  # backoff schedule from provider_lib (15s, 45s, 90s). Keys/prompts are never
  # printed: the only diagnostics come from Get-SafeProviderError. After the
  # retries are exhausted the last error is re-thrown so the safe provider runner
  # can mark Mistral unavailable and continue if enough providers remain.
  $mistralUri = "https://api.mistral.ai/v1/chat/completions"
  $delays = Get-MistralRetryDelaysSeconds
  $attempt = 0
  $response = $null
  while ($true) {
    try {
      $response = Invoke-RestMethod `
        -Uri $mistralUri `
        -Method Post `
        -Headers $headers `
        -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
      break
    } catch {
      $safe = Get-SafeProviderError -ErrorRecord $_ -Provider "Mistral" -Model $ModelName
      $isRateLimited = ($safe.Status -eq '429') -or ($safe.Code -eq '1300') -or ($safe.Type -match 'rate')
      if ($isRateLimited -and $attempt -lt $delays.Count) {
        $wait = $delays[$attempt]
        $attempt++
        Write-Host ("Mistral rate limited; retrying in {0} seconds... (attempt {1}/{2})" -f $wait, $attempt, $delays.Count)
        Start-Sleep -Seconds $wait
        continue
      }
      throw
    }
  }

  $text = ""

  if ($response.choices -and $response.choices[0].message -and $response.choices[0].message.content) {
    $text = $response.choices[0].message.content
  }

  return $text
}

# ============================================================
# SAFE PROVIDER RUNNER (fault-tolerant + resumable + secret-scanned)
# ============================================================
# Wraps a single provider call so that:
#   * a previously-saved, secret-clean output is REUSED (resume) unless
#     SP_FORCE_PROVIDER_RERUN=true, so a late failure (e.g. a Mistral 429) does
#     NOT force re-calling GPT/Claude/Gemini/Grok that already succeeded;
#   * on success the output is secret-scanned and saved to a deterministic
#     per-run cache file before any downstream use;
#   * on failure the provider is recorded UNAVAILABLE with a sanitized
#     status/type/code/message (never the key, never the prompt), and the run
#     continues when SP_ALLOW_PROVIDER_FAILURES=true.
# Returns a result object: Name / Key / Model / Available / Text / Reason /
# CacheFile / FromCache.
function Invoke-SafeProvider {
  param(
    [string]$Name,
    [string]$Key,
    [string]$Model,
    [scriptblock]$Call,
    [string]$CacheDir,
    [bool]$AllowFailures,
    [bool]$ReuseOutputs,
    [bool]$ForceRerun
  )

  $cacheFile = Join-Path $CacheDir ("{0}.txt" -f $Key)
  $result = [pscustomobject]@{
    Name      = $Name
    Key       = $Key
    Model     = $Model
    Available = $false
    Text      = ""
    Reason    = ""
    CacheFile = $cacheFile
    FromCache = $false
  }

  # ---- Resume: reuse a cached, non-empty, secret-clean output ----
  if ($ReuseOutputs -and (-not $ForceRerun) -and (Test-Path $cacheFile)) {
    $cached = Get-Content $cacheFile -Raw -Encoding UTF8
    if (-not [string]::IsNullOrWhiteSpace($cached)) {
      $hit = Get-FirstSecretMatch -Text $cached -Source ("cached:{0}" -f $Key)
      if ($null -eq $hit) {
        Write-Host ("Reusing cached {0} output from {1}" -f $Name, $cacheFile)
        $result.Available = $true
        $result.Text      = $cached
        $result.FromCache = $true
        return $result
      } else {
        Write-Host ("Cached {0} output failed secret scan (class {1}); ignoring cache and re-calling provider." -f $Name, $hit.Class)
      }
    }
  }

  # ---- Live call ----
  Write-Host ("Running {0} analyst (model={1})..." -f $Name, $Model)
  $text = $null
  try {
    $text = & $Call
  } catch {
    $safe = Get-SafeProviderError -ErrorRecord $_ -Provider $Name -Model $Model
    $result.Reason = ("status={0} type={1} code={2} message={3}" -f $safe.Status, $safe.Type, $safe.Code, $safe.Message)
    Write-Host ("  ! {0} unavailable: {1}" -f $Name, $result.Reason)
    if (-not $AllowFailures) {
      throw ("{0} provider failed and SP_ALLOW_PROVIDER_FAILURES=false: {1}" -f $Name, $result.Reason)
    }
    return $result
  }

  if ([string]::IsNullOrWhiteSpace($text)) {
    $result.Reason = "empty output"
    Write-Host ("  ! {0} returned empty output." -f $Name)
    if (-not $AllowFailures) { throw ("{0} analyst output was empty." -f $Name) }
    return $result
  }

  # Secret-scan BEFORE saving or any downstream use; tainted output is dropped.
  $hit = Get-FirstSecretMatch -Text $text -Source ("{0} analyst output" -f $Name)
  if ($null -ne $hit) {
    $result.Reason = ("output failed secret scan (class {0}); not saved" -f $hit.Class)
    Write-Host ("  ! {0} output flagged by secret scan (class {1}); marking unavailable and NOT saving." -f $Name, $hit.Class)
    if (-not $AllowFailures) { throw ("ABORTED: {0} output failed secret scan (class {1})." -f $Name, $hit.Class) }
    return $result
  }

  $text | Set-Content $cacheFile -Encoding UTF8
  Write-Host ("  {0} OK; saved to {1}" -f $Name, $cacheFile)
  $result.Available = $true
  $result.Text      = $text
  return $result
}

# ============================================================
# BUILD FULL PROMPTS
# ============================================================

$gptFullPrompt = @"
$gptPrompt
$sharedContext
"@

$claudeFullPrompt = @"
$claudePrompt
$sharedContext
"@

$geminiFullPrompt = @"
$geminiPrompt
$sharedContext
"@

$grokFullPrompt = @"
$grokPrompt
$sharedContext
"@

$mistralFullPrompt = @"
$mistralPrompt
$sharedContext
"@

$gptFullPrompt     = [regex]::Replace($gptFullPrompt, '[\uD800-\uDFFF]', '')
$claudeFullPrompt  = [regex]::Replace($claudeFullPrompt, '[\uD800-\uDFFF]', '')
$geminiFullPrompt  = [regex]::Replace($geminiFullPrompt, '[\uD800-\uDFFF]', '')
$grokFullPrompt    = [regex]::Replace($grokFullPrompt, '[\uD800-\uDFFF]', '')
$mistralFullPrompt = [regex]::Replace($mistralFullPrompt, '[\uD800-\uDFFF]', '')

# ============================================================
# RUN FIVE INDEPENDENT ANALYST MODELS (provider-safe + resumable)
# ============================================================
# Each provider runs through Invoke-SafeProvider: a late failure on one provider
# never forces re-calling the providers that already succeeded, and each output
# is secret-scanned + cached before any downstream use.

$cacheDir = Join-Path $RepoRoot ("runtime\five_model_synthesis\{0}" -f $runDate)
if (-not (Test-Path $cacheDir)) {
  New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null
}
Write-Host ("Provider output cache dir: {0}" -f $cacheDir)
Write-Host ("Orchestration: allow_failures={0} reuse_outputs={1} force_rerun={2} min_providers={3}" -f $AllowProviderFailures, $ReuseProviderOutputs, $ForceProviderRerun, $MinSynthesisProviders)

$gptProvider = Invoke-SafeProvider -Name "GPT" -Key "gpt" -Model $OPENAI_ANALYST_MODEL `
  -CacheDir $cacheDir -AllowFailures $AllowProviderFailures -ReuseOutputs $ReuseProviderOutputs -ForceRerun $ForceProviderRerun `
  -Call {
    Get-OpenAIResponseText `
      -PromptText $gptFullPrompt `
      -ModelName $OPENAI_ANALYST_MODEL `
      -SystemText "You are GPT, an independent advisory-only analyst for zzz_passenger's MVP. No execution. No broker action. No repository modification. No database update. Use only pasted context. Never reveal, infer, repeat, transform, summarize, or request API keys, secrets, tokens, Bearer headers, or environment variables."
  }

$claudeProvider = Invoke-SafeProvider -Name "Claude" -Key "claude" -Model $CLAUDE_MODEL `
  -CacheDir $cacheDir -AllowFailures $AllowProviderFailures -ReuseOutputs $ReuseProviderOutputs -ForceRerun $ForceProviderRerun `
  -Call {
    Get-ClaudeResponseText -PromptText $claudeFullPrompt -ModelName $CLAUDE_MODEL
  }

$geminiProvider = Invoke-SafeProvider -Name "Gemini" -Key "gemini" -Model $GEMINI_MODEL `
  -CacheDir $cacheDir -AllowFailures $AllowProviderFailures -ReuseOutputs $ReuseProviderOutputs -ForceRerun $ForceProviderRerun `
  -Call {
    Get-GeminiResponseText -PromptText $geminiFullPrompt -ModelName $GEMINI_MODEL
  }

$grokProvider = Invoke-SafeProvider -Name "Grok" -Key "grok" -Model $GROK_MODEL `
  -CacheDir $cacheDir -AllowFailures $AllowProviderFailures -ReuseOutputs $ReuseProviderOutputs -ForceRerun $ForceProviderRerun `
  -Call {
    Get-GrokResponseText -PromptText $grokFullPrompt -ModelName $GROK_MODEL
  }

$mistralProvider = Invoke-SafeProvider -Name "Mistral" -Key "mistral" -Model $MISTRAL_MODEL `
  -CacheDir $cacheDir -AllowFailures $AllowProviderFailures -ReuseOutputs $ReuseProviderOutputs -ForceRerun $ForceProviderRerun `
  -Call {
    Get-MistralResponseText -PromptText $mistralFullPrompt -ModelName $MISTRAL_MODEL
  }

$providerResults = @($gptProvider, $claudeProvider, $geminiProvider, $grokProvider, $mistralProvider)

# ============================================================
# PROVIDER AVAILABILITY GATE (partial-availability tolerant)
# ============================================================
$availableProviders = @($providerResults | Where-Object { $_.Available })
$availableCount = $availableProviders.Count
Write-Host ""
Write-Host "============================================================"
Write-Host "PROVIDER AVAILABILITY"
Write-Host "============================================================"
foreach ($p in $providerResults) {
  if ($p.Available) {
    $tag = if ($p.FromCache) { "available (cached)" } else { "available" }
    Write-Host ("  {0,-8} {1}" -f $p.Name, $tag)
  } else {
    Write-Host ("  {0,-8} unavailable - {1}" -f $p.Name, $p.Reason)
  }
}
Write-Host ("  {0}/5 providers available (minimum required = {1})." -f $availableCount, $MinSynthesisProviders)
Write-Host "============================================================"
Write-Host ""

if ($availableCount -lt $MinSynthesisProviders) {
  throw ("ABORTED: fewer than {0} providers succeeded; no robust synthesis possible. ({1}/5 available)" -f $MinSynthesisProviders, $availableCount)
}

# Resolve each provider's text (real output, or a secret-safe placeholder so the
# synthesizer treats it as missing rather than fabricating that provider's view).
$gptResult     = if ($gptProvider.Available)     { $gptProvider.Text }     else { Get-ProviderUnavailablePlaceholder -Provider "GPT"     -Reason $gptProvider.Reason }
$claudeResult  = if ($claudeProvider.Available)  { $claudeProvider.Text }  else { Get-ProviderUnavailablePlaceholder -Provider "Claude"  -Reason $claudeProvider.Reason }
$geminiResult  = if ($geminiProvider.Available)  { $geminiProvider.Text }  else { Get-ProviderUnavailablePlaceholder -Provider "Gemini"  -Reason $geminiProvider.Reason }
$grokResult    = if ($grokProvider.Available)    { $grokProvider.Text }    else { Get-ProviderUnavailablePlaceholder -Provider "Grok"    -Reason $grokProvider.Reason }
$mistralResult = if ($mistralProvider.Available) { $mistralProvider.Text } else { Get-ProviderUnavailablePlaceholder -Provider "Mistral" -Reason $mistralProvider.Reason }

$providerAvailabilitySection = Get-ProviderAvailabilitySection -Providers $providerResults

# ============================================================
# FINAL FIVE-MODEL SYNTHESIS PROMPT
# ============================================================

$synthesisPrompt = @"
for $runDate - running this combined all-5 synthesis prompt -

You are operating as the FINAL SYNTHESIS ANALYST for my MVP stock-signal workflow.

You are NOT one of the five source models.
You are the judge/synthesizer reading five independent AI model reports:

1. ChatGPT / GPT
2. Claude
3. Gemini
4. Grok
5. Mistral

============================================================
PROVIDER AVAILABILITY (read before synthesizing)
============================================================
$providerAvailabilitySection

If a provider is listed as unavailable, its response below is a
PROVIDER_UNAVAILABLE placeholder. Do NOT fabricate that provider's view; treat
it as missing and synthesize only from the providers that are available. Note in
the Model-by-Model Summary which providers were unavailable and why.

Your job is to compare, reconcile, challenge, and synthesize all five model outputs into one final paper-trading decision report.

IMPORTANT:
You are not executing trades.
You are not instructing me to buy, sell, short, exit, close, cancel broker orders, or use leverage.
You are not allowed to place orders.
You are not allowed to connect to brokers.
You are not allowed to modify my repository.
You are not allowed to reconcile trades yourself.
You are not allowed to update the database.
Final buy/hold/exit/reconciliation decisions are made manually by the human operator only.

This is advisory-only.
Treat paper trades as if they were real money trades.
Year 1 priority is survival first, learning second, scaling third.

============================================================
CORE OBJECTIVE
============================================================

Read all five AI responses below and answer:

â€œGiven the combined evidence from ChatGPT, Claude, Gemini, Grok, and Mistral, what stocks, if any, should be considered for paper-trade human review today?â€

You must also answer:

1. Are new paper trades allowed by the combined evidence?
2. Are existing trades more urgent than new trades?
3. Are there any stop-loss / invalidation breaches?
4. Are there any partial take-profit candidates?
5. Are there any duplicate / bad / suspect manual trade rows?
6. Is reconciliation clean enough to add new paper trades?
7. Is source health / live price data good enough?
8. Which model is being too aggressive?
9. Which model is being too conservative?
10. Which model found the most important risk?
11. Which model found the most useful candidate names?
12. What is the final action board?

============================================================
NON-NEGOTIABLE EXECUTION POLICY
============================================================

- Human operator makes all final decisions.
- AI models provide advisory inputs only.
- Indian equities: human operator may consider long-only exposure up to 4x, but 4x is the absolute ceiling, not the default.
- Rest-of-world equities: spot-only analysis. No leverage assumption.
- No shorts unless explicitly requested.
- No auto-execution.
- No broker execution.
- No broker cancellation.
- No revenge trading.
- No averaging down unless explicitly requested and separately justified.
- No trade idea without invalidation logic.
- No open trade should remain open if invalidation has clearly triggered.
- No signal should be promoted if it cannot survive Year-1 survival rules.
- No new trade idea should be promoted if existing reconciliation hygiene is poor or open-trade risk is unresolved.
- Treat paper trades as real money trades for discipline purposes.

Core rule:
Survive first.
Learn second.
Scale third.

============================================================
ABSOLUTE RISK-GATE RULES
============================================================

If any of these are true, final classification must be downgraded:

1. Reconciliation is dirty.
2. Current prices are missing for existing open trades.
3. Source health is stale, synthetic, seeded, placeholder, or collapsed.
4. MVP state is DIABLO / Jail Mode / policy veto / chaos veto.
5. allow_new_risk=false.
6. Existing trades have unresolved stop/invalidation breaches.
7. Existing leveraged Indian trades are unresolved or suspect.
8. Duplicate rows or venue/currency errors exist.
9. Model outputs disagree strongly and no clean signal survives.
10. Candidate has no clear invalidation.
11. Candidate cannot generate useful Moltbook learning.
12. Candidate is redundant with existing unresolved exposure.

If one model says BUY but another model identifies a hard data/reconciliation/policy block, the block wins unless there is strong evidence the block is wrong.

If Claude identifies a repo/policy/reconciliation hard block, treat it as highly important.

If Grok identifies narrative opportunity but repo hygiene is dirty, classify as WATCHLIST or WAIT, not BUY-CANDIDATE.

If Gemini or Mistral identify macro uncertainty, downgrade aggression.

If GPT identifies fake confidence or missing data, downgrade.

============================================================
PORTFOLIO TRUTH AUDIT â€” MANDATORY FIRST STEP (before reading consensus)
============================================================

Before you read any model's consensus, establish portfolio truth using the
PORTFOLIO TRUTH GATE block and the data/daily_payload/* files in the context.

Compute and display:
  H = V MINUS (C UNION S UNION D)
    V = OPEN tickers in verified_current_holdings.json
    C = CLOSED/EXITED/SOLD tickers in closed_positions.json
    S = tickers in sold_positions.json
    D = not_owned_do_not_manage UNION closed_or_sold_positions

Rules that override everything below:
- Only tickers in H are current holdings. SELL / EXIT REVIEW is allowed ONLY for
  tickers in H. If a ticker is not in H, SELL / EXIT REVIEW is forbidden.
- UNG, TIP, TLT, FCG, GLD must NOT be managed/exited/TP'd/held unless they are
  in H. moltbook/open_positions.json and signal_ledger.json are HISTORICAL ONLY.
- Phantom positions must NOT block fresh discovery. "No executable trade" is
  allowed; "no candidates" is NOT allowed unless discovery truly failed and you
  log the failure explicitly.

Model Contamination Audit â€” for each model compute:
  contamination_score(model) = phantom_management_mentions / max(1, total_position_management_mentions)
If contamination_score > 0, mark that model's portfolio-management section as
contaminated, but do NOT discard its fresh-discovery section unless that section
also relies on false holdings.

L_TODAY INVARIANT (HARD â€” applies to every candidate any model names):
The PORTFOLIO TRUTH GATE context block above contains an L_TODAY INVARIANT
section with: L_today (live-discovered set), static_universe, memory_only_stale,
phantom/closed/sold, verified holdings H, the TOP-30 COUNTRY COVERAGE PROOF, and
USA BIAS + FALLBACK CONTAMINATION metrics. Enforce:
  - A candidate may be a LIVE_DISCOVERED_CANDIDATE / EXECUTABLE-PAPER-BUY ONLY if
    it appears in L_today. Otherwise it is at most RESEARCH_ONLY_STATIC,
    MEMORY_ONLY_STALE, EXISTING_POSITION_REVIEW (if in H), PHANTOM_QUARANTINE
    (if closed/sold), or MODEL_PRIOR_ONLY (invented, in no payload).
  - Static-universe / model-prior names can NEVER be executable buys.
  - If the country coverage proof is missing/weak (low C_global), state that
    global discovery is DEGRADED or FAILED. Do NOT fill missing countries from
    your own priors and call it discovery.
  - Surface B_US / USA_bias_violation and R_static / R_live. A US name is not
    blocked for being US, but a high R_static / zero R_live means the board is
    research-grade, not live global discovery.

Fresh Cross-Model Candidate Board â€” rank by:
  ACQS(t) = CQS(t) * exp(-0.25 * days_without_fresh_signal)   (memory decay)
  FCS(t) = 0.25*ACQS + 0.20*mean_model_score + 0.15*cross_model_agreement
           + 0.15*why_today_score + 0.10*data_quality + 0.10*freshness
           + 0.05*liquidity_quality - 0.10*chaos_risk
           - 0.10*normalized_disagreement - 0.15*portfolio_contamination_penalty
  cross_model_agreement(t) = models_mentioning_t / 5
  normalized_disagreement(t) = min(1, std(model_scores[t]) / 0.50)
Execution Readiness:
  ERS(t) = 0.25*data_quality + 0.20*source_health + 0.15*invalidation_defined
           + 0.15*sizing_defined + 0.10*portfolio_truth_clean + 0.10*why_today_score
           + 0.05*human_review_ready
Classification (EXECUTABLE is the strictest tier â€” all must hold):
  EXECUTABLE-PAPER-BUY iff FCS>=0.70 AND ERS>=0.75 AND why_today_score>=0.70
    AND source_health>=0.70 AND invalidation_defined AND position_sizing_defined
    AND normalized_disagreement<0.35 AND t NOT in (closed/sold/do_not_treat_as_open)
    AND advisory_only AND human_execution_required
  FCS>=0.70 but any executable condition fails -> BUY-CANDIDATE / NOT-EXECUTABLE (say why)
  FCS>=0.65 and normalized_disagreement>=0.35   -> RESEARCH_CANDIDATE
  0.55<=FCS<0.70           -> WATCHLIST
  0.40<=FCS<0.55           -> WAIT
  FCS<0.40 or chaos>=0.80  -> AVOID

============================================================
OUTPUT FORMAT
============================================================

# Five-Model MVP Synthesis Report

## 0. Portfolio Truth Audit

Show H, closed/sold, do-not-treat-as-open, phantom mentions, and which model
sections were contaminated by phantom management. Then continue.

## 0a. Fresh Payload + Universe + Why-Today + Memory-Decay + Disagreement Audit

Before the candidate board, run these five audits using the daily payload and
the five model reports:

1. Fresh Payload Health Audit â€” for each of today_market_snapshot, today_price_movers,
   today_news_events, today_filings_events: report source_health, provider, is_live,
   record count. If is_live=false / source_health=UNVERIFIED, say discovery is
   UNDERPOWERED and candidates are research-grade. Never claim live data on a fallback.
2. Minimum Daily Universe Coverage Audit â€” confirm the minimum viable universe
   (US mega-cap, defense, energy, semis, India large-cap, Europe large-cap, macro
   ETFs, high-beta watch) was scanned. U_today = U_static âˆª U_price âˆª U_news âˆª
   U_filings âˆª U_yesterday âˆª U_old âˆª U_model. Membership does NOT imply ownership.
3. Why-Today Audit â€” every candidate must answer "Why today, not yesterday?".
   why_today_score < 0.70 => cannot be EXECUTABLE (still may be BUY-CANDIDATE /
   NOT-EXECUTABLE). Flag names whose why-today is static-fallback (0.25) or stale
   repeat (0.10).
4. Memory Decay Audit â€” repeated yesterday names with no fresh evidence decay by
   score_today = score_yesterday * exp(-0.25 * days_without_fresh_signal)
   (d=3 -> 0.472). A fresh signal today resets d=0.
5. Model Disagreement Audit â€” DisagreementScore(t) = variance(model_scores[t]);
   NormalizedDisagreement = min(1, std/0.50). High score + low disagreement =
   CLEAN_CONSENSUS; high score + high disagreement = RESEARCH_CANDIDATE; low score
   + high disagreement = uncertainty/avoid.

## 0b. Fresh Cross-Model Candidate Board

| Ticker | Bucket/Sector | Why today? | Freshness | Data quality | Candidate score | Execution readiness | Disagreement/uncertainty notes | Classification |
|---|---|---|---|---|---:|---:|---|---|

Also keep the FCS/ERS view:

| Ticker | Models Mentioning | Freshness | FCS | ERS | Candidate Quality | Execution Quality | Classification | Why |
|---|---|---:|---:|---|---|---|---|---|

Mandatory final boards (each must be present, "None" only with proof of search):
- Executable paper buys
- Buy-candidate but not executable
- Watchlist upgrades
- Sell/exit review for VERIFIED holdings (t in H) only
- Avoid/sell-bias candidates
- Stale/remove candidates
- Phantom-position quarantine board
- Moltbook logging sentence

Hard final rule: if executable buys = none, still provide
"Top 5 fresh candidates to study today."

## 1. Executive Verdict

Give one final classification:

- CLEAN FOR PAPER PROBES
- PROBE-ONLY
- EXISTING-POSITION MANAGEMENT ONLY
- JAIL MODE
- DIABLO / NO NEW RISK

Then give 5-10 blunt bullets explaining why.

You must explicitly answer:

| Final Gate | Answer |
|---|---|
| Can new paper trades be considered today? | |
| Should existing trades be managed first? | |
| Is reconciliation clean enough? | |
| Is source health good enough? | |
| Are current prices available enough? | |
| Is there any stop/invalidation breach? | |
| Is there any partial TP candidate? | |
| Is there any duplicate/suspect trade row? | |
| Max aggression level today | |
| Cash / patience recommended? | |

---

## 2. Model-by-Model Summary

| Model | Main Verdict | Best Useful Signal | Biggest Warning | Candidate Names Mentioned | Existing-Trade Warning | Aggression Level | Reliability Today |
|---|---|---|---|---|---|---|---|
| ChatGPT / GPT | | | | | | | |
| Claude | | | | | | | |
| Gemini | | | | | | | |
| Grok | | | | | | | |
| Mistral | | | | | | | |

Reliability Today must be one of:
- High
- Medium
- Low
- Unusable / Data-conflicted

---

## 3. Consensus Map

| Issue | ChatGPT / GPT | Claude | Gemini | Grok | Mistral | Final Synthesis |
|---|---|---|---|---|---|---|
| New-risk permission | | | | | | |
| Reconciliation hygiene | | | | | | |
| Source health / live data | | | | | | |
| Existing trades needing exit review | | | | | | |
| Partial TP candidates | | | | | | |
| Best stock candidates | | | | | | |
| Stocks to avoid | | | | | | |
| Biggest portfolio risk | | | | | | |
| Biggest data/repo risk | | | | | | |
| Final regime | | | | | | |

Explain the consensus and disagreement in plain English below the table.

---

## 4. Contradiction / Conflict Audit

| Conflict | Models Involved | What They Disagree On | Which Side Wins | Why |
|---|---|---|---|---|

---

## 5. Existing Trade Management Board

| Ticker / Trade | Mentioned By Which Models | Current Issue | Stop / Invalidation Status | TP Status | Final Classification | Human Review Action |
|---|---|---|---|---|---|---|

Rules:
- Existing trades come before new trades.
- If invalidation hit, classify INVALIDATION-HIT / EXIT-CANDIDATE.
- If TP hit, classify PARTIAL-TAKE-PROFIT-CANDIDATE.
- If no current price, classify DATA-INSUFFICIENT.
- If duplicate, classify DUPLICATE / CANCEL-LOCAL-LOG.
- Do not say â€œsell now.â€
- Say â€œmanual exit review candidateâ€ or â€œmanual partial TP review candidate.â€

---

## 6. Candidate Stock Cross-Vote Board

List every stock mentioned by any model.

| Rank | Ticker | Stock | Market | Mentioned By | Bull Case | Bear / Blocker Case | Existing Exposure? | Final Classification | Trigger Needed Before Human Review |
|---:|---|---|---|---|---|---|---|---|---|

Rules:
- Rank by survival quality, not excitement.
- Do not promote redundant exposure.
- If candidate already exists in open book, mark MANAGEMENT-ONLY unless there is a clear reason to add.
- If Reconciliation is dirty, classify as WAIT or DIABLO / NO NEW RISK.
- If source health is poor, classify as DATA-LIMITED.
- If candidate lacks invalidation, downgrade.
- If candidate is only narrative hype, downgrade.
- If candidate has clear feedback value but cannot be acted on today, mark WATCHLIST / WAIT.

---

## 7. Final Buy / Watch / Wait / Avoid Board

| Category | Tickers | Reason |
|---|---|---|
| BUY-CANDIDATE FOR HUMAN REVIEW | | |
| WATCHLIST | | |
| WAIT | | |
| AVOID | | |
| DIABLO / NO NEW RISK | | |
| EXISTING-POSITION MANAGEMENT ONLY | | |

Rules:
- It is valid for BUY-CANDIDATE to be â€œNone.â€
- Do not force a buy.
- If the five-model synthesis says â€œno clean buys,â€ say so.
- Paper trade still counts as real-risk discipline.
- If existing trades are unresolved, prioritize management over new names.

---

## 8. Leverage Suitability Under Year-1 Rules

For Indian equities only:
- spot only
- 1-2x max
- 2-3x max
- 3-4x max only if unusually clean
- not suitable for leverage

For rest-of-world equities:
- spot only
- avoid

| Ticker | Market | Final Classification | Max Sensible Exposure Band | Why | Main Leverage / Sizing Risk | Survival Score | Moltbook Feedback Value |
|---|---|---|---|---|---|---:|---:|

Rules:
- 4x is absolute ceiling for India, not default.
- Survival score below 7 = no leverage.
- High chaos = no leverage.
- Dirty reconciliation = no leverage.
- Existing unresolved leveraged Indian trades = no leverage.
- Rest-of-world = spot only or avoid.

---

## 9. Final Paper-Trade Decision

Answer directly:

â€œNow Iâ€™m running paper trades. Tell me which stocks to buy with ticker. Treat paper trade as real money trade.â€

Use this exact table:

| Decision Slot | Answer |
|---|---|
| Final answer: should I add new paper trades today? | |
| If yes, maximum number of new paper trades | |
| If yes, ticker 1 | |
| If yes, ticker 2 | |
| If yes, ticker 3 | |
| If no, why no? | |
| Existing trades to manage first | |
| Existing trades needing exit review | |
| Existing trades needing partial TP review | |
| Existing trades needing stop tightening | |
| Duplicate / suspect rows to clean | |
| Cash / patience verdict | |

Important:
If the answer is â€œno new trades,â€ do NOT still sneak in buy recommendations.
Instead give:
- â€œNo new paper buys todayâ€
- â€œExisting-position management onlyâ€
- â€œTop watchlist names once gate clearsâ€

---

## 10. Top Watchlist Once Gate Clears

Even if new trades are blocked, give the best 3-7 tickers to watch once gates clear.

| Rank | Ticker | Stock | Market | Why Watch | What Must Clear First | Invalidation To Define Before Entry |
|---:|---|---|---|---|---|---|

Rules:
- These are not buys.
- These are future watchlist names only.
- Must include blockers.

---

## 11. Moltbook / Reconciliation Logging Plan

| Item | What To Log | Why It Matters | Learning Value |
|---|---|---|---:|

Include:
- accepted paper trade candidates,
- rejected candidates,
- existing trade exits,
- partial TP decisions,
- duplicate cancellations,
- data-insufficient trades,
- model disagreement,
- false confidence warnings.

---

## 12. Brutal Final Verdict

Give a direct brutal answer in plain English.

Include:
- One-line regime verdict.
- Whether to buy anything today.
- Which existing trades need attention first.
- Which model's warning mattered most.
- Which model's candidate list was most useful.
- Which stocks are tempting but should be ignored.
- What would change the answer tomorrow.
- Maximum appropriate aggression level.
- One sentence that the operator should copy into Moltbook.

Final disclaimer:
This is advisory only. No broker action, no repository modification, no reconciliation/database update, and no trade execution is authorized.

============================================================
PASTE THE FIVE MODEL RESPONSES BELOW
============================================================

1. ChatGPT gave me this response -

$gptResult


2. Claude gave me this response -

$claudeResult


3. Gemini gave me this response -

$geminiResult


4. Grok gave me this response -

$grokResult


5. Mistral gave me this response -

$mistralResult


============================================================
FINAL USER QUESTION
============================================================

Now Iâ€™m running paper trades. Tell me which stocks to buy with ticker.
Treat paper trade as real money trade.
Use the combined five-model synthesis above.
Do not force buys if the correct answer is no new risk.
"@

$synthesisPrompt = [regex]::Replace($synthesisPrompt, '[\uD800-\uDFFF]', '')

Assert-NoSecretText -Text $synthesisPrompt -Source "final synthesis prompt"

# ============================================================
# RUN FINAL SYNTHESIS
# ============================================================

Write-Host "Running final all-5 synthesis..."

$rawSynthesisFile = ".\moltbook\five_model_synthesis_raw_response_$runDate.json"

$synthesisResult = Get-OpenAIResponseText `
  -PromptText $synthesisPrompt `
  -ModelName $OPENAI_SYNTH_MODEL `
  -SystemText "You are the final five-model synthesis analyst for zzz_passenger's MVP. You compare GPT, Claude, Gemini, Grok, and Mistral outputs. You are advisory only. No execution. No broker action. No repository modification. No database update. Never reveal or request secrets." `
  -RawOutFile $rawSynthesisFile

if ([string]::IsNullOrWhiteSpace($synthesisResult)) {
  Write-Host "Final synthesis output was empty. Opening raw response JSON."
  notepad $rawSynthesisFile
  throw "Final synthesis output was empty. Report was NOT written. Check raw JSON for status, output, content, text, refusal, or max_output_tokens exhaustion."
}

# Secret-safe check BEFORE writing the report to disk (report is not written on abort).
Assert-NoSecretText -Text $synthesisResult -Source "final synthesis output (report NOT written on abort)"

$outFile = ".\moltbook\five_model_synthesis_report_$runDate.txt"

$synthesisResult | Set-Content $outFile -Encoding UTF8

notepad $outFile



