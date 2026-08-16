Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ============================================================
# SLEEPING PASSENGER
# STANDALONE GOOGLE GEMINI API RUNNER
#
# PowerShell -> Google Gemini GenerateContent API
#            -> Gemini 3.1 Pro Preview
#
# NO GEMINI CLI
# NO OTHER AI MODEL
# NO BROKER ACTION
# NO REPOSITORY MODIFICATION BY GEMINI
# ============================================================

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

Set-Location "C:\Users\akash\sleeping-passenger-v1"

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " SLEEPING PASSENGER - GEMINI DAILY API RUN" -ForegroundColor Cyan
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

$provider = "Google Gemini"
$model = "gemini-3.1-pro-preview"
$thinkingLevel = "high"
$maxOutputTokens = 16000

$runDate = Get-Date -Format "yyyy-MM-dd"

Write-Host "Run date: $runDate"
Write-Host "Provider: $provider"
Write-Host "Model: $model"
Write-Host "Thinking level: $thinkingLevel"
Write-Host ""

# ============================================================
# 3. FILE PATHS
# ============================================================

$promptFile = ".\prompts\gemini_daily_prompt.txt"

$openPositionsFile = ".\moltbook\open_positions.json"
$signalLedgerFile = ".\moltbook\signal_ledger.json"
$thresholdsFile = ".\config\thresholds.yaml"

$outFile = ".\moltbook\gemini_report_$runDate.txt"
$rawFile = ".\moltbook\gemini_raw_response_$runDate.json"
$errorFile = ".\moltbook\gemini_http_error_$runDate.txt"

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
# 5. VERIFY GEMINI API KEY EXISTS
# ============================================================

if ([string]::IsNullOrWhiteSpace($env:GEMINI_API_KEY)) {
    throw "GEMINI_API_KEY is missing from this PowerShell session."
}

Write-Host "Gemini key is set." -ForegroundColor Green

# NEVER PRINT:
# $env:GEMINI_API_KEY

# ============================================================
# 6. LOAD GEMINI ANALYST PROMPT
# ============================================================

