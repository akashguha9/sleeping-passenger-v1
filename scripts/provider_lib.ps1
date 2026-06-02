# ============================================================
# provider_lib.ps1  -  pure, side-effect-free provider helpers
# ============================================================
# Advisory-only. This library is dot-sourced by run_five_model_synthesis.ps1
# AND by the test-suite in isolation. It performs NO network calls, NO key
# validation, NO file writes, and has NO top-level side effects on load, so it
# can be loaded by tests without API keys present.
#
# It NEVER prints, returns, logs, or serializes a matched secret value: the
# error-extraction helper redacts API-key-like substrings before returning.
# ============================================================

# Secret-redaction regex lives in the single-source-of-truth secret_scan_lib.ps1.
# Load it here ONLY if the host script has not already provided it (so tests can
# dot-source this file standalone). secret_scan_lib defines functions only -> no
# side effects on load.
if (-not (Get-Command Get-SecretRedactionRegex -ErrorAction SilentlyContinue)) {
  $___secretLib = Join-Path $PSScriptRoot "secret_scan_lib.ps1"
  if (Test-Path $___secretLib) { . $___secretLib }
}

function Test-IsClaudeOpus47Plus {
  <#
    True for Claude Opus 4.7 / 4.8 (and 4.9 / 5.x) style model ids, which reject
    sampling params (temperature / top_p / top_k) and legacy thinking-budget
    shapes. Used to decide whether to OMIT those fields from the request body.
    Matches both hyphenated ("opus-4-8") and dotted ("opus-4.8") id spellings.
  #>
  param([string]$ModelName)
  if ([string]::IsNullOrWhiteSpace($ModelName)) { return $false }
  $m = $ModelName.ToLowerInvariant()
  if ($m -match 'opus-4[-.](7|8|9)')  { return $true }
  if ($m -match 'opus-(5|6|7|8|9)')   { return $true }
  return $false
}

