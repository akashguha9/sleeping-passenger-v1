"""Tests — five-model synthesis PowerShell workflow robustness + secret safety.

Cover the patch to ``scripts/run_five_model_synthesis.ps1`` + helper scripts
(``secret_scan_lib.ps1`` / ``sanitize_generated_context.ps1``):

  * all three PowerShell scripts parse cleanly;
  * the frontier-resolver fallback-reason line is present (and parses);
  * the strict secret detector flags fake keys (incl. a SINGLE lone key) and
    reports file/line/pattern class but NEVER the matched secret value;
  * a realistic news-URL slug does NOT false-positive (the real abort cause);
  * the sanitizer redacts fake keys in generated folders, makes a ``.bak``,
    exits 0, and does NOT touch ``.env`` or source-code file extensions.

PowerShell tests skip cleanly where no ``powershell``/``pwsh`` exists.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
MAIN_PS1 = SCRIPTS / "run_five_model_synthesis.ps1"
LIB_PS1 = SCRIPTS / "secret_scan_lib.ps1"
SANITIZER_PS1 = SCRIPTS / "sanitize_generated_context.ps1"
PROVIDER_LIB_PS1 = SCRIPTS / "provider_lib.ps1"

_PWSH = shutil.which("pwsh") or shutil.which("powershell")
needs_powershell = pytest.mark.skipif(_PWSH is None, reason="PowerShell not available on this host")


def _run_ps(script_body: str) -> subprocess.CompletedProcess:
    assert _PWSH is not None
    return subprocess.run(
        [_PWSH, "-NoProfile", "-NonInteractive", "-Command", script_body],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )


def _parse_check(path: Path) -> subprocess.CompletedProcess:
    body = (
        "$errs=$null; $toks=$null; "
        f"[void][System.Management.Automation.Language.Parser]::ParseFile('{path}',[ref]$toks,[ref]$errs); "
        "if ($errs) { foreach ($e in $errs) { Write-Output (\"ERR line \" + "
        "$e.Extent.StartLineNumber + ': ' + $e.Message) } } else { Write-Output 'PARSE_OK' }"
    )
    return _run_ps(body)


def test_helper_scripts_exist() -> None:
    assert MAIN_PS1.is_file()
    assert LIB_PS1.is_file()
    assert SANITIZER_PS1.is_file()


def test_fallback_reason_line_present_and_well_formed() -> None:
    text = MAIN_PS1.read_text(encoding="utf-8", errors="ignore")
    assert "$reason = $resolved[$reasonKey]" in text
    assert "fallback in effect - reason:" in text
    assert "ABORTED: prompt/context contains API-key-like text." in (
        MAIN_PS1.read_text(encoding="utf-8", errors="ignore")
        + LIB_PS1.read_text(encoding="utf-8", errors="ignore")
    )


def test_repo_root_guard_present() -> None:
    text = MAIN_PS1.read_text(encoding="utf-8", errors="ignore")
    assert 'Resolve-Path (Join-Path $PSScriptRoot "..")' in text
    assert "Set-Location $RepoRoot" in text
    assert "Run from" in text and "full script path" in text


def test_advisory_only_invariants_preserved() -> None:
    text = MAIN_PS1.read_text(encoding="utf-8", errors="ignore").lower()
    for forbidden in ("place_order", "submit_order", "broker_execute", "place-order"):
        assert forbidden not in text


@needs_powershell
@pytest.mark.parametrize("path", [MAIN_PS1, LIB_PS1, SANITIZER_PS1, PROVIDER_LIB_PS1])
def test_powershell_parses_clean(path: Path) -> None:
    res = _parse_check(path)
    assert "PARSE_OK" in res.stdout, f"parse errors for {path.name}:\n{res.stdout}\n{res.stderr}"


@needs_powershell
def test_detector_reports_class_and_line_but_never_the_secret() -> None:
    fake_secret = "sk-ABCDEFGHIJKLMNOPQRSTUVWX1234567890abcd"
    body = (
        ". .\\scripts\\secret_scan_lib.ps1; "
        f"$t = 'OPENAI={fake_secret}'; "
        "$h = @(Find-SecretMatchLines -Text $t -Source 'unit.txt'); "
        "foreach ($x in $h) { Write-Output (\"HIT \" + $x.Source + ':' + $x.Line + ' ' + $x.Class) }"
    )
    res = _run_ps(body)
    assert "HIT unit.txt:1 OPENAI_STYLE_KEY" in res.stdout
    assert fake_secret not in res.stdout


@needs_powershell
def test_detector_single_lone_key_is_counted() -> None:
    fake_secret = "sk-ABCDEFGHIJKLMNOPQRSTUVWX1234567890abcd"
    body = (
        ". .\\scripts\\secret_scan_lib.ps1; "
        f"$t = 'only one key here: {fake_secret}'; "
        "$h = Find-SecretMatchLines -Text $t -Source 'one.txt'; "
        "Write-Output ('COUNT=' + $h.Count)"
    )
    res = _run_ps(body)
    assert "COUNT=1" in res.stdout, res.stdout


@needs_powershell
def test_detector_flags_fake_openai_project_key_without_leaking() -> None:
    fake_secret = "sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
    body = (
        ". .\\scripts\\secret_scan_lib.ps1; "
        f"$t = 'OPENAI_PROJECT={fake_secret}'; "
        "$h = @(Find-SecretMatchLines -Text $t -Source 'proj.txt'); "
        "foreach ($x in $h) { Write-Output (\"HIT \" + $x.Source + ':' + $x.Line + ' ' + $x.Class) }"
    )
    res = _run_ps(body)
    assert "HIT proj.txt:1 OPENAI_PROJECT_KEY" in res.stdout, res.stdout
    assert fake_secret not in res.stdout


@needs_powershell
def test_detector_flags_fake_anthropic_key_without_leaking() -> None:
    fake_secret = "sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
    body = (
        ". .\\scripts\\secret_scan_lib.ps1; "
        f"$t = 'ANTHROPIC_API_KEY={fake_secret}'; "
        "$h = @(Find-SecretMatchLines -Text $t -Source 'ant.txt'); "
        "foreach ($x in $h) { Write-Output (\"HIT \" + $x.Source + ':' + $x.Line + ' ' + $x.Class) }"
    )
    res = _run_ps(body)
    assert "HIT ant.txt:1 ANTHROPIC_STYLE_KEY" in res.stdout, res.stdout
    assert fake_secret not in res.stdout


@needs_powershell
def test_detector_flags_fake_xai_key_without_leaking() -> None:
    fake_secret = "xai-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
    body = (
        ". .\\scripts\\secret_scan_lib.ps1; "
        f"$t = 'XAI_API_KEY={fake_secret}'; "
        "$h = @(Find-SecretMatchLines -Text $t -Source 'xai.txt'); "
        "foreach ($x in $h) { Write-Output (\"HIT \" + $x.Source + ':' + $x.Line + ' ' + $x.Class) }"
    )
    res = _run_ps(body)
    assert "HIT xai.txt:1 XAI_STYLE_KEY" in res.stdout, res.stdout
    assert fake_secret not in res.stdout


@needs_powershell
def test_detector_does_not_false_positive_on_news_slug() -> None:
    slug_line = '{"url": "https://example.com/biggest-ipo-elon-musk-is-going-to-get-even-bigger/"}'
    body = (
        ". .\\scripts\\secret_scan_lib.ps1; "
        f"$t = '{slug_line}'; "
        "$h = @(Find-SecretMatchLines -Text $t -Source 'slug.json'); "
        "Write-Output ('COUNT=' + $h.Count)"
    )
    res = _run_ps(body)
    assert "COUNT=0" in res.stdout, res.stdout


@needs_powershell
def test_real_news_payload_does_not_false_positive() -> None:
    news = REPO_ROOT / "data" / "daily_payload" / "today_news_events.json"
    if not news.is_file():
        pytest.skip("today_news_events.json not present")
    body = (
        ". .\\scripts\\secret_scan_lib.ps1; "
        "$t = Get-Content '.\\data\\daily_payload\\today_news_events.json' -Raw; "
        "$h = @(Find-SecretMatchLines -Text $t -Source 'news'); "
        "Write-Output ('COUNT=' + $h.Count)"
    )
    res = _run_ps(body)
    assert "COUNT=0" in res.stdout, res.stdout


@needs_powershell
def test_assert_throws_on_single_key_without_leaking_secret() -> None:
    fake_secret = "xai-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
    body = (
        ". .\\scripts\\secret_scan_lib.ps1; "
        f"$t = 'XAI_API_KEY={fake_secret}'; "
        "try { Assert-NoSecretText -Text $t -Source 'env-dump'; Write-Output 'NO_THROW' } "
        "catch { Write-Output ('THREW::' + $_.Exception.Message) }"
    )
    res = _run_ps(body)
    assert "THREW::" in res.stdout, res.stdout
    assert "XAI_STYLE_KEY" in res.stdout
    assert fake_secret not in res.stdout


@needs_powershell
def test_sanitizer_redacts_generated_skips_env_and_source() -> None:
    sandbox = REPO_ROOT / "data" / "_sanitizer_selftest_tmp"
    if sandbox.exists():
        shutil.rmtree(sandbox)
    sandbox.mkdir(parents=True)
    fake = "sk-ABCDEFGHIJKLMNOPQRSTUVWX1234567890abcd"
    json_file = sandbox / "generated_payload.json"
    env_file = sandbox / ".env"
    py_file = sandbox / "should_not_touch.py"
    json_file.write_text('{"leak": "' + fake + '"}\n', encoding="utf-8")
    env_file.write_text("OPENAI_API_KEY=" + fake + "\n", encoding="utf-8")
    py_file.write_text('KEY = "' + fake + '"\n', encoding="utf-8")
    try:
        res = _run_ps(".\\scripts\\sanitize_generated_context.ps1 -Apply")
        assert res.returncode == 0, res.stdout + res.stderr

        redacted = json_file.read_text(encoding="utf-8")
        assert "[REDACTED_API_KEY]" in redacted
        assert fake not in redacted
        bak = json_file.with_name(json_file.name + ".bak")
        assert bak.is_file()
        assert fake in bak.read_text(encoding="utf-8")

        assert env_file.read_text(encoding="utf-8").strip().endswith(fake)
        assert not env_file.with_name(env_file.name + ".bak").exists()

        assert fake in py_file.read_text(encoding="utf-8")
        assert not py_file.with_name(py_file.name + ".bak").exists()

        assert fake not in res.stdout
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


@needs_powershell
def test_sanitizer_dryrun_reports_but_does_not_modify() -> None:
    """Dry-run must flag the leak (and exit 0) but leave the file untouched and
    create no .bak — never printing the matched secret value."""
    sandbox = REPO_ROOT / "data" / "_sanitizer_dryrun_selftest_tmp"
    if sandbox.exists():
        shutil.rmtree(sandbox)
    sandbox.mkdir(parents=True)
    fake = "sk-ABCDEFGHIJKLMNOPQRSTUVWX1234567890abcd"
    json_file = sandbox / "generated_payload.json"
    original = '{"leak": "' + fake + '"}\n'
    json_file.write_text(original, encoding="utf-8")
    try:
        res = _run_ps(".\\scripts\\sanitize_generated_context.ps1 -DryRun")
        assert res.returncode == 0, res.stdout + res.stderr
        assert "DRY-RUN" in res.stdout
        assert "WOULD REDACT" in res.stdout
        # File is unchanged and no backup was written.
        assert json_file.read_text(encoding="utf-8") == original
        assert fake in json_file.read_text(encoding="utf-8")
        assert not json_file.with_name(json_file.name + ".bak").exists()
        # The matched secret value is never printed.
        assert fake not in res.stdout
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


# ============================================================
# Provider-safe orchestration (TASKS 1-6) — pure helpers in provider_lib.ps1
# ============================================================


def test_provider_lib_exists() -> None:
    assert PROVIDER_LIB_PS1.is_file()


def test_orchestration_env_vars_have_safe_defaults() -> None:
    """The four orchestration controls exist with the documented safe defaults."""
    text = MAIN_PS1.read_text(encoding="utf-8", errors="ignore")
    # default true: failures tolerated unless explicitly 'false'
    assert "$AllowProviderFailures = ($env:SP_ALLOW_PROVIDER_FAILURES -ne 'false')" in text
    # default true: reuse cached outputs unless explicitly 'false'
    assert "$ReuseProviderOutputs  = ($env:SP_REUSE_PROVIDER_OUTPUTS -ne 'false')" in text
    # default false: only force rerun when explicitly 'true'
    assert "$ForceProviderRerun    = ($env:SP_FORCE_PROVIDER_RERUN -eq 'true')" in text
    # default 4 minimum providers
    assert "$MinSynthesisProviders = 4" in text


def test_safe_provider_runner_and_cache_path_present() -> None:
    text = MAIN_PS1.read_text(encoding="utf-8", errors="ignore")
    assert "function Invoke-SafeProvider" in text
    # deterministic per-run cache under runtime/five_model_synthesis/<RUN_DATE>/
    assert "runtime\\five_model_synthesis\\{0}" in text
    # resume message must be printed verbatim
    assert "Reusing cached {0} output from {1}" in text
    # all five providers go through the safe runner
    for key in ("gpt", "claude", "gemini", "grok", "mistral"):
        assert f'-Key "{key}"' in text


@needs_powershell
def test_claude_opus48_body_omits_sampling_params() -> None:
    """TASK 2/7.1 — claude-opus-4-8 request body must NOT contain
    temperature/top_p/top_k; older Claude models keep temperature."""
    body = (
        ". .\\scripts\\provider_lib.ps1; "
        "$b = Get-ClaudeRequestBody -PromptText 'hi' -ModelName 'claude-opus-4-8'; "
        "$j = $b | ConvertTo-Json -Depth 10 -Compress; "
        "Write-Output ('OPUS::' + $j); "
        "$b2 = Get-ClaudeRequestBody -PromptText 'hi' -ModelName 'claude-sonnet-4-6'; "
        "$j2 = $b2 | ConvertTo-Json -Depth 10 -Compress; "
        "Write-Output ('SONNET_HAS_TEMP::' + ($j2 -match 'temperature'))"
    )
    res = _run_ps(body)
    opus_line = next(ln for ln in res.stdout.splitlines() if ln.startswith("OPUS::"))
    assert "temperature" not in opus_line, opus_line
    assert "top_p" not in opus_line, opus_line
    assert "top_k" not in opus_line, opus_line
    # required fields are still present
    assert "max_tokens" in opus_line
    assert "messages" in opus_line
    assert "SONNET_HAS_TEMP::True" in res.stdout, res.stdout


@needs_powershell
def test_gemini_resolver_normalizes_pro_to_preview() -> None:
    """TASK 3/7.2 — gemini-3.1-pro -> gemini-3.1-pro-preview; other ids pass through."""
    body = (
        ". .\\scripts\\provider_lib.ps1; "
        "Write-Output ('NORM::' + (Resolve-GeminiModel -ModelName 'gemini-3.1-pro')); "
        "Write-Output ('PASS::' + (Resolve-GeminiModel -ModelName 'gemini-2.5-flash'))"
    )
    res = _run_ps(body)
    assert "NORM::gemini-3.1-pro-preview" in res.stdout, res.stdout
    assert "PASS::gemini-2.5-flash" in res.stdout, res.stdout


@needs_powershell
def test_mistral_retry_schedule_is_15_45_90() -> None:
    """TASK 4/7.3 — the 429 retry backoff schedule exists (15s, 45s, 90s)."""
    body = (
        ". .\\scripts\\provider_lib.ps1; "
        "Write-Output ('DELAYS::' + ((Get-MistralRetryDelaysSeconds) -join ','))"
    )
    res = _run_ps(body)
    assert "DELAYS::15,45,90" in res.stdout, res.stdout
    # and the live caller wires the retry message + re-throw on exhaustion
    main = MAIN_PS1.read_text(encoding="utf-8", errors="ignore")
    assert "Mistral rate limited; retrying in {0} seconds..." in main


@needs_powershell
def test_safe_provider_error_redacts_secret_and_extracts_fields() -> None:
    """TASK 5 — Get-SafeProviderError extracts status/type/code/message from a
    Mistral-style 429 body and NEVER leaks an API-key-like substring."""
    fake = "sk-ABCDEFGHIJKLMNOPQRSTUVWX1234567890abcd"
    body = (
        ". .\\scripts\\provider_lib.ps1; "
        "$payload = '{\"object\":\"error\",\"message\":\"Rate limit exceeded key "
        + fake
        + "\",\"type\":\"rate_limited\",\"code\":\"1300\",\"raw_status_code\":429}'; "
        "$exc = New-Object System.Exception('boom'); "
        "$er = New-Object System.Management.Automation.ErrorRecord("
        "$exc,'id',[System.Management.Automation.ErrorCategory]::NotSpecified,$null); "
        "$er.ErrorDetails = New-Object System.Management.Automation.ErrorDetails($payload); "
        "$s = Get-SafeProviderError -ErrorRecord $er -Provider 'Mistral' -Model 'm'; "
        "Write-Output ('STATUS::' + $s.Status); "
        "Write-Output ('TYPE::' + $s.Type); "
        "Write-Output ('CODE::' + $s.Code); "
        "Write-Output ('MSG::' + $s.Message); "
        "Write-Output ('RAW::' + $s.RawBodyRedacted)"
    )
    res = _run_ps(body)
    assert "STATUS::429" in res.stdout, res.stdout
    assert "TYPE::rate_limited" in res.stdout, res.stdout
    assert "CODE::1300" in res.stdout, res.stdout
    assert "[REDACTED_API_KEY]" in res.stdout, res.stdout
    assert fake not in res.stdout, "Get-SafeProviderError leaked the API key!"


@needs_powershell
def test_provider_unavailable_placeholder_has_no_api_key() -> None:
    """TASK 6/7.4 — the unavailable-provider placeholder built from a sanitized
    reason contains no API-key-like text."""
    fake = "sk-ABCDEFGHIJKLMNOPQRSTUVWX1234567890abcd"
    body = (
        ". .\\scripts\\provider_lib.ps1; "
        # reason flows through Get-SafeProviderError redaction first
        "$payload = '{\"error\":{\"type\":\"bad\",\"message\":\"leak " + fake + "\"}}'; "
        "$exc = New-Object System.Exception('boom'); "
        "$er = New-Object System.Management.Automation.ErrorRecord("
        "$exc,'id',[System.Management.Automation.ErrorCategory]::NotSpecified,$null); "
        "$er.ErrorDetails = New-Object System.Management.Automation.ErrorDetails($payload); "
        "$s = Get-SafeProviderError -ErrorRecord $er -Provider 'Claude' -Model 'm'; "
        "$ph = Get-ProviderUnavailablePlaceholder -Provider 'Claude' -Reason $s.Message; "
        "Write-Output ('PH::' + $ph)"
    )
    res = _run_ps(body)
    assert "PROVIDER_UNAVAILABLE: Claude unavailable due" in res.stdout, res.stdout
    assert fake not in res.stdout, "placeholder leaked the API key!"


@needs_powershell
def test_provider_availability_section_lists_available_and_unavailable() -> None:
    """TASK 6 — the synthesis 'Provider Availability' section reflects each
    provider's state + reason."""
    body = (
        ". .\\scripts\\provider_lib.ps1; "
        "$ps = @("
        "[pscustomobject]@{Name='GPT';Available=$true;Reason=''},"
        "[pscustomobject]@{Name='Mistral';Available=$false;Reason='status=429 type=rate_limited'}"
        "); "
        "Write-Output (Get-ProviderAvailabilitySection -Providers $ps)"
    )
    res = _run_ps(body)
    assert "GPT: available" in res.stdout, res.stdout
    assert "Mistral: unavailable - status=429 type=rate_limited" in res.stdout, res.stdout