$geminiPrompt = Get-Content `
    -LiteralPath $promptFile `
    -Raw `
    -Encoding UTF8

if ([string]::IsNullOrWhiteSpace($geminiPrompt)) {
    throw "Gemini prompt file is empty."
}

$geminiPrompt = $geminiPrompt.Replace(
    "{{RUN_DATE}}",
    $runDate
)

Write-Host "Gemini analyst prompt loaded." -ForegroundColor DarkGreen

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
$geminiPrompt


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
# IMPORTANT:
#
# This checks actual credential-like VALUES.
#
# It does NOT abort merely because your prompt contains words
# such as:
#
# GEMINI_API_KEY
# API key
# risk-sensitivity
#
# It also explicitly checks whether the exact current Gemini
# API key has leaked into any prompt/context source.
# ============================================================

$knownCredentialPattern = '(?i)(?<![A-Za-z0-9])(?:AIza[A-Za-z0-9_-]{20,}|xai-[A-Za-z0-9_-]{20,}|sk-(?:proj-)?[A-Za-z0-9_-]{20,}|Bearer\s+[A-Za-z0-9._~+/=-]{20,})'

$assignmentPattern = '(?i)(?:api[_ -]?key|access[_ -]?token|secret|password)\s*[:=]\s*["'']?[A-Za-z0-9._~+/=-]{24,}'

# ============================================================
# 11. SCAN EACH SOURCE WITHOUT PRINTING ANY SECRET
# ============================================================

$scanSources = [ordered]@{
    "Gemini prompt"   = $geminiPrompt
    "Open positions"  = $openPositions
    "Signal ledger"   = $signalLedger
    "Thresholds"      = $thresholds
}

$credentialProblemFound = $false

foreach ($scanSource in $scanSources.GetEnumerator()) {

    $sourceTriggered = $false

    # --------------------------------------------------------
    # Exact current Gemini key check
    # --------------------------------------------------------

    if (
        -not [string]::IsNullOrWhiteSpace($env:GEMINI_API_KEY) -and
        $scanSource.Value.Contains($env:GEMINI_API_KEY)
    ) {
        $sourceTriggered = $true
    }

    # --------------------------------------------------------
    # Known credential patterns
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
# 12. GEMINI SYSTEM INSTRUCTION
# ============================================================

$systemInstruction = @"
You are Gemini acting as an independent long-context analytical
research model for zzz_passenger's Sleeping Passenger MVP.

This is a standalone Google Gemini API request.

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
- Do not claim access to Google Search unless explicitly enabled.
- No search grounding tool is enabled in this request.
- No code-execution tool is enabled in this request.
- No external market-data tool is enabled in this request.

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
- company filings
- current news
- current catalysts
- broker holdings
- fills
- PnL
- reconciliation status

SECURITY:

Never reveal, infer, repeat, transform, summarize, or request
API keys, passwords, credentials, secrets, tokens, Bearer headers,
or environment-variable contents.

Follow the user's Gemini analyst prompt carefully.

Return the completed analyst report only.
"@

# ============================================================
# 13. BUILD GEMINI GENERATECONTENT REQUEST
#
# Gemini 3.1 Pro supports thinkingLevel:
#
# low
# medium
# high
#
# We use HIGH for Sleeping Passenger.
#
# Google recommends leaving temperature at its default for
# Gemini 3.x, so temperature is deliberately NOT set here.
# ============================================================

$bodyObj = @{
    systemInstruction = @{
        parts = @(
            @{
                text = $systemInstruction
            }
        )
    }

    contents = @(
        @{
            role = "user"

            parts = @(
                @{
                    text = $fullPrompt
                }
            )
        }
    )

    generationConfig = @{
        maxOutputTokens = $maxOutputTokens

        thinkingConfig = @{
            thinkingLevel = $thinkingLevel
        }
    }

    store = $false
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
# 15. CREATE GEMINI AUTH HEADER
# ============================================================

$headers = @{
    "x-goog-api-key" = $env:GEMINI_API_KEY
}

# NEVER PRINT $headers.

# ============================================================
# 16. CREATE HTTP REQUEST
# ============================================================

$endpoint = "https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent"

$requestParams = @{
    Uri = $endpoint

    Method = "Post"

    Headers = $headers

    ContentType = "application/json; charset=utf-8"

    Body = [System.Text.Encoding]::UTF8.GetBytes($bodyJson)

    TimeoutSec = 3600
}

# ============================================================
# 17. SEND REQUEST TO GOOGLE GEMINI
# ============================================================

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " SENDING REQUEST TO GOOGLE GEMINI" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "Model: $model"
Write-Host "Thinking level: $thinkingLevel"
Write-Host "Maximum output tokens: $maxOutputTokens"
Write-Host "Temperature: Google Gemini default"
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
    # Redact the exact current Gemini key if it somehow
    # appears in an API error.
    # --------------------------------------------------------

    if (-not [string]::IsNullOrWhiteSpace($env:GEMINI_API_KEY)) {

        $escapedGeminiKey = [regex]::Escape(
            $env:GEMINI_API_KEY
        )

        $safeException = [regex]::Replace(
            $safeException,
            $escapedGeminiKey,
            "[REDACTED]"
        )

        $safeApiDetails = [regex]::Replace(
            $safeApiDetails,
            $escapedGeminiKey,
            "[REDACTED]"
        )
    }

    # --------------------------------------------------------
    # Redact other recognizable key formats.
    # --------------------------------------------------------

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
GEMINI API REQUEST FAILED

Date:
$runDate

Provider:
Google Gemini

Model:
$model

Endpoint:
$endpoint

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
    Write-Host "GEMINI API REQUEST FAILED" -ForegroundColor Red
    Write-Host ""
    Write-Host "Safe error report:"
    Write-Host $errorFile
    Write-Host ""

    notepad $errorFile

    throw "Gemini API request failed. See $errorFile"
}

# ============================================================
# 18. SAVE COMPLETE RAW GEMINI RESPONSE
# ============================================================

$response |
    ConvertTo-Json `
        -Depth 100 |
    Set-Content `
        -LiteralPath $rawFile `
        -Encoding UTF8

Write-Host "Raw Gemini response saved:" -ForegroundColor DarkGreen
Write-Host $rawFile
Write-Host ""

# ============================================================
# 19. CHECK FOR PROMPT-LEVEL BLOCKING
# ============================================================

if ($response.PSObject.Properties.Name -contains "promptFeedback") {

    $promptFeedback = $response.promptFeedback

    if (
        $null -ne $promptFeedback -and
        $promptFeedback.PSObject.Properties.Name -contains "blockReason"
    ) {

        $blockReason = [string]$promptFeedback.blockReason

        if (-not [string]::IsNullOrWhiteSpace($blockReason)) {

            Write-Host ""
            Write-Host "Gemini prompt block reason: $blockReason" -ForegroundColor Yellow
            Write-Host "Opening raw response:"
            Write-Host $rawFile

            notepad $rawFile

            throw "Gemini blocked the request. Inspect promptFeedback in $rawFile"
        }
    }
}

