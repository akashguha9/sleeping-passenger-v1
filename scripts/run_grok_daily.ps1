Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ============================================================
# SLEEPING PASSENGER
# STANDALONE GROK 4.5 API RUNNER
#
# PowerShell -> xAI Responses API -> grok-4.5
#
# NO GROK CLI
# NO OTHER MODEL
# NO BROKER ACTION
# NO REPOSITORY MODIFICATION BY GROK
# ============================================================

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

Set-Location "C:\Users\akash\sleeping-passenger-v1"

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " SLEEPING PASSENGER - GROK DAILY API RUN" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# ============================================================
# 1. CLEAN PREVIOUS IN-MEMORY VARIABLES
# ============================================================

Remove-Variable response -ErrorAction SilentlyContinue
Remove-Variable result -ErrorAction SilentlyContinue
Remove-Variable bodyObj -ErrorAction SilentlyContinue
Remove-Variable bodyJson -ErrorAction SilentlyContinue
Remove-Variable requestParams -ErrorAction SilentlyContinue
Remove-Variable textParts -ErrorAction SilentlyContinue
Remove-Variable headers -ErrorAction SilentlyContinue

# ============================================================
# 2. RUN SETTINGS
# ============================================================

$provider = "xAI"
$model = "grok-4.5"
$runDate = Get-Date -Format "yyyy-MM-dd"

# Stable cache-routing key.
# This is NOT an API key or credential.
$promptCacheKey = "sleeping-passenger-grok-daily-v1"

Write-Host "Run date: $runDate"
Write-Host "Provider: $provider"
Write-Host "Model: $model"
Write-Host ""

# ============================================================
# 3. FILE PATHS
# ============================================================

$promptFile = ".\prompts\grok_daily_prompt.txt"

$openPositionsFile = ".\moltbook\open_positions.json"
$signalLedgerFile = ".\moltbook\signal_ledger.json"
$thresholdsFile = ".\config\thresholds.yaml"

$outFile = ".\moltbook\grok_report_$runDate.txt"
$rawFile = ".\moltbook\grok_raw_response_$runDate.json"
$errorFile = ".\moltbook\grok_http_error_$runDate.txt"

# ============================================================
# 4. VERIFY REQUIRED FILES
# ============================================================

$requiredFiles = @(
    $promptFile,
    $openPositionsFile,
    $signalLedgerFile,
    $thresholdsFile
)

foreach ($requiredFile in $requiredFiles) {

    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required file missing: $requiredFile"
    }

    Write-Host "FOUND: $requiredFile" -ForegroundColor DarkGreen
}

Write-Host ""

# ============================================================
# 5. VERIFY XAI KEY EXISTS
# ============================================================

if ([string]::IsNullOrWhiteSpace($env:XAI_API_KEY)) {
    throw "XAI_API_KEY is missing from this PowerShell session."
}

Write-Host "xAI key is set." -ForegroundColor Green

# NEVER print:
# $env:XAI_API_KEY

# ============================================================
# 6. LOAD GROK PROMPT
# ============================================================

$grokPrompt = Get-Content `
    -LiteralPath $promptFile `
    -Raw `
    -Encoding UTF8

if ([string]::IsNullOrWhiteSpace($grokPrompt)) {
    throw "Grok prompt file is empty."
}

$grokPrompt = $grokPrompt.Replace(
    "{{RUN_DATE}}",
    $runDate
)

Write-Host "Grok prompt loaded." -ForegroundColor DarkGreen

# ============================================================
# 7. LOAD LOCAL MVP CONTEXT
# ============================================================

$openPositions = Get-Content `
    -LiteralPath $openPositionsFile `
    -Raw `
    -Encoding UTF8

$signalLedger = Get-Content `
    -LiteralPath $signalLedgerFile `
    -Raw `
    -Encoding UTF8

$thresholds = Get-Content `
    -LiteralPath $thresholdsFile `
    -Raw `
    -Encoding UTF8