@needs_powershell
def test_safe_provider_reuses_cache_unless_force_rerun() -> None:
    """TASK 1/7.5 — Invoke-SafeProvider reuses a cached, secret-clean output and
    does NOT call the provider again; with -ForceRerun it ignores the cache.
    The runner is exercised in isolation by dot-sourcing only the two pure libs
    plus the function definition extracted from the main script (no network)."""
    sandbox = REPO_ROOT / "data" / "_provider_cache_selftest_tmp"
    if sandbox.exists():
        shutil.rmtree(sandbox)
    sandbox.mkdir(parents=True)
    cache_dir = sandbox / "cache"
    cache_dir.mkdir()
    (cache_dir / "claude.txt").write_text("CACHED ADVISORY TEXT — no secrets here.\n", encoding="utf-8")
    # Extract the Invoke-SafeProvider function body from the main script so we can
    # exercise it without running the whole (network/key-gated) workflow.
    main_src = MAIN_PS1.read_text(encoding="utf-8", errors="ignore")
    start = main_src.index("function Invoke-SafeProvider")
    # function ends at the start of the next top-level comment banner
    end = main_src.index("# ============================================================\n# BUILD FULL PROMPTS", start)
    func_src = main_src[start:end]
    func_file = sandbox / "_runner.ps1"
    func_file.write_text(func_src, encoding="utf-8")
    try:
        cache_posix = str(cache_dir).replace("\\", "\\\\")
        runner_posix = str(func_file).replace("\\", "\\\\")
        body = (
            ". .\\scripts\\secret_scan_lib.ps1; "
            ". .\\scripts\\provider_lib.ps1; "
            f". '{runner_posix}'; "
            "$called = $false; "
            # Reuse path: cache present, not forced -> provider NOT called
            f"$r = Invoke-SafeProvider -Name 'Claude' -Key 'claude' -Model 'm' -CacheDir '{cache_posix}' "
            "-AllowFailures $true -ReuseOutputs $true -ForceRerun $false "
            "-Call { $script:called = $true; 'LIVE' }; "
            "Write-Output ('REUSE_FROMCACHE::' + $r.FromCache); "
            "Write-Output ('REUSE_CALLED::' + $called); "
            # Force path: ignore cache -> provider IS called
            "$called2 = $false; "
            f"$r2 = Invoke-SafeProvider -Name 'Claude' -Key 'claude' -Model 'm' -CacheDir '{cache_posix}' "
            "-AllowFailures $true -ReuseOutputs $true -ForceRerun $true "
            "-Call { $script:called2 = $true; 'LIVE OUTPUT NO SECRET' }; "
            "Write-Output ('FORCE_CALLED::' + $called2); "
            "Write-Output ('FORCE_FROMCACHE::' + $r2.FromCache)"
        )
        res = _run_ps(body)
        assert "REUSE_FROMCACHE::True" in res.stdout, res.stdout
        assert "REUSE_CALLED::False" in res.stdout, res.stdout
        assert "FORCE_CALLED::True" in res.stdout, res.stdout
        assert "FORCE_FROMCACHE::False" in res.stdout, res.stdout
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


