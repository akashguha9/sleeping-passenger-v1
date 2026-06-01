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
  return [ordered]@{
    'ANTHROPIC_STYLE_KEY' = '(?<![A-Za-z0-9/_.\-])sk-ant-[A-Za-z0-9_\-]{20,}'
    'OPENAI_PROJECT_KEY'  = '(?<![A-Za-z0-9/_.\-])sk-(?:proj|svcacct|admin)-[A-Za-z0-9_\-]{20,}'
    'OPENAI_STYLE_KEY'    = '(?<![A-Za-z0-9/_.\-])sk-[A-Za-z0-9]{20,}'
    'XAI_STYLE_KEY'       = '(?<![A-Za-z0-9/_.\-])xai-[A-Za-z0-9]{20,}'
    'GOOGLE_STYLE_KEY'    = '(?<![A-Za-z0-9/_.\-])AIza[A-Za-z0-9_\-]{30,}'
    'BEARER_TOKEN'        = 'Bearer[ \t]+[A-Za-z0-9_\-]{20,}'
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
  # Return with a unary comma so PowerShell does NOT enumerate the list on the
  # way out: a single finding must stay a 1-element collection (otherwise
  # $result.Count is $null and a lone leaked key would slip past the guard).
  if ([string]::IsNullOrEmpty($Text)) { return ,$findings }
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
  return ,$findings
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