Write-Host "Local MVP context loaded." -ForegroundColor DarkGreen

# ============================================================
# 8. BUILD COMPLETE PROMPT
# ============================================================

$fullPrompt = @"
$grokPrompt


============================================================
PASTED LOCAL MVP CONTEXT
============================================================


============================================================
FILE 1
moltbook/open_positions.json
============================================================

$openPositions


============================================================
FILE 2
moltbook/signal_ledger.json
============================================================

$signalLedger


============================================================
FILE 3
config/thresholds.yaml
============================================================

$thresholds


============================================================
END PASTED LOCAL MVP CONTEXT
============================================================
"@

# ============================================================
# 9. REMOVE INVALID UTF-16 SURROGATE CHARACTERS
# ============================================================

$fullPrompt = [regex]::Replace(
    $fullPrompt,
    '[\uD800-\uDFFF]',
    ''
)

# ============================================================
# 10. CREDENTIAL SAFETY SCANNER
#
# IMPORTANT FIX:
#
# This searches for actual credential-like VALUES.
#
# It does NOT flag ordinary text merely because it contains:
#
# risk-sensitivity
# XAI_API_KEY
# OPENAI_API_KEY
# API key
#
# The negative lookbehind also prevents:
#
# risk-sensitivity
#
# from being interpreted as:
#
# sk-sensitivity
# ============================================================

$keyPattern = '(?i)(?<![A-Za-z0-9])(?:xai-[A-Za-z0-9_-]{20,}|sk-(?:proj-)?[A-Za-z0-9_-]{20,}|AIza[A-Za-z0-9_-]{20,}|Bearer\s+[A-Za-z0-9._~+/=-]{20,})'

# Generic explicit secret assignment pattern.
$assignmentPattern = '(?i)(?:api[_ -]?key|access[_ -]?token|secret|password)\s*[:=]\s*["'']?[A-Za-z0-9._~+/=-]{24,}'

# ============================================================
# 11. SCAN EACH SOURCE WITHOUT PRINTING MATCHED CONTENT
# ============================================================

$scanSources = [ordered]@{
    "Grok prompt"     = $grokPrompt
    "Open positions"  = $openPositions
    "Signal ledger"   = $signalLedger
    "Thresholds"      = $thresholds
}

$credentialProblemFound = $false

foreach ($scanSource in $scanSources.GetEnumerator()) {

    $sourceTriggered = $false

    if ($scanSource.Value -match $keyPattern) {
        $sourceTriggered = $true
    }

    if ($scanSource.Value -match $assignmentPattern) {
        $sourceTriggered = $true
    }

    if ($sourceTriggered) {

        Write-Host `
            "Credential scanner triggered by: $($scanSource.Key)" `
            -ForegroundColor Red

        $credentialProblemFound = $true
    }
}

if ($credentialProblemFound) {

    throw @"
ABORTED:
Possible credential material was detected in one or more prompt/context sources.

The suspected credential itself was NOT printed.

Remove any real credential value from the source named above and retry.
"@
}

Write-Host "Credential safety scan passed." -ForegroundColor Green
Write-Host ""

# ============================================================
# 12. GROK SYSTEM INSTRUCTION
# ============================================================

$systemInstruction = @"
You are Grok operating as an independent long-context research analyst
for zzz_passenger's Sleeping Passenger MVP.

This is a standalone xAI API request.

OPERATIONAL BOUNDARIES:

- Advisory analysis only.
- Do not execute trades.
- Do not place broker orders.
- Do not cancel broker orders.
- Do not connect to brokers.
- Do not change leverage.
- Do not modify the repository.
- Do not modify files.
- Do not update databases.
- Do not claim you performed reconciliation.
- Do not claim you inspected the local filesystem.
- Treat supplied local-file contents as pasted text only.
- Do not claim access to Google Sheets.
- Do not claim access to live prices unless supplied.
- Do not claim access to live filings unless supplied.
- Do not claim access to current news unless supplied.
- Do not claim access to X/social data unless supplied.
- No web-search tool is enabled in this API call.
- No X-search tool is enabled in this API call.
- No code-execution tool is enabled in this API call.

