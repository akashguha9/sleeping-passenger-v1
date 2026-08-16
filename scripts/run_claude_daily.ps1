Set-StrictMode -Version Latest

$reader = $null
$stream = $null
$response = $null
$request = $null
$client = $null
$rawWriter = $null

$ErrorActionPreference = "Stop"

# ============================================================
# SLEEPING PASSENGER
# CLAUDE FABLE 5 STREAMING API RUNNER
#
# PowerShell
#     ->
# Anthropic Messages API with SSE streaming
#     ->
# claude-fable-5
#
# Designed specifically to prevent long non-streaming
# Fable requests from timing out.
# ============================================================

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

Add-Type -AssemblyName System.Net.Http

Set-Location "C:\Users\akash\sleeping-passenger-v1"

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " SLEEPING PASSENGER - CLAUDE STREAMING API RUN" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# ============================================================
# 1. SETTINGS
# ============================================================

$provider = "Anthropic"
$model = "claude-fable-5"

# Fable 5 default/high reasoning depth.
$effort = "high"

# IMPORTANT:
# max_tokens includes Claude's total generated output budget,
# including adaptive reasoning plus visible response.
$maxTokens = 32000

$runDate = Get-Date -Format "yyyy-MM-dd"

Write-Host "Run date: $runDate"
Write-Host "Provider: $provider"
Write-Host "Model: $model"
Write-Host "Effort: $effort"
Write-Host "Output budget: $maxTokens"
Write-Host "Transport: STREAMING SSE"
Write-Host ""

# ============================================================
# 2. FILE PATHS
# ============================================================

$promptFile = ".\prompts\claude_daily_prompt.txt"

$openPositionsFile = ".\moltbook\open_positions.json"
$signalLedgerFile = ".\moltbook\signal_ledger.json"
$thresholdsFile = ".\config\thresholds.yaml"

$outFile = ".\moltbook\claude_report_$runDate.txt"
$rawStreamFile = ".\moltbook\claude_raw_stream_$runDate.txt"
$errorFile = ".\moltbook\claude_http_error_$runDate.txt"

# ============================================================
# 3. VERIFY REQUIRED FILES
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
# 4. VERIFY ANTHROPIC KEY
# ============================================================

if ([string]::IsNullOrWhiteSpace($env:ANTHROPIC_API_KEY)) {
    throw "ANTHROPIC_API_KEY is missing from this PowerShell session."
}

Write-Host "Anthropic key is set." -ForegroundColor Green

# NEVER PRINT:
# $env:ANTHROPIC_API_KEY

# ============================================================
# 5. LOAD CLAUDE PROMPT
# ============================================================