function Get-ClaudeRequestBody {
  <#
    Build the Anthropic /v1/messages request body as a hashtable (caller
    ConvertTo-Json's it). MODEL-AWARE by design, NOT via a manual regex edit:
      * Opus 4.7+/4.8-style models -> omit temperature / top_p / top_k and any
        old thinking-budget shape. Keep only model / max_tokens / system /
        messages (the anthropic-version header is set by the caller).
      * Older Claude models (sonnet / haiku / opus<=4.6) -> include temperature.
    top_p / top_k are NEVER added for any Claude model.
  #>
  param(
    [string]$PromptText,
    [string]$ModelName,
    [string]$SystemText = ""
  )
  if ([string]::IsNullOrWhiteSpace($SystemText)) {
    $SystemText = "You are Claude, an independent advisory-only analyst for zzz_passenger's MVP. No execution. No broker action. No repository modification. No database update. Use only pasted context. Never reveal, infer, repeat, transform, summarize, or request API keys, secrets, tokens, Bearer headers, or environment variables."
  }
  $body = @{
    model      = $ModelName
    max_tokens = 8000
    system     = $SystemText
    messages   = @(
      @{
        role    = "user"
        content = $PromptText
      }
    )
  }
  if (-not (Test-IsClaudeOpus47Plus -ModelName $ModelName)) {
    # Older Claude models accept sampling params; opus 4.7+/4.8 reject them.
    $body.temperature = 0.2
  }
  return $body
}

function Resolve-GeminiModel {
  <#
    Normalize the Gemini model id so a resolver-selected "gemini-3.1-pro" (which
    the API answers with 404) becomes the served "gemini-3.1-pro-preview".
    SP_GEMINI_MODEL, when set, overrides everything (used as-is).
  #>
  param([string]$ModelName)
  if ($env:SP_GEMINI_MODEL) { return $env:SP_GEMINI_MODEL }
  if ($ModelName -eq 'gemini-3.1-pro') { return 'gemini-3.1-pro-preview' }
  return $ModelName
}

function Get-MistralRetryDelaysSeconds {
  # Backoff schedule for Mistral 429 / rate_limited / code 1300 retries.
  # Two retries: 20s then 45s. On a 429 we wait 20s and retry once; on another
  # 429 we wait 45s and retry once; if it still 429s the caller returns a
  # structured degraded result (see New-MistralDegradedResult) instead of looping
  # forever or crashing the run. Defined here so it is unit-testable without
  # making a network call or printing secrets.
  return @(20, 45)
}

function New-MistralDegradedResult {
  <#
    Structured DEGRADED result returned by Get-MistralResponseText after the
    Mistral 429 rate-limit retries (20s, 45s) are exhausted. usable=$false signals
    the safe provider runner (Invoke-SafeProvider) to record Mistral UNAVAILABLE
    and exclude it from the final vote WITHOUT crashing the run. Carries no
    secret and no prompt text.
  #>
  return [pscustomobject]@{
    provider      = "mistral"
    status        = "RATE_LIMITED"
    usable        = $false
    advisory_text = "Mistral unavailable due to rate limit; excluded from final vote."
  }
}

function Get-MistralSynthesisModel {
  <#
    The Mistral model id used for five-model synthesis. Defaults to a
    rate-limit-safe small model and is overridden by the MISTRAL_MODEL env var.
    This is DELIBERATELY not the resolver's highest-capability pick: the larger
    Mistral models (e.g. mistral-medium-3.5) have a low ~25k-tokens/min rate limit
    that 429s on the large synthesis prompt, so the synthesis runner pins a
    smaller, higher-throughput model here.
  #>
  param([string]$Default = "mistral-small-2506")
  if (-not [string]::IsNullOrWhiteSpace($env:MISTRAL_MODEL)) { return $env:MISTRAL_MODEL }
  return $Default
}

function Get-MistralSynthesisMaxTokens {
  <#
    The max_tokens cap for the Mistral synthesis call. Defaults to 1200 and is
    overridden by the MISTRAL_SYNTHESIS_MAX_TOKENS env var (must be a positive
    integer; otherwise the default is used). Keeping Mistral's output small helps
    stay under its rate limit.
  #>
  param([int]$Default = 1200)
  if (-not [string]::IsNullOrWhiteSpace($env:MISTRAL_SYNTHESIS_MAX_TOKENS)) {
    $parsed = 0
    if ([int]::TryParse($env:MISTRAL_SYNTHESIS_MAX_TOKENS, [ref]$parsed) -and $parsed -ge 1) {
      return $parsed
    }
  }
  return $Default
}

function Get-MistralAdversarialPrompt {
  <#
    Build the COMPACT adversarial-review prompt for Mistral. Mistral deliberately
    does NOT receive the full raw daily payload (it is large and 429s on a low
    rate limit). Instead it receives its base lens prompt plus the CONDENSED
    portfolio-truth summary, framed as an adversarial reviewer that stress-tests
    today's thesis. Pure/string-only: no network, no secrets.
  #>
  param(
    [string]$BasePrompt,
    [string]$TruthContext
  )
  $truth = if ([string]::IsNullOrWhiteSpace($TruthContext)) { "PORTFOLIO_TRUTH_SUMMARY_UNAVAILABLE" } else { $TruthContext }
  return @"
$BasePrompt

============================================================
COMPACT ADVERSARIAL-REVIEW MODE (rate-limit-safe)
============================================================
You are running as a COMPACT ADVERSARIAL REVIEWER, not a full analyst. To stay
under your provider rate limit you have deliberately been given a CONDENSED
context (the portfolio-truth summary below) and NOT the full raw daily payload.

Your job: stress-test today's emerging thesis. Be terse and high-signal:
- Name the strongest reasons today's candidates could be WRONG.
- Surface the biggest macro / policy / reconciliation / data-quality risks.
- Flag anything the other models are likely to over-trust.
Advisory-only. No execution. Do not request the omitted full payload.

============================================================
CONDENSED CONTEXT (portfolio-truth summary only; full payload intentionally omitted)
============================================================
$truth
"@
}

function Get-RetryAfterSeconds {
  <#
    Extract the Retry-After header value from a caught provider ErrorRecord's HTTP
    response, if present. Returns "" when absent. Never throws and never reads or
    prints API keys (it touches only the response headers, not auth headers).
  #>
  param($ErrorRecord)
  $val = ""
  try {
    $resp = $null
    try { $resp = $ErrorRecord.Exception.Response } catch {}
    if ($resp) {
      $h = $null
      try { $h = $resp.Headers["Retry-After"] } catch {}
      if ([string]::IsNullOrWhiteSpace([string]$h)) {
        try { $h = ($resp.Headers.GetValues("Retry-After")) -join "," } catch {}
      }
      if (-not [string]::IsNullOrWhiteSpace([string]$h)) { $val = [string]$h }
    }
  } catch {}
  return $val
}

function Write-MistralRateLimitDiagnostics {
  <#
    Emit SECRET-SAFE diagnostics for a Mistral 429. Every free-text field comes
    from Get-SafeProviderError (already API-key-redacted); the API key and the
    prompt text are NEVER printed. Logs: model, status code, redacted error body,
    estimated prompt tokens, max tokens, Retry-After header, and attempt count.
  #>
  param(
    [string]$Model,
    $SafeError,
    [int]$EstimatedPromptTokens = 0,
    [int]$MaxTokens = 0,
    [string]$RetryAfter = "",
    [int]$Attempt = 0
  )
  $status = if ($SafeError) { [string]$SafeError.Status } else { "" }
  $bodyRedacted = if ($SafeError) { [string]$SafeError.RawBodyRedacted } else { "" }
  if ($bodyRedacted.Length -gt 300) { $bodyRedacted = $bodyRedacted.Substring(0, 300) + "...(truncated)" }
  Write-Host "  Mistral 429 diagnostics (secret-safe):"
  Write-Host ("    model               : {0}" -f $Model)
  Write-Host ("    status_code         : {0}" -f $(if ($status) { $status } else { "(unknown)" }))
  Write-Host ("    est_prompt_tokens   : {0}" -f $EstimatedPromptTokens)
  Write-Host ("    max_tokens          : {0}" -f $MaxTokens)
  Write-Host ("    retry_after_header  : {0}" -f $(if ($RetryAfter) { $RetryAfter } else { "(none)" }))
  Write-Host ("    attempt             : {0}" -f $Attempt)
  Write-Host ("    error_body_redacted : {0}" -f $(if ($bodyRedacted) { $bodyRedacted } else { "(empty)" }))
}

function Get-SafeProviderError {
  <#
    Extract a SECRET-SAFE structured error from a caught provider ErrorRecord.
    Reads HTTP status + provider response body (PS5.1 response stream OR PS7
    ErrorDetails.Message), parses the common error JSON shapes (OpenAI / xAI /
    Anthropic / Gemini nested {error:{type,code,message}}; Mistral flat
    {message,type,code,raw_status_code}) and REDACTS any API-key-like substring
    from every free-text field before returning. Never throws.
  #>
  param(
    [Parameter(Mandatory = $true)]$ErrorRecord,
    [string]$Provider = "",
    [string]$Model = ""
  )

  $status  = ""
  $rawBody = ""
  $exc     = $null
  try { $exc = $ErrorRecord.Exception } catch {}

  # --- HTTP status code (PS5.1 WebException.Response / PS7 HttpResponseException) ---
  try {
    if ($exc -and $exc.Response) {
      try { $status = [string]([int]$exc.Response.StatusCode) }
      catch { try { $status = [string]$exc.Response.StatusCode } catch {} }
    }
  } catch {}

  # --- Response body: PS7 exposes it on ErrorDetails.Message; PS5.1 needs the stream ---
  try {
    if ($ErrorRecord.ErrorDetails -and $ErrorRecord.ErrorDetails.Message) {
      $rawBody = [string]$ErrorRecord.ErrorDetails.Message
    }
  } catch {}
  if ([string]::IsNullOrWhiteSpace($rawBody)) {
    try {
      if ($exc -and $exc.Response) {
        $stream = $exc.Response.GetResponseStream()
        if ($stream) {
          $reader  = New-Object System.IO.StreamReader($stream)
          $rawBody = $reader.ReadToEnd()
          $reader.Close()
        }
      }
    } catch {}
  }

  # --- Parse structured fields from the common provider error shapes ---
  $type = ""; $code = ""; $message = ""
  if (-not [string]::IsNullOrWhiteSpace($rawBody)) {
    try {
      $j = $rawBody | ConvertFrom-Json
      if ($j) {
        $errObj = $null
        if ($j.PSObject.Properties.Name -contains 'error') { $errObj = $j.error }
        if ($errObj) {
          if ($errObj.type)              { $type    = [string]$errObj.type }
          if ($null -ne $errObj.code)    { $code    = [string]$errObj.code }
          if ($errObj.message)           { $message = [string]$errObj.message }
          if ($errObj.status -and -not $type) { $type = [string]$errObj.status }
        }
        if (-not $type    -and $j.type)             { $type    = [string]$j.type }
        if (-not $code    -and $null -ne $j.code)   { $code    = [string]$j.code }
        if (-not $message -and $j.message)          { $message = [string]$j.message }
        if (-not $status  -and $j.raw_status_code)  { $status  = [string]$j.raw_status_code }
      }
    } catch {
      # body was not JSON; the redacted raw body below carries the detail
    }
  }
  if ([string]::IsNullOrWhiteSpace($message)) {
    if (-not [string]::IsNullOrWhiteSpace($rawBody)) {
      $message = $rawBody
    } else {
      try { $message = [string]$exc.Message } catch {}
    }
  }

  # --- Redact API-key-like substrings from every free-text field ---
  $redaction = $null
  try { $redaction = Get-SecretRedactionRegex } catch {}
  $redact = {
    param([string]$s)
    if ([string]::IsNullOrEmpty($s)) { return $s }
    if ($redaction) { return [regex]::Replace($s, $redaction, '[REDACTED_API_KEY]') }
    return $s
  }
  $message = [string](& $redact $message)
  $type    = [string](& $redact $type)
  $rawRed  = [string](& $redact $rawBody)
  if ($message.Length -gt 600) { $message = $message.Substring(0, 600) + "...(truncated)" }

  return [pscustomobject]@{
    Provider        = $Provider
    Model           = $Model
    Status          = $status
    Type            = $type
    Code            = $code
    Message         = $message
    RawBodyRedacted = $rawRed
  }
}

function Get-ProviderUnavailablePlaceholder {
  <#
    The placeholder text substituted for an unavailable provider's response in
    the final synthesis prompt. The $Reason MUST already be secret-safe (it comes
    from Get-SafeProviderError); this never embeds a key.
  #>
  param([string]$Provider, [string]$Reason)
  $r = if ([string]::IsNullOrWhiteSpace($Reason)) { "unknown reason" } else { $Reason }
  return ("PROVIDER_UNAVAILABLE: {0} unavailable due {1}. No advisory generated by this provider." -f $Provider, $r)
}

function Get-ProviderAvailabilitySection {
  <#
    Build the "Provider Availability" block for the synthesis prompt from the
    array of provider-result objects (each: Name / Available / Reason).
  #>
  param([Parameter(Mandatory = $true)]$Providers)
  $lines = New-Object System.Collections.Generic.List[string]
  foreach ($p in $Providers) {
    if ($p.Available) {
      $lines.Add(("{0}: available" -f $p.Name))
    } else {
      $reason = if ([string]::IsNullOrWhiteSpace($p.Reason)) { "unknown reason" } else { $p.Reason }
      $lines.Add(("{0}: unavailable - {1}" -f $p.Name, $reason))
    }
  }
  return ($lines -join "`n")
}

function Format-ProviderReason {
  <#
    Build a compact, human-readable, SECRET-SAFE provider-failure reason from a
    Get-SafeProviderError object: "type / status / code (message)", skipping any
    field that is empty. The $Safe fields are already redacted by
    Get-SafeProviderError, so this never embeds an API key. Used so the recorded
    reason surfaces rate_limited / 429 / 1300 for an exhausted Mistral 429.
  #>
  param($Safe)
  if (-not $Safe) { return "unknown error" }
  $parts = New-Object System.Collections.Generic.List[string]
  if (-not [string]::IsNullOrWhiteSpace([string]$Safe.Type))   { $parts.Add([string]$Safe.Type) }
  if (-not [string]::IsNullOrWhiteSpace([string]$Safe.Status)) { $parts.Add([string]$Safe.Status) }
  if (-not [string]::IsNullOrWhiteSpace([string]$Safe.Code))   { $parts.Add([string]$Safe.Code) }
  $head = if ($parts.Count -gt 0) { $parts -join ' / ' } else { '' }
  $msg  = if (-not [string]::IsNullOrWhiteSpace([string]$Safe.Message)) { [string]$Safe.Message } else { '' }
  if ($head -and $msg) { return ("{0} ({1})" -f $head, $msg) }
  if ($head) { return $head }
  if ($msg)  { return $msg }
  return "unknown error"
}

function Get-ConciseProviderReason {
  <#
    The short "due ..." descriptor embedded in a provider's UNAVAILABLE
    placeholder. Prefers the structured failure TYPE (e.g. "rate_limited") so the
    Mistral placeholder reads "...unavailable due rate_limited...", and falls back
    to the full reason / a generic phrase. Always secret-safe (the fields it reads
    come from Get-SafeProviderError redaction).
  #>
  param($Result)
  if ($Result) {
    if (-not [string]::IsNullOrWhiteSpace([string]$Result.Type))   { return [string]$Result.Type }
    if (-not [string]::IsNullOrWhiteSpace([string]$Result.Reason)) { return [string]$Result.Reason }
  }
  return "unknown reason"
}

function New-RateLimitedErrorRecord {
  <#
    Build a self-describing, SECRET-SAFE ErrorRecord representing rate-limit retry
    EXHAUSTION, so Invoke-SafeProvider records the provider unavailable with
    status=429 / type=rate_limited / code=1300 / message="Rate limit exceeded"
    DETERMINISTICALLY.

    Why this exists: the retry loop must NOT bare re-throw the raw WebException at
    exhaustion. By that point the retry diagnostics (Get-SafeProviderError) have
    already consumed that exception's HTTP response stream, so re-reading it inside
    Invoke-SafeProvider's catch would yield an empty/garbled reason (and, with the
    stream disposed, risk the error escaping before the provider is marked
    unavailable). A fresh, fully self-describing ErrorRecord removes that fragility.

    -SafeError (optional) preserves the real status/type/code from the last
    observed rate-limit error when present; missing fields default to the
    canonical rate-limit values. The message is always the canonical, secret-safe
    "Rate limit exceeded" (the $SafeError fields are themselves already redacted,
    so this never embeds an API key).
  #>
  param(
    $SafeError,
    [string]$Provider = "Mistral"
  )
  $status  = "429"
  $type    = "rate_limited"
  $code    = "1300"
  $message = "Rate limit exceeded"
  if ($SafeError) {
    if (-not [string]::IsNullOrWhiteSpace([string]$SafeError.Status)) { $status = [string]$SafeError.Status }
    if (-not [string]::IsNullOrWhiteSpace([string]$SafeError.Type))   { $type   = [string]$SafeError.Type }
    if (-not [string]::IsNullOrWhiteSpace([string]$SafeError.Code))   { $code   = [string]$SafeError.Code }
  }
  $rawStatus = 429
  [void][int]::TryParse([string]$status, [ref]$rawStatus)
  $bodyObj = [ordered]@{
    message         = $message
    type            = $type
    code            = $code
    raw_status_code = $rawStatus
  }
  $json = $bodyObj | ConvertTo-Json -Compress
  $exc  = New-Object System.Exception (("{0} rate limit exceeded after retries" -f $Provider))
  $er   = New-Object System.Management.Automation.ErrorRecord(
    $exc, "ProviderRateLimited", [System.Management.Automation.ErrorCategory]::LimitsExceeded, $null)
  $er.ErrorDetails = New-Object System.Management.Automation.ErrorDetails($json)
  return $er
}