DATA DISCIPLINE:

Clearly distinguish:
1. facts supported by supplied context
2. analytical inference
3. live validation required
4. data insufficient

Never fabricate:
- prices
- market moves
- financial ratios
- filings
- news
- social sentiment
- broker holdings
- trade fills
- PnL
- reconciliation status
- catalysts presented as current facts

GROK SPECIALTY:

Apply particular attention to:
- narrative pressure
- crowd psychology
- attention
- reflexivity
- hype
- narrative saturation
- narrative decay
- meme pressure
- geopolitical narrative
- headline chasing
- crowded positioning
- story-versus-economics contradictions
- hidden toll collectors
- overlooked structural winners
- what the crowd may be missing
- queen-priced pawns
- chaos traps

SECURITY:

Never reveal, infer, repeat, transform, summarize, or request
API keys, passwords, credentials, secrets, tokens, Bearer headers,
or environment-variable contents.

Follow the user's analyst prompt carefully.

Return the completed analyst report only.
"@

# ============================================================
# 13. CREATE xAI RESPONSES API REQUEST BODY
# ============================================================

$bodyObj = @{
    model = $model

    input = @(
        @{
            role = "system"
            content = $systemInstruction
        },
        @{
            role = "user"
            content = $fullPrompt
        }
    )

    reasoning = @{
        effort = "high"
    }

    max_output_tokens = 16000

    store = $false

    prompt_cache_key = $promptCacheKey
}

# ============================================================
# 14. SERIALIZE JSON
# ============================================================

$bodyJson = $bodyObj |
    ConvertTo-Json `
        -Depth 50 `
        -Compress

Write-Host "Request JSON created." -ForegroundColor DarkGreen

# ============================================================
# 15. CREATE AUTHORIZATION HEADER
# ============================================================

$headers = @{
    Authorization = "Bearer $($env:XAI_API_KEY)"
}

# Do not print $headers.

# ============================================================
# 16. CREATE HTTP REQUEST PARAMETERS
# ============================================================

$requestParams = @{
    Uri = "https://api.x.ai/v1/responses"

    Method = "Post"

    Headers = $headers

    ContentType = "application/json; charset=utf-8"

    Body = [System.Text.Encoding]::UTF8.GetBytes($bodyJson)

    TimeoutSec = 3600
}

# ============================================================
# 17. SEND REQUEST TO xAI
# ============================================================

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " SENDING REQUEST TO xAI" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "Model: $model"
Write-Host "Reasoning effort: HIGH"
Write-Host "Maximum output tokens: 16000"
Write-Host "Server-side response storage: DISABLED"
Write-Host ""
Write-Host "Large reasoning runs can take several minutes."
Write-Host ""

try {

    $response = Invoke-RestMethod @requestParams

}
catch {

    $apiErrorDetails = ""

    if (
        $_.ErrorDetails -and
        $_.ErrorDetails.Message
    ) {
        $apiErrorDetails = [string]$_.ErrorDetails.Message
    }

    # Redact any credential-like material from the error before saving it.
    $safeException = [string]$_.Exception.Message
    $safeException = [regex]::Replace(
        $safeException,
        $keyPattern,
        "[REDACTED]"
    )

    $safeApiDetails = [regex]::Replace(
        $apiErrorDetails,
        $keyPattern,
        "[REDACTED]"
    )

    $errorText = @"
GROK API REQUEST FAILED

Date:
$runDate

Provider:
xAI

Model:
$model

Endpoint:
https://api.x.ai/v1/responses

Exception:
$safeException

API error details:
$safeApiDetails
"@

    $errorText |
        Set-Content `
            -LiteralPath $errorFile `
            -Encoding UTF8

    Write-Host ""
    Write-Host "GROK API REQUEST FAILED" -ForegroundColor Red
    Write-Host ""
    Write-Host "Safe error report:"
    Write-Host $errorFile
    Write-Host ""

    notepad $errorFile

    throw "Grok API request failed. See $errorFile"
}

