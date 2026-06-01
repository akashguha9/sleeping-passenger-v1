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
@pytest.mark.parametrize("path", [MAIN_PS1, LIB_PS1, SANITIZER_PS1])
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
