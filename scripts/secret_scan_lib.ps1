# ============================================================
# secret_scan_lib.ps1  -  shared API-key leak detection helpers
# ============================================================
# Advisory-only. This library NEVER prints, returns, logs, or serializes a
# matched secret value. It reports only (source, line, pattern-class).
#
# Detection is intentionally STRICT to avoid false positives on advisory
# prompt/context text (e.g. news URL slugs such as ".../elon-musk-is-going-..."
# which used to trip a hyphen-permissive "sk-[A-Za-z0-9_-]{20,}" pattern):
#   * classic OpenAI / xAI keys have a high-entropy base62 body with NO hyphens,
#     so the body class forbids hyphens;
#   * structured keys (sk-ant-, sk-proj-, sk-svcacct-, sk-admin-) keep their
#     distinctive prefix, which advisory text never contains;
#   * every key class uses a negative lookbehind so the prefix cannot be matched
#     when it is embedded inside a longer word / URL / path;
#   * Bearer tokens require SAME-LINE whitespace ([ \t]) so the match can never
#     bridge two unrelated lines via a newline.
# These rules strengthen (not weaken) real-secret detection.
#
# Matching uses [regex]::IsMatch (the explicit, case-sensitive .NET engine)
# rather than the PowerShell -match operator: -match is case-insensitive and was
# observed to produce a spurious match the explicit engine does not. API-key
# prefixes have fixed casing (sk-/xai- lowercase, AIza, Bearer), so
# case-sensitive matching is correct and avoids that pitfall.
# ============================================================

function Get-SecretClassPatterns {
  # ONE source of truth. Returned fresh each call (no module-scope state to
  # drift). Ordered so structured/longer prefixes are reported before classic.
  # Each class is anchored by a negative lookBEHIND (prefix cannot be embedded in
  # a longer word/URL/path, e.g. ".../mu[sk-]is-going...") and a negative
  # lookAHEAD (the body cannot bleed into an adjacent word/hyphen), so the match
  # is a standalone token, never a prose substring.
  return [ordered]@{
    'ANTHROPIC_STYLE_KEY' = '(?<![A-Za-z0-9/_.\-])sk-ant-[A-Za-z0-9_\-]{20,}(?![A-Za-z0-9_\-])'
    'OPENAI_PROJECT_KEY'  = '(?<![A-Za-z0-9/_.\-])sk-(?:proj|svcacct|admin)-[A-Za-z0-9_\-]{20,}(?![A-Za-z0-9_\-])'
    # Legacy OpenAI keys are high-entropy base62 with NO hyphens; require 32+ so a
    # short hyphen-broken slug fragment ("sk-is-going-...") can never match.
    'OPENAI_STYLE_KEY'    = '(?<![A-Za-z0-9/_.\-])sk-[A-Za-z0-9]{32,}(?![A-Za-z0-9_\-])'
    'XAI_STYLE_KEY'       = '(?<![A-Za-z0-9/_.\-])xai-[A-Za-z0-9]{20,}(?![A-Za-z0-9_\-])'
    'GOOGLE_STYLE_KEY'    = '(?<![A-Za-z0-9/_.\-])AIza[A-Za-z0-9_\-]{20,}(?![A-Za-z0-9_\-])'
    'BEARER_TOKEN'        = 'Bearer[ \t]+[A-Za-z0-9_\-]{20,}(?![A-Za-z0-9_\-])'
  }
}

function Get-SecretRedactionRegex {
  # Single combined regex (alternation) for redaction. Structured prefixes come
  # first so the full token is consumed when more than one class could match.
  return [string]::Join('|', @((Get-SecretClassPatterns).Values))
}

function Find-SecretMatchLines {
  <#
    Scan $Text line-by-line and return one finding per offending line:
      [pscustomobject]@{ Source; Line; Class }
    The matched secret VALUE is never captured, returned, or printed.
    Scanning per-line guarantees a match can never span unrelated lines.
  #>
  param(
    [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text,
    [string]$Source = '<text>'
  )
  $patterns = Get-SecretClassPatterns
  $findings = New-Object System.Collections.Generic.List[object]
  # An EMPTY result MUST enumerate to ZERO items at the call site. The previous
  # `return ,$findings` wrapped the empty list as a single element, so
  # @(Find-SecretMatchLines ...) reported Count=1 and FALSE-POSITIVED on clean
  # text (e.g. a news URL slug). When there are no hits we therefore emit
  # nothing; when there are hits we return the array wrapped with a unary comma
  # so a lone finding still keeps its .Count for bare-assignment callers.
  if ([string]::IsNullOrEmpty($Text)) { return }
  $lineNo = 0
  foreach ($line in ($Text -split "`n")) {
    $lineNo++
    foreach ($cls in $patterns.Keys) {
      if ([regex]::IsMatch($line, $patterns[$cls])) {
        $findings.Add([pscustomobject]@{ Source = $Source; Line = $lineNo; Class = $cls })
        break  # one flag per line is enough; do not keep scanning this line
      }
    }
  }
  if ($findings.Count -eq 0) { return }
  return ,$findings.ToArray()
}

function Get-FirstSecretMatch {
  <#
    Return the FIRST API-key-like finding in $Text as
      [pscustomobject]@{ Source; Line; Class }
    or $null when the text is clean. Single source of truth shared with
    run_five_model_synthesis.ps1 (which dot-sources this library) so the main
    script and this library can never drift apart. The matched secret VALUE is
    never captured, returned, or printed.
  #>
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
  <#
    Throw a structured, secret-safe abort if $Text contains API-key-like text.
    The thrown message names the source, line, and pattern class but NEVER the
    matched value.
  #>
  param(
    [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text,
    [Parameter(Mandatory = $true)][string]$Source
  )
  $hits = @(Find-SecretMatchLines -Text $Text -Source $Source)
  if ($hits.Count -gt 0) {
    $h = $hits[0]
    $msg = @"
ABORTED: prompt/context contains API-key-like text.
Matched source: $($h.Source) (line $($h.Line))
Pattern class: $($h.Class)
Secret value was not printed.
Fix: run scripts/sanitize_generated_context.ps1 or delete stale generated payloads and rerun.
"@
    throw $msg
  }
}