# ============================================================
# 18. SAVE COMPLETE RAW RESPONSE
# ============================================================

$response |
    ConvertTo-Json `
        -Depth 100 |
    Set-Content `
        -LiteralPath $rawFile `
        -Encoding UTF8

Write-Host "Raw xAI response saved:" -ForegroundColor DarkGreen
Write-Host $rawFile
Write-Host ""

# ============================================================
# 19. EXTRACT FINAL TEXT
#
# Responses API structure:
#
# output[]
#   -> type = message
#   -> content[]
#      -> type = output_text
#      -> text
# ============================================================

$textParts = New-Object System.Collections.Generic.List[string]

# Try direct output_text if exposed.
if ($response.PSObject.Properties.Name -contains "output_text") {

    if (
        -not [string]::IsNullOrWhiteSpace(
            [string]$response.output_text
        )
    ) {

        $textParts.Add(
            [string]$response.output_text
        )
    }
}

# Standard Responses API output.
if ($response.PSObject.Properties.Name -contains "output") {

    if ($response.output) {

        foreach ($outputItem in @($response.output)) {

            if (
                $outputItem.type -eq "message" -and
                $outputItem.content
            ) {

                foreach ($contentPart in @($outputItem.content)) {

                    if (
                        $contentPart.type -eq "output_text" -and
                        -not [string]::IsNullOrWhiteSpace(
                            [string]$contentPart.text
                        )
                    ) {

                        $textParts.Add(
                            [string]$contentPart.text
                        )
                    }
                }
            }
        }
    }
}

$result = ($textParts -join "`n").Trim()

# ============================================================
# 20. CHECK FOR EMPTY OUTPUT
# ============================================================

if ([string]::IsNullOrWhiteSpace($result)) {

    Write-Host ""
    Write-Host "Grok returned EMPTY report text." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Opening raw response:"
    Write-Host $rawFile
    Write-Host ""

    notepad $rawFile

    throw @"
Grok returned no extractable report text.

Inspect the raw response for:

- status
- error
- incomplete_details
- output
- message content
- refusal information

Raw response:
$rawFile
"@
}

# ============================================================
# 21. CHECK RESPONSE STATUS
# ============================================================

if ($response.PSObject.Properties.Name -contains "status") {

    Write-Host "xAI response status: $($response.status)"

    if ([string]$response.status -eq "incomplete") {

        Write-Warning "xAI marked this response INCOMPLETE."
        Write-Warning "Inspect the raw response for incomplete_details."
    }
}

# ============================================================
# 22. SAFETY-SCAN GROK OUTPUT
# ============================================================

if (
    ($result -match $keyPattern) -or
    ($result -match $assignmentPattern)
) {

    throw @"
ABORTED:
Grok output appears to contain credential-like material.

The final report was NOT written.

The raw API response remains available for manual inspection:
$rawFile
"@
}

# ============================================================
# 23. WRITE FINAL GROK REPORT
# ============================================================

$result |
    Set-Content `
        -LiteralPath $outFile `
        -Encoding UTF8

# ============================================================
# 24. FINAL STATUS
# ============================================================

Write-Host ""
Write-Host "==================================================" -ForegroundColor Green
Write-Host " GROK REPORT COMPLETE" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green
Write-Host ""

Write-Host "Run date:"
Write-Host $runDate

Write-Host ""
Write-Host "Provider:"
Write-Host $provider

Write-Host ""
Write-Host "Model:"
Write-Host $model

Write-Host ""
Write-Host "Final report:"
Write-Host $outFile

Write-Host ""
Write-Host "Raw response:"
Write-Host $rawFile

Write-Host ""
Write-Host "Opening Grok report..."
Write-Host ""

notepad $outFile