$claudePrompt = Get-Content `
    -LiteralPath $promptFile `
    -Raw `
    -Encoding UTF8

if ([string]::IsNullOrWhiteSpace($claudePrompt)) {
    throw "Claude prompt file is empty."
}

$claudePrompt = $claudePrompt.Replace(
    "{{RUN_DATE}}",
    $runDate
)

Write-Host "Claude analyst prompt loaded." -ForegroundColor DarkGreen

# ============================================================
# 6. LOAD LOCAL MVP CONTEXT
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
# 7. BUILD USER PROMPT
# ============================================================

$fullPrompt = @"
$claudePrompt


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

# Remove invalid surrogate characters.
$fullPrompt = [regex]::Replace(
    $fullPrompt,
    '[\uD800-\uDFFF]',
    ''
)

# ============================================================
# 8. CREDENTIAL SAFETY
#
# Fixes the old risk-sensitivity / sk-sensitivity false hit.
# ============================================================

$knownCredentialPattern = '(?i)(?<![A-Za-z0-9])(?:sk-ant-[A-Za-z0-9_-]{20,}|sk-(?:proj-)?[A-Za-z0-9_-]{20,}|xai-[A-Za-z0-9_-]{20,}|AIza[A-Za-z0-9_-]{20,}|Bearer\s+[A-Za-z0-9._~+/=-]{20,})'

$assignmentPattern = '(?i)(?:api[_ -]?key|access[_ -]?token|secret|password)\s*[:=]\s*["'']?[A-Za-z0-9._~+/=-]{24,}'

$scanSources = [ordered]@{
    "Claude prompt"   = $claudePrompt
    "Open positions"  = $openPositions
    "Signal ledger"   = $signalLedger
    "Thresholds"      = $thresholds
}

$credentialProblemFound = $false

foreach ($scanSource in $scanSources.GetEnumerator()) {

    $sourceTriggered = $false

    if (
        -not [string]::IsNullOrWhiteSpace($env:ANTHROPIC_API_KEY) -and
        $scanSource.Value.Contains($env:ANTHROPIC_API_KEY)
    ) {
        $sourceTriggered = $true
    }

    if ($scanSource.Value -match $knownCredentialPattern) {
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
Possible credential material was detected in prompt/context.

The credential itself was NOT displayed.
"@
}

Write-Host "Credential safety scan passed." -ForegroundColor Green

# ============================================================
# 9. SYSTEM INSTRUCTION
# ============================================================

$systemInstruction = @"
You are Claude operating as an independent long-context analytical
research model for zzz_passenger's Sleeping Passenger MVP.

This is a standalone Anthropic API request.

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
- No web-search tool is enabled.
- No code-execution tool is enabled.
- No broker tool is enabled.
- No filesystem tool is enabled.

DATA DISCIPLINE:

Clearly distinguish:

1. facts supported by supplied context
2. analytical inference
3. live validation required
4. data insufficient

Never fabricate:

- current prices
- market moves
- ratios
- filings
- current news
- current catalysts
- broker holdings
- fills
- PnL
- reconciliation status

SECURITY:

Never reveal, repeat, infer, transform, summarize, or request
API keys, passwords, credentials, secrets, tokens,
authentication headers, or environment-variable contents.

Follow the user's Claude analyst prompt carefully.

Return the completed analyst report only.
"@

# ============================================================
# 10. BUILD ANTHROPIC REQUEST
#
# Fable 5 has adaptive thinking.
#
# STREAMING IS ENABLED.
# ============================================================

$bodyObj = @{
    model = $model

    max_tokens = $maxTokens

    system = $systemInstruction

    messages = @(
        @{
            role = "user"
            content = $fullPrompt
        }
    )

    thinking = @{
        type = "adaptive"

        # Fable 5 does not return raw private chain of thought.
        # Omitted thinking output keeps the wire response lean.
        display = "omitted"
    }

    output_config = @{
        effort = $effort
    }

    stream = $true
}

$bodyJson = $bodyObj |
    ConvertTo-Json `
        -Depth 50 `
        -Compress

Write-Host "Request JSON created." -ForegroundColor DarkGreen

# ============================================================
# 11. INITIALIZE OUTPUT FILES
# ============================================================

"" |
    Set-Content `
        -LiteralPath $rawStreamFile `
        -Encoding UTF8

"" |
    Set-Content `
        -LiteralPath $outFile `
        -Encoding UTF8

# ============================================================
# 12. CREATE HTTPCLIENT
#
# Important:
#
# We use HttpClient directly rather than Invoke-RestMethod.
#
# Timeout is infinite because Anthropic itself controls the
# request lifecycle and SSE traffic keeps the connection active.
# ============================================================

$handler = New-Object System.Net.Http.HttpClientHandler

$client = New-Object System.Net.Http.HttpClient($handler)

$client.Timeout = [System.Threading.Timeout]::InfiniteTimeSpan

$request = New-Object System.Net.Http.HttpRequestMessage

$request.Method = [System.Net.Http.HttpMethod]::Post

$request.RequestUri = [Uri]"https://api.anthropic.com/v1/messages"

$request.Headers.Add(
    "x-api-key",
    $env:ANTHROPIC_API_KEY
)

$request.Headers.Add(
    "anthropic-version",
    "2023-06-01"
)

$request.Headers.Accept.Add(
    [System.Net.Http.Headers.MediaTypeWithQualityHeaderValue]::new(
        "text/event-stream"
    )
)

$request.Content = New-Object System.Net.Http.StringContent(
    $bodyJson,
    [System.Text.Encoding]::UTF8,
    "application/json"
)

# ============================================================
# 13. STREAM STATE
# ============================================================

$textBuilder = New-Object System.Text.StringBuilder

$stopReason = ""
$inputTokens = $null
$outputTokens = $null
$messageId = ""

$receivedAnyEvent = $false
$receivedText = $false

# ============================================================
# 14. SEND STREAMING REQUEST
# ============================================================

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " SENDING STREAMING REQUEST TO CLAUDE" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "Model: $model"
Write-Host "Adaptive thinking: ENABLED"
Write-Host "Effort: $effort"
Write-Host "Maximum output budget: $maxTokens"
Write-Host "Streaming: ENABLED"
Write-Host ""
Write-Host "Fable may think for a long time."
Write-Host "SSE ping events will keep this connection active."
Write-Host ""
Write-Host "Waiting for Claude..."
Write-Host ""

try {

    $httpResponse = $client.SendAsync(
        $request,
        [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead
    ).GetAwaiter().GetResult()

    if (-not $httpResponse.IsSuccessStatusCode) {

        $errorBody = $httpResponse.Content.ReadAsStringAsync().GetAwaiter().GetResult()

        if (-not [string]::IsNullOrWhiteSpace($env:ANTHROPIC_API_KEY)) {

            $escapedKey = [regex]::Escape(
                $env:ANTHROPIC_API_KEY
            )

            $errorBody = [regex]::Replace(
                $errorBody,
                $escapedKey,
                "[REDACTED]"
            )
        }

        $errorBody = [regex]::Replace(
            $errorBody,
            $knownCredentialPattern,
            "[REDACTED]"
        )

        $errorText = @"
CLAUDE API REQUEST FAILED

Date:
$runDate

Provider:
Anthropic

Model:
$model

HTTP status:
$([int]$httpResponse.StatusCode)

HTTP reason:
$($httpResponse.ReasonPhrase)

API response:
$errorBody
"@

        $errorText |
            Set-Content `
                -LiteralPath $errorFile `
                -Encoding UTF8

        throw "Claude returned HTTP $([int]$httpResponse.StatusCode). See $errorFile"
    }

    Write-Host "Anthropic accepted request." -ForegroundColor Green
    Write-Host "Streaming response..." -ForegroundColor Cyan
    Write-Host ""

    $stream = $httpResponse.Content.ReadAsStreamAsync().GetAwaiter().GetResult()

    $reader = New-Object System.IO.StreamReader(
        $stream,
        [System.Text.Encoding]::UTF8
    )

    # ========================================================
    # 15. READ ANTHROPIC SSE LINE-BY-LINE
    # ========================================================

    while (-not $reader.EndOfStream) {

        $line = $reader.ReadLineAsync().GetAwaiter().GetResult()

        if ($null -eq $line) {
            continue
        }

        # Save complete SSE stream for diagnostics.
        $line |
            Add-Content `
                -LiteralPath $rawStreamFile `
                -Encoding UTF8

        # Ignore blank lines.
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }

        # We only parse SSE data records.
        if (-not $line.StartsWith("data:")) {
            continue
        }

        $jsonText = $line.Substring(5).Trim()

        if ([string]::IsNullOrWhiteSpace($jsonText)) {
            continue
        }

        try {
            $evt = $jsonText | ConvertFrom-Json
        }
        catch {
            # Preserve malformed/unexpected event in raw stream,
            # but do not crash the entire analysis immediately.
            continue
        }

        $receivedAnyEvent = $true

        # ====================================================
        # MESSAGE START
        # ====================================================

        if ($evt.type -eq "message_start") {

            if ($evt.message) {

                if ($evt.message.id) {
                    $messageId = [string]$evt.message.id
                }

                if (
                    $evt.message.usage -and
                    $null -ne $evt.message.usage.input_tokens
                ) {
                    $inputTokens = $evt.message.usage.input_tokens
                }
            }

            Write-Host "Claude stream started." -ForegroundColor DarkGreen

            if (-not [string]::IsNullOrWhiteSpace($messageId)) {
                Write-Host "Message ID received."
            }

            continue
        }

        # ====================================================
        # PING
        #
        # Anthropic sends pings during long requests.
        # We only show a small heartbeat.
        # ====================================================

        if ($evt.type -eq "ping") {

            Write-Host "." -NoNewline -ForegroundColor DarkGray
            continue
        }

        # ====================================================
        # TEXT DELTA
        # ====================================================

        if ($evt.type -eq "content_block_delta") {

            if (
                $evt.delta -and
                $evt.delta.type -eq "text_delta"
            ) {

                $chunk = [string]$evt.delta.text

                if (-not [string]::IsNullOrEmpty($chunk)) {

                    [void]$textBuilder.Append($chunk)

                    # Write visible answer incrementally.
                    $chunk |
                        Add-Content `
                            -LiteralPath $outFile `
                            -NoNewline `
                            -Encoding UTF8

                    $receivedText = $true
                }
            }

            # Deliberately ignore thinking/signature deltas.
            continue
        }

        # ====================================================
        # MESSAGE DELTA
        # ====================================================

        if ($evt.type -eq "message_delta") {

            if (
                $evt.delta -and
                $evt.delta.stop_reason
            ) {
                $stopReason = [string]$evt.delta.stop_reason
            }

            if (
                $evt.usage -and
                $null -ne $evt.usage.output_tokens
            ) {
                $outputTokens = $evt.usage.output_tokens
            }

            continue
        }

        # ====================================================
        # API ERROR EVENT
        # ====================================================

        if ($evt.type -eq "error") {

            $safeStreamError = $jsonText

            if (-not [string]::IsNullOrWhiteSpace($env:ANTHROPIC_API_KEY)) {

                $escapedKey = [regex]::Escape(
                    $env:ANTHROPIC_API_KEY
                )

                $safeStreamError = [regex]::Replace(
                    $safeStreamError,
                    $escapedKey,
                    "[REDACTED]"
                )
            }

            $safeStreamError = [regex]::Replace(
                $safeStreamError,
                $knownCredentialPattern,
                "[REDACTED]"
            )

            $errorText = @"
CLAUDE STREAM ERROR

Date:
$runDate

Provider:
Anthropic

Model:
$model

Stream error:
$safeStreamError

Raw stream:
$rawStreamFile
"@

            $errorText |
                Set-Content `
                    -LiteralPath $errorFile `
                    -Encoding UTF8

            throw "Claude returned a streaming error. See $errorFile"
        }

        # ====================================================
        # MESSAGE STOP
        # ====================================================

        if ($evt.type -eq "message_stop") {

            Write-Host ""
            Write-Host ""
            Write-Host "Claude stream completed." -ForegroundColor Green

            break
        }
    }
}
catch {

    $safeException = [string]$_.Exception.Message

    if (-not [string]::IsNullOrWhiteSpace($env:ANTHROPIC_API_KEY)) {

        $escapedKey = [regex]::Escape(
            $env:ANTHROPIC_API_KEY
        )

        $safeException = [regex]::Replace(
            $safeException,
            $escapedKey,
            "[REDACTED]"
        )
    }

    $safeException = [regex]::Replace(
        $safeException,
        $knownCredentialPattern,
        "[REDACTED]"
    )

    # Do not overwrite a richer API error file if one exists.
    if (-not (Test-Path -LiteralPath $errorFile)) {

        $errorText = @"
CLAUDE STREAMING REQUEST FAILED

Date:
$runDate

Provider:
Anthropic

Model:
$model

Exception:
$safeException

Raw stream, if any:
$rawStreamFile
"@

        $errorText |
            Set-Content `
                -LiteralPath $errorFile `
                -Encoding UTF8
    }

    Write-Host ""
    Write-Host "CLAUDE STREAMING REQUEST FAILED" -ForegroundColor Red
    Write-Host ""
    Write-Host "Error report:"
    Write-Host $errorFile
    Write-Host ""

    if (Test-Path -LiteralPath $errorFile) {
        notepad $errorFile
    }

    throw
}
finally {

    if ($null -ne $reader) {
        $reader.Dispose()
    }

    if ($null -ne $stream) {
        $stream.Dispose()
    }

    if ($null -ne $httpResponse) {
        $httpResponse.Dispose()
    }

    if ($null -ne $request) {
        $request.Dispose()
    }

    if ($null -ne $client) {
        $client.Dispose()
    }

    if ($null -ne $handler) {
        $handler.Dispose()
    }
}

