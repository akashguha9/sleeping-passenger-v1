Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ============================================================
# SLEEPING PASSENGER
# STANDALONE GPT API RUNNER
# ============================================================

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

Set-Location "C:\Users\akash\sleeping-passenger-v1"

Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host " SLEEPING PASSENGER - GPT DAILY API RUN" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""

# ------------------------------------------------------------
# 1. CLEAN OLD IN-MEMORY VARIABLES
# ------------------------------------------------------------

Remove-Variable response -ErrorAction SilentlyContinue
Remove-Variable result -ErrorAction SilentlyContinue
Remove-Variable bodyObj -ErrorAction SilentlyContinue
Remove-Variable bodyJson -ErrorAction SilentlyContinue
Remove-Variable requestParams -ErrorAction SilentlyContinue

# ------------------------------------------------------------
# 2. RUN SETTINGS
# ------------------------------------------------------------

$provider = "gpt"
$model = "gpt-5.6-sol"
$runDate = Get-Date -Format "yyyy-MM-dd"

Write-Host "Run date: $runDate"
Write-Host "Provider: OpenAI"
Write-Host "Model: $model"
Write-Host ""

# ------------------------------------------------------------
# 3. FILE PATHS
# ------------------------------------------------------------

$promptFile = ".\prompts\gpt_daily_prompt.txt"

$openPositionsFile = ".\moltbook\open_positions.json"
$signalLedgerFile = ".\moltbook\signal_ledger.json"
$thresholdsFile = ".\config\thresholds.yaml"

$rawFile = ".\moltbook\gpt_raw_response_$runDate.json"
$errorFile = ".\moltbook\gpt_http_error_$runDate.txt"
$outFile = ".\moltbook\gpt_report_$runDate.txt"

# ------------------------------------------------------------
# 4. VERIFY REQUIRED FILES
# ------------------------------------------------------------

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

# ------------------------------------------------------------
# 5. VERIFY OPENAI KEY EXISTS
# ------------------------------------------------------------

