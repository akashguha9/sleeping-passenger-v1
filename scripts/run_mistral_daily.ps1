Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ============================================================
# SLEEPING PASSENGER
# STANDALONE MISTRAL API RUNNER
#
# PowerShell -> Mistral Chat Completions API
#            -> Mistral Medium 3.5
#
# NO CLI
# NO OTHER AI MODEL
# NO BROKER ACTION
# NO REPOSITORY MODIFICATION BY MISTRAL
# ============================================================

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

Set-Location "C:\Users\akash\sleeping-passenger-v1"

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " SLEEPING PASSENGER - MISTRAL DAILY API RUN" -ForegroundColor Cyan
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

$provider = "Mistral AI"
$model = "mistral-medium-3-5"
$reasoningEffort = "high"
$maxTokens = 16000

$runDate = Get-Date -Format "yyyy-MM-dd"

Write-Host "Run date: $runDate"
Write-Host "Provider: $provider"
Write-Host "Model: $model"
Write-Host "Reasoning effort: $reasoningEffort"
Write-Host ""

# ============================================================
# 3. FILE PATHS
# ============================================================

$promptFile = ".\prompts\mistral_daily_prompt.txt"

$openPositionsFile = ".\moltbook\open_positions.json"
$signalLedgerFile = ".\moltbook\signal_ledger.json"
$thresholdsFile = ".\config\thresholds.yaml"

$outFile = ".\moltbook\mistral_report_$runDate.txt"
$rawFile = ".\moltbook\mistral_raw_response_$runDate.json"
$errorFile = ".\moltbook\mistral_http_error_$runDate.txt"

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
# 5. VERIFY MISTRAL API KEY EXISTS
# ============================================================

if ([string]::IsNullOrWhiteSpace($env:MISTRAL_API_KEY)) {
    throw "MISTRAL_API_KEY is missing from this PowerShell session."
}

Write-Host "Mistral key is set." -ForegroundColor Green

# NEVER PRINT:
# $env:MISTRAL_API_KEY

# ============================================================
# 6. LOAD MISTRAL ANALYST PROMPT
# ============================================================