@needs_powershell
def test_safe_provider_failure_is_tolerated_and_marks_unavailable() -> None:
    """TASK 1/6/7.6 — a provider whose call throws is marked unavailable (not
    fatal) when AllowFailures=$true, with a sanitized reason and no secret."""
    sandbox = REPO_ROOT / "data" / "_provider_fail_selftest_tmp"
    if sandbox.exists():
        shutil.rmtree(sandbox)
    sandbox.mkdir(parents=True)
    cache_dir = sandbox / "cache"
    cache_dir.mkdir()
    main_src = MAIN_PS1.read_text(encoding="utf-8", errors="ignore")
    start = main_src.index("function Invoke-SafeProvider")
    end = main_src.index("# ============================================================\n# BUILD FULL PROMPTS", start)
    func_file = sandbox / "_runner.ps1"
    func_file.write_text(main_src[start:end], encoding="utf-8")
    try:
        cache_posix = str(cache_dir).replace("\\", "\\\\")
        runner_posix = str(func_file).replace("\\", "\\\\")
        body = (
            ". .\\scripts\\secret_scan_lib.ps1; "
            ". .\\scripts\\provider_lib.ps1; "
            f". '{runner_posix}'; "
            f"$r = Invoke-SafeProvider -Name 'Mistral' -Key 'mistral' -Model 'm' -CacheDir '{cache_posix}' "
            "-AllowFailures $true -ReuseOutputs $false -ForceRerun $false "
            "-Call { throw 'simulated provider failure' }; "
            "Write-Output ('AVAILABLE::' + $r.Available); "
            "Write-Output ('REASON::' + $r.Reason)"
        )
        res = _run_ps(body)
        assert "AVAILABLE::False" in res.stdout, res.stdout
        assert "REASON::" in res.stdout, res.stdout
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def test_min_providers_abort_message_present() -> None:
    """TASK 6/7.7 — the script aborts safely when fewer than the minimum
    providers succeed."""
    text = MAIN_PS1.read_text(encoding="utf-8", errors="ignore")
    assert "ABORTED: fewer than {0} providers succeeded; no robust synthesis possible." in text
    assert "$availableCount -lt $MinSynthesisProviders" in text


