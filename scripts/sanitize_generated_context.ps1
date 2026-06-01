<#
  sanitize_generated_context.ps1  -  redact API-key-like strings from
  GENERATED / non-source folders only.

  Advisory-only, secret-safe:
    * runs from repo root (resolved via $PSScriptRoot/..)
    * scans ONLY generated/non-source folders (data, moltbook, reports,
      outputs, tmp, runtime)
    * NEVER touches source code, .env / .env.*, or dependency/build dirs
    * prints ONLY <relative-path>:<line> - never the matched secret value
    * creates a .bak before editing any file
    * -DryRun (default) reports what WOULD change; -Apply performs the redaction

  Usage:
    powershell -File scripts\sanitize_generated_context.ps1            # dry run
    powershell -File scripts\sanitize_generated_context.ps1 -DryRun
    powershell -File scripts\sanitize_generated_context.ps1 -Apply
#>
[CmdletBinding()]
param(
  [switch]$DryRun,
  [switch]$Apply
)

$ErrorActionPreference = 'Stop'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $RepoRoot
. (Join-Path $PSScriptRoot 'secret_scan_lib.ps1')

# Default to dry-run when neither switch is passed. If both are passed, -Apply wins.
if (-not $Apply) { $DryRun = $true }
if ($Apply) { $DryRun = $false }
$mode = 'DRY-RUN'
if ($Apply) { $mode = 'APPLY' }

# Generated / non-source folders only.
$scanDirs = @('data', 'moltbook', 'reports', 'outputs', 'tmp', 'runtime')

# Never descend into these (dependencies, build caches, VCS, source trees).
$excludeDirRx  = '(?i)(^|[\\/])(\.git|node_modules|\.venv|venv|__pycache__|scripts|tests)([\\/]|$)|(?i)frontend[\\/](node_modules|src)([\\/]|$)'
# Never touch env files even if they live under a scanned folder.
$excludeFileRx = '(?i)(^|[\\/])\.env($|\.)'

# Only rewrite text-like generated artifacts (avoid mangling binaries / DBs).
$textExt = @('.json', '.ndjson', '.txt', '.md', '.csv', '.tsv', '.log', '.yaml', '.yml', '.html', '.xml')

$redactRx       = Get-SecretRedactionRegex
$replacement    = '[REDACTED_API_KEY]'
$filesScanned   = 0
$filesWithHits  = 0
$linesRedacted  = 0
$filesEdited    = 0

Write-Host "sanitize_generated_context.ps1 - mode: $mode"
Write-Host "repo root: $RepoRoot"
Write-Host ("scanning generated folders: {0}" -f ($scanDirs -join ', '))
Write-Host ''

foreach ($dir in $scanDirs) {
  $full = Join-Path $RepoRoot $dir
  if (-not (Test-Path $full)) { continue }

  Get-ChildItem -Path $full -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
    $path = $_.FullName
    if ($path -match $excludeDirRx)  { return }
    if ($path -match $excludeFileRx) { return }
    if ($textExt -notcontains $_.Extension.ToLower()) { return }

    $filesScanned++
    $rel = $path.Substring($RepoRoot.Length).TrimStart('\', '/')

    $lines = Get-Content -LiteralPath $path
    if ($null -eq $lines) { return }

    $newLines = New-Object System.Collections.Generic.List[string]
    $fileHit  = $false
    $lineNo   = 0
    foreach ($line in $lines) {
      $lineNo++
      if ([regex]::IsMatch($line, $redactRx)) {
        $fileHit = $true
        $linesRedacted++
        $verb = 'WOULD REDACT'
        if ($Apply) { $verb = 'REDACTED' }
        # path + line only - never the matched value
        Write-Host ("  {0}:{1}  [{2}]" -f $rel, $lineNo, $verb)
        $newLines.Add(([regex]::Replace($line, $redactRx, $replacement)))
      }
      else {
        $newLines.Add($line)
      }
    }

    if ($fileHit) {
      $filesWithHits++
      if ($Apply) {
        Copy-Item -LiteralPath $path -Destination ($path + '.bak') -Force
        Set-Content -LiteralPath $path -Value $newLines -Encoding UTF8
        $filesEdited++
      }
    }
  }
}

Write-Host ''
Write-Host '------------------------------------------------------------'
Write-Host ("files scanned        : {0}" -f $filesScanned)
Write-Host ("files with key-like  : {0}" -f $filesWithHits)
Write-Host ("lines flagged        : {0}" -f $linesRedacted)
if ($Apply) {
  Write-Host ("files edited (.bak)  : {0}" -f $filesEdited)
}
else {
  Write-Host 'DRY-RUN: no files were modified. Re-run with -Apply to redact.'
}
Write-Host '------------------------------------------------------------'