$mistralPrompt = Get-Content `
    -LiteralPath $promptFile `
    -Raw `
    -Encoding UTF8

if ([string]::IsNullOrWhiteSpace($mistralPrompt)) {
    throw "Mistral prompt file is empty."
}

$mistralPrompt = $mistralPrompt.Replace(
    "{{RUN_DATE}}",
    $runDate
)

Write-Host "Mistral analyst prompt loaded." -ForegroundColor DarkGreen

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
# 8. BUILD COMPLETE USER PROMPT
# ============================================================

$fullPrompt = @"
$mistralPrompt


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
# 10. CREDENTIAL SAFETY
#
# This version does NOT mistake ordinary phrases such as:
#
# risk-sensitivity
#
# for API keys.
#
# It also checks directly whether the actual Mistral key value
# somehow leaked into one of the prompt/context sources.
# ============================================================

$knownCredentialPattern = '(?i)(?<![A-Za-z0-9])(?:xai-[A-Za-z0-9_-]{20,}|sk-(?:proj-)?[A-Za-z0-9_-]{20,}|AIza[A-Za-z0-9_-]{20,}|Bearer\s+[A-Za-z0-9._~+/=-]{20,})'

$assignmentPattern = '(?i)(?:api[_ -]?key|access[_ -]?token|secret|password)\s*[:=]\s*["'']?[A-Za-z0-9._~+/=-]{24,}'

$scanSources = [ordered]@{
    "Mistral prompt" = $mistralPrompt
    "Open positions" = $openPositions
    "Signal ledger"  = $signalLedger
    "Thresholds"     = $thresholds
}

$credentialProblemFound = $false

foreach ($scanSource in $scanSources.GetEnumerator()) {

    $sourceTriggered = $false

    # --------------------------------------------------------
    # Exact current Mistral key check.
    #
    # The value itself is NEVER printed.
    # --------------------------------------------------------

    if (
        -not [string]::IsNullOrWhiteSpace($env:MISTRAL_API_KEY) -and
        $scanSource.Value.Contains($env:MISTRAL_API_KEY)
    ) {
        $sourceTriggered = $true
    }

    # --------------------------------------------------------
    # Common known credential patterns
    # --------------------------------------------------------

    if ($scanSource.Value -match $knownCredentialPattern) {
        $sourceTriggered = $true
    }

    # --------------------------------------------------------
    # Generic explicit secret assignment
    # --------------------------------------------------------

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
# 11. SYSTEM INSTRUCTION
# ============================================================

$systemInstruction = @"
You are Mistral acting as an independent long-context analytical
research model for zzz_passenger's Sleeping Passenger MVP.

This is a standalone Mistral API request.

OPERATIONAL BOUNDARIES:

- Advisory analysis only.
- Do not execute trades.
- Do not place broker orders.
- Do not cancel broker orders.
- Do not connect to brokers.
- Do not change leverage.
- Do not modify the repository.
- Do not modify local files.
- Do not update databases.
- Do not claim you performed reconciliation.
- Do not claim you inspected the local filesystem.
- Treat supplied local-file contents as pasted text only.
- Do not claim access to Google Sheets.
- Do not claim access to live prices unless supplied.
- Do not claim access to live filings unless supplied.
- Do not claim access to current news unless supplied.
- Do not claim access to social-media information unless supplied.
- No external tools are enabled in this request.

DATA DISCIPLINE:

Clearly distinguish:
1. facts supported by supplied context
2. analytical inference
3. live validation required
4. data insufficient

Never fabricate:
- current prices
- market moves
- financial ratios
- filings
- news
- social sentiment
- broker holdings
- fills
- PnL
- reconciliation status
- current catalysts

SECURITY:

Never reveal, infer, repeat, transform, summarize, or request
API keys, passwords, credentials, secrets, tokens, Bearer headers,
or environment-variable contents.

Follow the user's Mistral analyst prompt carefully.

Return the completed analyst report only.
"@

# ============================================================
# 12. BUILD CHAT COMPLETIONS REQUEST
#
# Mistral Medium 3.5 supports adjustable reasoning.
#
# reasoning_effort = high
#
# With high reasoning, Mistral may return:
#
# - thinking chunks
# - text chunks
#
# The extraction code below deliberately saves only the final
# text chunks into the readable report.
# ============================================================

$bodyObj = @{
    model = $model

    messages = @(
        @{
            role = "system"
            content = $systemInstruction
        },
        @{
            role = "user"
            content = $fullPrompt
        }
    )

    reasoning_effort = $reasoningEffort

    temperature = 0.2

    max_tokens = $maxTokens

    stream = $false
}

# ============================================================
# 13. SERIALIZE JSON
# ============================================================

$bodyJson = $bodyObj |
    ConvertTo-Json `
        -Depth 50 `
        -Compress

Write-Host "Request JSON created." -ForegroundColor DarkGreen

# ============================================================
# 14. AUTHORIZATION HEADER
# ============================================================

$headers = @{
    Authorization = "Bearer $($env:MISTRAL_API_KEY)"
}

# NEVER print $headers.

# ============================================================
# 15. HTTP REQUEST
# ============================================================

$requestParams = @{
    Uri = "https://api.mistral.ai/v1/chat/completions"

    Method = "Post"

    Headers = $headers

    ContentType = "application/json; charset=utf-8"

    Body = [System.Text.Encoding]::UTF8.GetBytes($bodyJson)

    TimeoutSec = 3600
}

# ============================================================
# 16. SEND REQUEST TO MISTRAL
# ============================================================

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " SENDING REQUEST TO MISTRAL" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "Model: $model"
Write-Host "Reasoning effort: $reasoningEffort"
Write-Host "Maximum completion tokens: $maxTokens"
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

    $safeException = [string]$_.Exception.Message
    $safeApiDetails = $apiErrorDetails

    # --------------------------------------------------------
    # Redact current Mistral key from an error response
    # if it somehow appears.
    # --------------------------------------------------------

    if (-not [string]::IsNullOrWhiteSpace($env:MISTRAL_API_KEY)) {

        $escapedMistralKey = [regex]::Escape(
            $env:MISTRAL_API_KEY
        )

        $safeException = [regex]::Replace(
            $safeException,
            $escapedMistralKey,
            "[REDACTED]"
        )

        $safeApiDetails = [regex]::Replace(
            $safeApiDetails,
            $escapedMistralKey,
            "[REDACTED]"
        )
    }

    $safeException = [regex]::Replace(
        $safeException,
        $knownCredentialPattern,
        "[REDACTED]"
    )

    $safeApiDetails = [regex]::Replace(
        $safeApiDetails,
        $knownCredentialPattern,
        "[REDACTED]"
    )

    $errorText = @"
MISTRAL API REQUEST FAILED

Date:
$runDate

Provider:
Mistral AI

Model:
$model

Endpoint:
https://api.mistral.ai/v1/chat/completions

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
    Write-Host "MISTRAL API REQUEST FAILED" -ForegroundColor Red
    Write-Host ""
    Write-Host "Safe error report:"
    Write-Host $errorFile
    Write-Host ""

    notepad $errorFile

    throw "Mistral API request failed. See $errorFile"
}

# ============================================================
# 17. SAVE COMPLETE RAW RESPONSE
# ============================================================

$response |
    ConvertTo-Json `
        -Depth 100 |
    Set-Content `
        -LiteralPath $rawFile `
        -Encoding UTF8

