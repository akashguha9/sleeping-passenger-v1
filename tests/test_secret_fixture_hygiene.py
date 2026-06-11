"""Pytest wrapper for scripts/secret_fixture_lint.py (scanner-bait guard).

Keeps the secret-fixture hygiene rule (SECURITY.md) enforced from inside
the normal test run, so a coding pass that reintroduces gitleaks bait
fails `pytest tests` long before CI's secret scan sees it.

This file is allow-listed in the lint because it must spell out the very
patterns it forbids; every probe below is assembled at runtime via
tests/helpers/scanner_probes.py and is synthetic.
"""
from __future__ import annotations

from scripts import secret_fixture_lint as lint
from tests.helpers import scanner_probes as probes


def test_secret_fixture_hygiene_blocks_scanner_bait():
    """The lint must flag the exact fixture shapes that broke CI before."""
    redacted = probes.assemble("RED", "ACTED")
    baits = [
        # tests/test_evidence_production_wiring.py:157 (original failure)
        'claim="' + probes.api_key_assignment() + ' leaked into claim"',
        # the REDACTED-as-value idioms from the incident report
        probes.KW_API_KEY + "=" + redacted,
        '"EDINET_' + probes.KW_API_KEY.upper() + '", "' + redacted + '"',
        probes.assemble("TOK", "EN") + '_HASH_RE_HEX64 = "' + redacted + '"',
        probes.assemble("sec", "ret") + ' = "' + redacted + '"',
        probes.assemble("pass", "word") + ' = "' + redacted + '"',
        # realistic-looking fake tokens
        probes.sk_style_token("ABCDEFGHIJKL1234567890"),
        probes.xai_style_token("abcdef1234567890"),
        probes.assemble("gh", "p_") + "A" * 36,
        probes.assemble("AK", "IA") + "IOSFODNN7EXAMPLE",
    ]
    for bait in baits:
        assert lint.scan_text(bait, "synthetic.py"), f"lint missed: {bait!r}"


def test_safe_sentinels_are_allowed():
    for sentinel in sorted(lint.ALLOWED_SENTINELS):
        line = probes.KW_API_KEY.upper() + ' = "' + sentinel + '"'
        assert lint.scan_text(line, "synthetic.py") == []


def test_ordinary_code_is_not_flagged():
    samples = [
        "token = os.environ.get(\"MVP_API_TOKEN\", \"\")",
        "score_key=\"data_model_persistence_v2_score\",",
        "API_KEY_ENV_NAMES = (\"NEWS_API_KEY\", \"XAI_API_KEY\")",
        "cleaned = cleaned.replace(api_key, \"<redacted>\")",
        "# set MVP_ALLOW_UNAUTH=1 to override on loopback",
    ]
    for line in samples:
        assert lint.scan_text(line, "synthetic.py") == [], line


def test_repo_is_clean_of_scanner_bait():
    """The whole tracked tree stays free of secret-shaped fixtures."""
    assert lint.scan_repo() == []


def test_lint_cli_reports_pass(capsys):
    assert lint.main() == 0
    assert "PASS" in capsys.readouterr().out