# ============================================================
# 16. VALIDATE STREAM
# ============================================================

if (-not $receivedAnyEvent) {

    throw @"
Claude returned no SSE events.

Inspect:
$rawStreamFile
"@
}

if (-not $receivedText) {

    throw @"
Claude stream completed without final text.

Inspect:
$rawStreamFile
"@
}

$result = $textBuilder.ToString().Trim()

if ([string]::IsNullOrWhiteSpace($result)) {

    throw "Claude final report text is empty."
}

# ============================================================
# 17. OUTPUT CREDENTIAL SAFETY
# ============================================================

$outputCredentialProblem = $false

if (
    -not [string]::IsNullOrWhiteSpace($env:ANTHROPIC_API_KEY) -and
    $result.Contains($env:ANTHROPIC_API_KEY)
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

    Remove-Item `
        -LiteralPath $outFile `
        -Force `
        -ErrorAction SilentlyContinue

    throw @"
ABORTED:
Claude output appears to contain credential-like material.

Readable report deleted.

Diagnostic stream:
$rawStreamFile
"@
}

# ============================================================
# 18. NORMALIZE FINAL REPORT FILE
# ============================================================

$result |
    Set-Content `
        -LiteralPath $outFile `
        -Encoding UTF8

# ============================================================
# 19. STOP-REASON WARNINGS
# ============================================================

if ($stopReason -eq "max_tokens") {

    Write-Warning "Claude reached max_tokens."
    Write-Warning "The report may be incomplete."
}

if ($stopReason -eq "model_context_window_exceeded") {

    Write-Warning "Claude reached its context window."
}

if ($stopReason -eq "refusal") {

    Write-Warning "Claude returned a refusal stop reason."
}

if ($stopReason -eq "pause_turn") {

    Write-Warning "Claude returned pause_turn."
    Write-Warning "The task may require a continuation request."
}

# ============================================================
# 20. FINAL STATUS
# ============================================================

Write-Host ""
Write-Host "==================================================" -ForegroundColor Green
Write-Host " CLAUDE REPORT COMPLETE" -ForegroundColor Green
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
Write-Host "Effort:"
Write-Host $effort

Write-Host ""
Write-Host "Streaming:"
Write-Host "ENABLED"

Write-Host ""
Write-Host "Stop reason:"
Write-Host $stopReason

if ($null -ne $inputTokens) {
    Write-Host ""
    Write-Host "Input tokens:"
    Write-Host $inputTokens
}

if ($null -ne $outputTokens) {
    Write-Host ""
    Write-Host "Output tokens:"
    Write-Host $outputTokens
}

Write-Host ""
Write-Host "Final report:"
Write-Host $outFile

Write-Host ""
Write-Host "Raw SSE stream:"
Write-Host $rawStreamFile

Write-Host ""
Write-Host "Opening Claude report..."
Write-Host ""

notepad $outFile