if ([string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) {

    throw "OPENAI_API_KEY is missing from this PowerShell session."

}

Write-Host "OpenAI key is set." -ForegroundColor Green

# NEVER PRINT THE ACTUAL KEY.

# ------------------------------------------------------------
# 6. LOAD GPT PROMPT
# ------------------------------------------------------------

$gptPrompt = Get-Content `
    -LiteralPath $promptFile `
    -Raw `
    -Encoding UTF8

$gptPrompt = $gptPrompt.Replace(
    "{{RUN_DATE}}",
    $runDate
)

if ([string]::IsNullOrWhiteSpace($gptPrompt)) {

    throw "GPT prompt file is empty."

}

# ------------------------------------------------------------
# 7. LOAD LOCAL MVP CONTEXT
# ------------------------------------------------------------

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

# ------------------------------------------------------------
# 8. BUILD COMPLETE USER PROMPT
# ------------------------------------------------------------

$fullPrompt = @"
$gptPrompt


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
END LOCAL MVP CONTEXT
============================================================
"@

# ------------------------------------------------------------
# 9. REMOVE INVALID UTF-16 SURROGATES
# ------------------------------------------------------------

$fullPrompt = [regex]::Replace(
    $fullPrompt,
    '[\uD800-\uDFFF]',
    ''
)

# ------------------------------------------------------------
# 10. CREDENTIAL SAFETY SCANNER
#
# Important:
# The boundary before "sk-" prevents normal words such as
# "risk-sensitivity" from being falsely detected as API keys.
# ------------------------------------------------------------

$keyPattern = '(?i)((?<![A-Za-z0-9])sk-(?:proj-)?[A-Za-z0-9_-]{20,}|(?<![A-Za-z0-9])xai-[A-Za-z0-9_-]{20,}|(?<![A-Za-z0-9])AIza[A-Za-z0-9_-]{20,}|Bearer\s+[A-Za-z0-9._~+/=-]{20,}|(?:OPENAI|ANTHROPIC|XAI|GEMINI|GOOGLE|MISTRAL|DEEPSEEK|PERPLEXITY)_API_KEY\s*[:=]\s*["'']?[A-Za-z0-9._~+/=-]{16,}|(?:api[_ -]?key|access[_ -]?token|secret)\s*[:=]\s*["'']?[A-Za-z0-9._~+/=-]{20,})'

# ------------------------------------------------------------
# 11. IDENTIFY SOURCE OF CREDENTIAL PROBLEM WITHOUT PRINTING IT
# ------------------------------------------------------------

$scanSources = [ordered]@{
    "GPT prompt"     = $gptPrompt
    "Open positions" = $openPositions
    "Signal ledger"  = $signalLedger
    "Thresholds"     = $thresholds
}

$credentialProblemFound = $false

foreach ($scanSource in $scanSources.GetEnumerator()) {

    if ($scanSource.Value -match $keyPattern) {

        Write-Host `
            "Credential scanner triggered by: $($scanSource.Key)" `
            -ForegroundColor Red

        $credentialProblemFound = $true
    }
}

if ($credentialProblemFound) {

    throw "ABORTED: API-key-like credential material was detected in prompt/context."

}

Write-Host "Credential safety scan passed." -ForegroundColor Green

# ------------------------------------------------------------
# 12. SYSTEM INSTRUCTION
# ------------------------------------------------------------

$systemInstruction = @"
You are GPT-5.6 Sol, an independent long-context synthesis analyst
for zzz_passenger's Sleeping Passenger MVP.

OPERATIONAL BOUNDARIES:

- You are advisory only.
- Do not execute trades.
- Do not place broker orders.
- Do not cancel broker orders.
- Do not use leverage on behalf of the operator.
- Do not modify the repository.
- Do not modify files.
- Do not update databases.
- Do not claim that an action was executed.
- Do not claim you accessed files other than the text pasted into this request.
- Treat supplied local files as pasted context only.
- Clearly distinguish supplied facts from analytical inference.
- Do not invent prices.
- Do not invent filings.
- Do not invent news.
- Do not invent portfolio positions.
- Do not invent PnL.
- Do not invent live market conditions.
- Never reveal, infer, transform, repeat, summarize or request API keys,
  secrets, passwords, credentials, tokens, Bearer headers or environment
  variable contents.

Follow the user's analyst prompt carefully.

Return the completed analyst report only.
"@

# ------------------------------------------------------------
# 13. CREATE OPENAI RESPONSES API BODY
# ------------------------------------------------------------

$bodyObj = @{
    model = $model

    instructions = $systemInstruction

    input = $fullPrompt

    reasoning = @{
        effort = "high"
    }

    max_output_tokens = 16000

    store = $false
}

$bodyJson = $bodyObj |
    ConvertTo-Json `
        -Depth 50 `
        -Compress

# ------------------------------------------------------------
# 14. AUTHORIZATION HEADER
# ------------------------------------------------------------

$headers = @{
    Authorization = "Bearer $($env:OPENAI_API_KEY)"
}

# ------------------------------------------------------------
# 15. CREATE REQUEST
# ------------------------------------------------------------

$requestParams = @{
    Uri = "https://api.openai.com/v1/responses"

    Method = "Post"

    Headers = $headers

    ContentType = "application/json; charset=utf-8"

    Body = [System.Text.Encoding]::UTF8.GetBytes($bodyJson)

    TimeoutSec = 3600
}

# ------------------------------------------------------------
# 16. CALL OPENAI
# ------------------------------------------------------------

Write-Host ""
Write-Host "Sending request to OpenAI..." -ForegroundColor Cyan
Write-Host "This can take several minutes for a large reasoning prompt."
Write-Host ""

try {

    $response = Invoke-RestMethod @requestParams

}
catch {

    $apiErrorDetails = ""

    if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
        $apiErrorDetails = $_.ErrorDetails.Message
    }

    $errorText = @"
GPT API REQUEST FAILED

Date:
$runDate

Model:
$model

Exception:
$($_.Exception.Message)

API error details:
$apiErrorDetails
"@

    $errorText |
        Set-Content `
            -LiteralPath $errorFile `
            -Encoding UTF8

    Write-Host ""
    Write-Host "GPT API REQUEST FAILED" -ForegroundColor Red
    Write-Host "Error report written to:"
    Write-Host $errorFile
    Write-Host ""

    notepad $errorFile

    throw "GPT API request failed. See $errorFile"
}

# ------------------------------------------------------------
# 17. SAVE COMPLETE RAW RESPONSE
# ------------------------------------------------------------

$response |
    ConvertTo-Json `
        -Depth 100 |
    Set-Content `
        -LiteralPath $rawFile `
        -Encoding UTF8

Write-Host "Raw OpenAI response saved:"
Write-Host $rawFile
Write-Host ""

# ------------------------------------------------------------
# 18. EXTRACT TEXT FROM RESPONSES API
# ------------------------------------------------------------

$textParts = New-Object System.Collections.Generic.List[string]

# Some API/client representations may expose output_text directly.
if (
    $response.PSObject.Properties.Name -contains "output_text" -and
    -not [string]::IsNullOrWhiteSpace([string]$response.output_text)
) {

    $textParts.Add([string]$response.output_text)

}

# Normal Responses API structure:
# output[] -> message -> content[] -> output_text -> text

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

$result = ($textParts -join "`n").Trim()

# ------------------------------------------------------------
# 19. HANDLE EMPTY OUTPUT
# ------------------------------------------------------------

if ([string]::IsNullOrWhiteSpace($result)) {

    Write-Host ""
    Write-Host "GPT returned EMPTY report text." -ForegroundColor Yellow
    Write-Host "Opening raw response:"
    Write-Host $rawFile
    Write-Host ""

    notepad $rawFile

    throw @"
GPT output was empty.

Inspect:
- status
- error
- incomplete_details
- output
- refusal information

Raw file:
$rawFile
"@
}

# ------------------------------------------------------------
# 20. OUTPUT CREDENTIAL SAFETY CHECK
# ------------------------------------------------------------

if ($result -match $keyPattern) {

    throw "ABORTED: GPT output contains API-key-like credential material. Report was NOT written."

}

# ------------------------------------------------------------
# 21. WRITE FINAL GPT REPORT
# ------------------------------------------------------------

$result |
    Set-Content `
        -LiteralPath $outFile `
        -Encoding UTF8

Write-Host ""
Write-Host "=============================================" -ForegroundColor Green
Write-Host " GPT REPORT COMPLETE" -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Green
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
Write-Host "Opening final report..."
Write-Host ""

notepad $outFile