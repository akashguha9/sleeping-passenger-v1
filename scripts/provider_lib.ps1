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
  # Three retries: 15s, 45s, 90s. Defined here so it is unit-testable without
  # making a network call or printing secrets.
  return @(15, 45, 90)
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