def test_provider_availability_section_wired_into_synthesis_prompt() -> None:
    """TASK 6 — the synthesis prompt embeds the Provider Availability block and
    the placeholder convention."""
    text = MAIN_PS1.read_text(encoding="utf-8", errors="ignore")
    assert "PROVIDER AVAILABILITY (read before synthesizing)" in text
    assert "$providerAvailabilitySection" in text
    assert "Get-ProviderUnavailablePlaceholder" in text


def test_secret_scan_still_runs_on_prompts_and_outputs() -> None:
    """TASK 7.8 — secret scanning is NOT disabled: prompts/context are scanned
    pre-flight, each provider output is scanned in the runner, and the final
    synthesis prompt + output are still asserted."""
    text = MAIN_PS1.read_text(encoding="utf-8", errors="ignore")
    # pre-flight prompt/context scan loop still present
    assert "Get-FirstSecretMatch -Text ([string]$contextSources[$srcName])" in text
    # provider output scanned inside the runner before save
    assert 'Get-FirstSecretMatch -Text $text -Source ("{0} analyst output" -f $Name)' in text
    # final synthesis prompt + output still asserted
    assert 'Assert-NoSecretText -Text $synthesisPrompt -Source "final synthesis prompt"' in text
    assert "Assert-NoSecretText -Text $synthesisResult" in text


def test_advisory_human_execution_invariants_intact() -> None:
    """TASK 7.9 — advisory-only / human-execution-required invariants remain."""
    text = MAIN_PS1.read_text(encoding="utf-8", errors="ignore")
    assert "advisory only" in text.lower()
    assert "Final buy/hold/exit/reconciliation decisions are made manually by the human operator only." in text
    assert "No broker action" in text
    # no execution/order-placement surface was introduced
    low = text.lower()
    for forbidden in ("place_order", "submit_order", "broker_execute", "place-order", "execute_trade"):
        assert forbidden not in low
