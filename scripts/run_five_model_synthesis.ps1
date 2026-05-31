cd "C:\Users\akash\sleeping-passenger-v1"

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
# These are NOT the source of truth — the resolver below selects the highest
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
# FRONTIER MODEL RESOLVER — highest-available-model-per-provider.
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
    Write-Host "Frontier resolver selected: OpenAI=$OPENAI_ANALYST_MODEL Claude=$CLAUDE_MODEL Grok=$GROK_MODEL Gemini=$GEMINI_MODEL Mistral=$MISTRAL_MODEL"
    foreach ($p in @("OPENAI","ANTHROPIC","XAI","GOOGLE_GEMINI","MISTRAL")) {
      if ($resolved["${p}_FALLBACK_USED"] -eq "true") {
        Write-Host "  ! $p fallback in effect — reason: $($resolved["${p}_FALLBACK_REASON"]) (not a silent downgrade)"
      }
    }
  } else {
    Write-Host "Frontier resolver returned nothing; using hardcoded seed model ids."
  }
} catch {
  Write-Host "Frontier resolver unavailable; using hardcoded seed model ids."
}

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
# DAILY PAYLOAD (v2) — verified truth + fresh discovery seeds
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
Write-Host "Rebuilding daily payloads via signal_events + price bridges (honest fallback if no live data)..."
try {
  & python ".\scripts\build_daily_payloads.py" 2>$null | Out-Null
} catch {
  Write-Host "build_daily_payloads bridge unavailable; using existing payload files."
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
DAILY PAYLOAD (v2) — VERIFIED TRUTH IS AUTHORITATIVE
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
HISTORICAL CONTEXT ONLY (NOT portfolio truth — never manage from these)
============================================================

moltbook/open_positions.json (STALE — historical/contaminated; do NOT treat as open):
$openPositions

============================================================

moltbook/signal_ledger.json (historical signal memory only):
$signalLedger

============================================================

config/thresholds.yaml:
$thresholds
"@

$sharedContext = [regex]::Replace($sharedContext, '[\uD800-\uDFFF]', '')

# ============================================================
# SAFETY SCAN
# ============================================================

$keyPattern = "sk-[A-Za-z0-9_\-]{20,}|sk-ant-[A-Za-z0-9_\-]{20,}|xai-[A-Za-z0-9_\-]{20,}|AIza[A-Za-z0-9_\-]{20,}|Bearer\s+[A-Za-z0-9_\-]{20,}"

$allPromptsAndContext = @"
$gptPrompt
$claudePrompt
$geminiPrompt
$grokPrompt
$mistralPrompt
$sharedContext
"@

if ($allPromptsAndContext -match $keyPattern) {
  throw "ABORTED: prompt/context contains API-key-like text. Clean prompt/context before sending."
}

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

  $bodyObj = @{
    model = $ModelName
    max_tokens = 8000
    temperature = 0.2
    system = "You are Claude, an independent advisory-only analyst for zzz_passenger's MVP. No execution. No broker action. No repository modification. No database update. Use only pasted context. Never reveal, infer, repeat, transform, summarize, or request API keys, secrets, tokens, Bearer headers, or environment variables."
    messages = @(
      @{
        role = "user"
        content = $PromptText
      }
    )
  }

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

  $response = Invoke-RestMethod `
    -Uri "https://api.mistral.ai/v1/chat/completions" `
    -Method Post `
    -Headers $headers `
    -Body ([System.Text.Encoding]::UTF8.GetBytes($body))

  $text = ""

  if ($response.choices -and $response.choices[0].message -and $response.choices[0].message.content) {
    $text = $response.choices[0].message.content
  }

  return $text
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
# RUN FIVE INDEPENDENT ANALYST MODELS
# ============================================================

Write-Host "Running GPT analyst..."
$gptResult = Get-OpenAIResponseText `
  -PromptText $gptFullPrompt `
  -ModelName $OPENAI_ANALYST_MODEL `
  -SystemText "You are GPT, an independent advisory-only analyst for zzz_passenger's MVP. No execution. No broker action. No repository modification. No database update. Use only pasted context. Never reveal, infer, repeat, transform, summarize, or request API keys, secrets, tokens, Bearer headers, or environment variables."

if ([string]::IsNullOrWhiteSpace($gptResult)) {
  throw "GPT analyst output was empty."
}

if ($gptResult -match $keyPattern) {
  throw "ABORTED: GPT analyst output contains API-key-like text."
}

Write-Host "Running Claude analyst..."
$claudeResult = Get-ClaudeResponseText `
  -PromptText $claudeFullPrompt `
  -ModelName $CLAUDE_MODEL

if ([string]::IsNullOrWhiteSpace($claudeResult)) {
  throw "Claude analyst output was empty."
}

if ($claudeResult -match $keyPattern) {
  throw "ABORTED: Claude analyst output contains API-key-like text."
}

Write-Host "Running Gemini analyst..."
$geminiResult = Get-GeminiResponseText `
  -PromptText $geminiFullPrompt `
  -ModelName $GEMINI_MODEL

if ([string]::IsNullOrWhiteSpace($geminiResult)) {
  throw "Gemini analyst output was empty."
}

if ($geminiResult -match $keyPattern) {
  throw "ABORTED: Gemini analyst output contains API-key-like text."
}

Write-Host "Running Grok analyst..."
$grokResult = Get-GrokResponseText `
  -PromptText $grokFullPrompt `
  -ModelName $GROK_MODEL

if ([string]::IsNullOrWhiteSpace($grokResult)) {
  throw "Grok analyst output was empty."
}

if ($grokResult -match $keyPattern) {
  throw "ABORTED: Grok analyst output contains API-key-like text."
}

Write-Host "Running Mistral analyst..."
$mistralResult = Get-MistralResponseText `
  -PromptText $mistralFullPrompt `
  -ModelName $MISTRAL_MODEL

if ([string]::IsNullOrWhiteSpace($mistralResult)) {
  throw "Mistral analyst output was empty."
}

if ($mistralResult -match $keyPattern) {
  throw "ABORTED: Mistral analyst output contains API-key-like text."
}

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

“Given the combined evidence from ChatGPT, Claude, Gemini, Grok, and Mistral, what stocks, if any, should be considered for paper-trade human review today?”

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
PORTFOLIO TRUTH AUDIT — MANDATORY FIRST STEP (before reading consensus)
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

Model Contamination Audit — for each model compute:
  contamination_score(model) = phantom_management_mentions / max(1, total_position_management_mentions)
If contamination_score > 0, mark that model's portfolio-management section as
contaminated, but do NOT discard its fresh-discovery section unless that section
also relies on false holdings.

L_TODAY INVARIANT (HARD — applies to every candidate any model names):
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

Fresh Cross-Model Candidate Board — rank by:
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
Classification (EXECUTABLE is the strictest tier — all must hold):
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

1. Fresh Payload Health Audit — for each of today_market_snapshot, today_price_movers,
   today_news_events, today_filings_events: report source_health, provider, is_live,
   record count. If is_live=false / source_health=UNVERIFIED, say discovery is
   UNDERPOWERED and candidates are research-grade. Never claim live data on a fallback.
2. Minimum Daily Universe Coverage Audit — confirm the minimum viable universe
   (US mega-cap, defense, energy, semis, India large-cap, Europe large-cap, macro
   ETFs, high-beta watch) was scanned. U_today = U_static ∪ U_price ∪ U_news ∪
   U_filings ∪ U_yesterday ∪ U_old ∪ U_model. Membership does NOT imply ownership.
3. Why-Today Audit — every candidate must answer "Why today, not yesterday?".
   why_today_score < 0.70 => cannot be EXECUTABLE (still may be BUY-CANDIDATE /
   NOT-EXECUTABLE). Flag names whose why-today is static-fallback (0.25) or stale
   repeat (0.10).
4. Memory Decay Audit — repeated yesterday names with no fresh evidence decay by
   score_today = score_yesterday * exp(-0.25 * days_without_fresh_signal)
   (d=3 -> 0.472). A fresh signal today resets d=0.
5. Model Disagreement Audit — DisagreementScore(t) = variance(model_scores[t]);
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
- Do not say “sell now.”
- Say “manual exit review candidate” or “manual partial TP review candidate.”

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
- It is valid for BUY-CANDIDATE to be “None.”
- Do not force a buy.
- If the five-model synthesis says “no clean buys,” say so.
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

“Now I’m running paper trades. Tell me which stocks to buy with ticker. Treat paper trade as real money trade.”

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
If the answer is “no new trades,” do NOT still sneak in buy recommendations.
Instead give:
- “No new paper buys today”
- “Existing-position management only”
- “Top watchlist names once gate clears”

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

Now I’m running paper trades. Tell me which stocks to buy with ticker.
Treat paper trade as real money trade.
Use the combined five-model synthesis above.
Do not force buys if the correct answer is no new risk.
"@

$synthesisPrompt = [regex]::Replace($synthesisPrompt, '[\uD800-\uDFFF]', '')

if ($synthesisPrompt -match $keyPattern) {
  throw "ABORTED: synthesis prompt contains API-key-like text."
}

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

if ($synthesisResult -match $keyPattern) {
  throw "ABORTED: final synthesis output contains API-key-like text. Report was NOT written."
}

$outFile = ".\moltbook\five_model_synthesis_report_$runDate.txt"

$synthesisResult | Set-Content $outFile -Encoding UTF8

notepad $outFile