# ============================================================
# 20. VERIFY CANDIDATES EXIST
# ============================================================

if (-not ($response.PSObject.Properties.Name -contains "candidates")) {

    Write-Host "Gemini response contains no candidates property." -ForegroundColor Yellow

    notepad $rawFile

    throw "Gemini returned no candidates. See $rawFile"
}

if (
    $null -eq $response.candidates -or
    @($response.candidates).Count -eq 0
) {

    Write-Host "Gemini returned zero candidates." -ForegroundColor Yellow

    notepad $rawFile

    throw "Gemini returned zero candidates. See $rawFile"
}

# ============================================================
# 21. READ FINISH REASON
# ============================================================

$firstCandidate = @($response.candidates)[0]

$finishReason = ""

if (
    $firstCandidate.PSObject.Properties.Name -contains "finishReason"
) {
    $finishReason = [string]$firstCandidate.finishReason
}

Write-Host "Gemini finish reason: $finishReason"

if ($finishReason -eq "MAX_TOKENS") {

    Write-Warning "Gemini reached maxOutputTokens."
    Write-Warning "The report may be incomplete."
}

# ============================================================
# 22. EXTRACT FINAL TEXT
#
# Gemini output:
#
# candidates[]
#   -> content
#      -> parts[]
#         -> text
#
# We ignore non-text parts and any explicitly marked thought
# parts if present.
# ============================================================

$textParts = New-Object System.Collections.Generic.List[string]

if (
    $firstCandidate.PSObject.Properties.Name -contains "content" -and
    $null -ne $firstCandidate.content
) {

    $candidateContent = $firstCandidate.content

    if (
        $candidateContent.PSObject.Properties.Name -contains "parts" -and
        $null -ne $candidateContent.parts
    ) {

        foreach ($contentPart in @($candidateContent.parts)) {

            $isThought = $false

            if (
                $contentPart.PSObject.Properties.Name -contains "thought"
            ) {
                $isThought = [bool]$contentPart.thought
            }

            if ($isThought) {
                continue
            }

            if (
                $contentPart.PSObject.Properties.Name -contains "text"
            ) {

                $partText = [string]$contentPart.text

                if (-not [string]::IsNullOrWhiteSpace($partText)) {

                    $textParts.Add(
                        $partText
                    )
                }
            }
        }
    }
}

$result = ($textParts -join "`n").Trim()

# ============================================================
# 23. EMPTY OUTPUT CHECK
# ============================================================

if ([string]::IsNullOrWhiteSpace($result)) {

    Write-Host ""
    Write-Host "Gemini returned EMPTY final report text." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Opening raw response:"
    Write-Host $rawFile
    Write-Host ""

    notepad $rawFile

    throw @"
Gemini returned no extractable final-answer text.

Inspect the raw response for:

- promptFeedback
- candidates
- finishReason
- content
- parts
- safetyRatings

Raw response:
$rawFile
"@
}

# ============================================================
# 24. OUTPUT CREDENTIAL SAFETY CHECK
# ============================================================

$outputCredentialProblem = $false

# Exact current Gemini key.
if (
    -not [string]::IsNullOrWhiteSpace($env:GEMINI_API_KEY) -and
    $result.Contains($env:GEMINI_API_KEY)
) {
    $outputCredentialProblem = $true
}

# Common credential formats.
if ($result -match $knownCredentialPattern) {
    $outputCredentialProblem = $true
}

# Generic explicit secret assignment.
if ($result -match $assignmentPattern) {
    $outputCredentialProblem = $true
}

if ($outputCredentialProblem) {

    throw @"
ABORTED:
Gemini output appears to contain credential-like material.

The final readable report was NOT written.

The raw API response is available for manual inspection:
$rawFile
"@
}

# ============================================================
# 25. WRITE FINAL GEMINI REPORT
# ============================================================

$result |
    Set-Content `
        -LiteralPath $outFile `
        -Encoding UTF8

# ============================================================
# 26. USAGE METADATA — SAFE TO PRINT
# ============================================================

if (
    $response.PSObject.Properties.Name -contains "usageMetadata" -and
    $null -ne $response.usageMetadata
) {

    Write-Host ""
    Write-Host "Gemini usage metadata available in raw response." -ForegroundColor DarkGreen
}

# ============================================================
# 27. FINAL STATUS
# ============================================================

Write-Host ""
Write-Host "==================================================" -ForegroundColor Green
Write-Host " GEMINI REPORT COMPLETE" -ForegroundColor Green
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
Write-Host "Thinking level:"
Write-Host $thinkingLevel

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
Write-Host "Opening Gemini report..."
Write-Host ""

notepad $outFile