Write-Host "Raw Mistral response saved:" -ForegroundColor DarkGreen
Write-Host $rawFile
Write-Host ""

# ============================================================
# 18. VALIDATE CHOICES EXIST
# ============================================================

if (
    -not $response.choices -or
    $response.choices.Count -eq 0
) {

    Write-Host "Mistral returned no choices." -ForegroundColor Yellow

    notepad $rawFile

    throw "Mistral response contained no choices. See $rawFile"
}

# ============================================================
# 19. EXTRACT FINAL ANSWER ONLY
#
# Mistral documentation says reasoning_effort=high can return
# message.content as a LIST containing:
#
# type = thinking
# type = text
#
# We deliberately EXCLUDE thinking chunks from the final report.
#
# If content is a normal string, we use it directly.
# ============================================================

$textParts = New-Object System.Collections.Generic.List[string]

$content = $response.choices[0].message.content

if ($content -is [string]) {

    if (-not [string]::IsNullOrWhiteSpace($content)) {

        $textParts.Add(
            [string]$content
        )
    }
}
elseif ($content) {

    foreach ($contentPart in @($content)) {

        if (
            $contentPart.type -eq "text" -and
            -not [string]::IsNullOrWhiteSpace(
                [string]$contentPart.text
            )
        ) {

            $textParts.Add(
                [string]$contentPart.text
            )
        }

        # Deliberately ignore:
        #
        # type = thinking
    }
}

$result = ($textParts -join "`n").Trim()

# ============================================================
# 20. EMPTY FINAL-ANSWER CHECK
# ============================================================

if ([string]::IsNullOrWhiteSpace($result)) {

    Write-Host ""
    Write-Host "Mistral returned EMPTY final report text." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Opening raw response:"
    Write-Host $rawFile
    Write-Host ""

    notepad $rawFile

    throw @"
Mistral returned no extractable final-answer text.

Inspect the raw response for:

- choices
- message
- content
- finish_reason
- thinking/text chunk structure

Raw response:
$rawFile
"@
}

# ============================================================
# 21. FINISH-REASON CHECK
# ============================================================

$finishReason = [string]$response.choices[0].finish_reason

Write-Host "Mistral finish reason: $finishReason"

if ($finishReason -eq "length") {

    Write-Warning "Mistral reached max_tokens."
    Write-Warning "The report may be incomplete."
}

# ============================================================
# 22. OUTPUT CREDENTIAL SAFETY CHECK
# ============================================================

$outputCredentialProblem = $false

if (
    -not [string]::IsNullOrWhiteSpace($env:MISTRAL_API_KEY) -and
    $result.Contains($env:MISTRAL_API_KEY)
) {
    $outputCredentialProblem = $true
}

if ($result -match $knownCredentialPattern) {
    $outputCredentialProblem = $true
}

if ($result -match $assignmentPattern) {
    $outputCredentialProblem = $true
}

if ($outputCredentialProblem) {

    throw @"
ABORTED:
Mistral output appears to contain credential-like material.

The final readable report was NOT written.

The raw API response is available for manual inspection:
$rawFile
"@
}

# ============================================================
# 23. WRITE FINAL MISTRAL REPORT
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
Write-Host " MISTRAL REPORT COMPLETE" -ForegroundColor Green
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
Write-Host "Reasoning:"
Write-Host $reasoningEffort

Write-Host ""
Write-Host "Finish reason:"
Write-Host $finishReason

Write-Host ""
Write-Host "Final report:"
Write-Host $outFile

Write-Host ""
Write-Host "Raw response:"
Write-Host $rawFile

Write-Host ""
Write-Host "Opening Mistral report..."
Write-Host ""

notepad $outFile