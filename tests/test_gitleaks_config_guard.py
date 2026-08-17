"""Guard tests for .gitleaks.toml (secret-scan false-positive config).

Two verified generic-api-key false positives are allowlisted there:
the ``"key_risk"`` prose field in dated discovery-report JSON, and the
historical prompt cache-routing literal in scripts/run_grok_daily.ps1.

These tests pin the safety properties of that config:
  * the default gitleaks ruleset stays fully enabled (nothing disabled);
  * every allowlist targets only generic-api-key, requires path AND
    line-content to match, and stays scoped to the known-safe patterns;
  * credential-shaped fixtures (synthetic, obviously fake) are NOT
    covered by any allowlist, so a real leak still fails the scan;
  * the CI action pin has left the deprecated Node 20 release behind.

Stdlib only (tomllib requires Python >= 3.11, matching CI's 3.13).
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_PATH = _REPO_ROOT / ".gitleaks.toml"
_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "dep_audit.yml"


@pytest.fixture(scope="module")
def config() -> dict:
    return tomllib.loads(_CONFIG_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def allowlists(config: dict) -> list[dict]:
    return config["rules"][0]["allowlists"]


# ---------------------------------------------------------------------------
# Detection sensitivity is preserved
# ---------------------------------------------------------------------------


def test_default_ruleset_extended_not_replaced(config: dict):
    assert config["extend"]["useDefault"] is True
    # No default rules disabled, no global [allowlist] table (its path /
    # regex criteria are OR'd — too broad for our purposes).
    assert "disabledRules" not in config["extend"]
    assert "allowlist" not in config
    assert "allowlists" not in config
    # Exactly one rule extension: generic-api-key, extended BY ID ONLY so
    # every detection attribute (regex, entropy, keywords) is inherited
    # unchanged from the default ruleset. Any other key here would
    # override — and potentially weaken — the default rule.
    rules = config["rules"]
    assert len(rules) == 1
    assert rules[0]["id"] == "generic-api-key"
    assert set(rules[0]) == {"id", "allowlists"}


def test_every_allowlist_is_narrow(allowlists: list[dict]):
    assert len(allowlists) == 2
    for entry in allowlists:
        # Path AND line content must both match for an exemption.
        assert entry["condition"] == "AND"
        assert entry["regexTarget"] == "line"
        assert entry["paths"], "allowlist without a path scope is too broad"
        assert entry["regexes"], "allowlist without a content regex is too broad"


def _path_allowed(allowlists: list[dict], path: str) -> bool:
    return any(
        re.search(p, path) for entry in allowlists for p in entry["paths"]
    )


def test_path_scope_covers_only_known_files(allowlists: list[dict]):
    for known in (
        "reports/daily_stock_discovery_2026-07-13.json",
        "reports/mvp_global_equity_discovery_2026-07-06.json",
        "scripts/run_grok_daily.ps1",
    ):
        assert _path_allowed(allowlists, known)
    for other in (
        "reports/other_report.json",
        "reports/github_owner_settings_manual_checklist.md",
        "scripts/run_claude_daily.ps1",
        "config/thresholds.yaml",
        "frontend/package.json",
        "moltbook/open_positions.json",
    ):
        assert not _path_allowed(allowlists, other), other


# ---------------------------------------------------------------------------
# The known-benign lines ARE covered (false-positive regression)
# ---------------------------------------------------------------------------


def _line_allowed(allowlists: list[dict], line: str) -> bool:
    return any(
        re.search(rx, line) for entry in allowlists for rx in entry["regexes"]
    )


# Every scanner-shaped fixture below is assembled at runtime from pieces
# split so that no single SOURCE line of this file contains a
# keyword+delimiter+value pattern — otherwise this test file would itself
# trip the secret scan it is guarding. The assembled strings are
# byte-identical to the lines being tested.
def _assemble(*parts: str) -> str:
    return "".join(parts)


_CACHE_LABEL = _assemble('"sleeping-passenger', "-grok-daily-v1", '"')


def test_key_risk_prose_lines_are_allowlisted(allowlists: list[dict]):
    # Actual flagged lines from the two reports (harmless research prose).
    benign = (
        _assemble(
            '      "key_', 'risk"', ": ",
            '"Airbus/Boeing production-rate execution risk,'
            ' titanium/nickel supply-chain constraints",',
        ),
        _assemble(
            '    "key_', 'risk"', ": ",
            '"Political/regulatory approval risk on new export'
            ' pipeline capacity",',
        ),
    )
    for line in benign:
        assert _line_allowed(allowlists, line), line


def test_prompt_cache_label_line_is_allowlisted(allowlists: list[dict]):
    # Historical spelling (in git history) and current spelling.
    for var_suffix in ("Key", "Id"):
        line = _assemble("$promptCache", var_suffix, " = ", _CACHE_LABEL)
        assert _line_allowed(allowlists, line), line


# ---------------------------------------------------------------------------
# Credential-shaped fixtures are NOT covered (sensitivity regression)
# ---------------------------------------------------------------------------


def test_fake_credentials_are_not_allowlisted(allowlists: list[dict]):
    # Synthetic, obviously fake fixtures — never real keys.
    fake_lines = (
        _assemble('"api_', 'key"', ": ", '"sk-FAKE', "FAKEFAKEFAKEFAKEFAKE1234", '"'),
        _assemble("api", "Key", " = ", '"AKIA', "FAKEFAKEFAKEFAKE", '"'),
        _assemble("$promptCache", "Key", " = ", '"xai-FAKE', "FAKEFAKEFAKEFAKEFAKE", '"'),
        _assemble("$api", "Token", " = ", '"ghp_FAKE', "FAKEFAKEFAKEFAKEFAKEFAKEFAKE", '"'),
        _assemble('"sec', 'ret"', ": ", _CACHE_LABEL),
    )
    for line in fake_lines:
        assert not _line_allowed(allowlists, line), line


def test_key_risk_regex_requires_string_value(allowlists: list[dict]):
    # The key_risk exemption covers only a quoted JSON string on that
    # line — a bare token or trailing extra content is not exempt.
    smuggled = _assemble(
        '"key_', 'risk"', ": ", '"x", ',
        '"api_', 'key"', ": ", '"sk-FAKE', "FAKEFAKEFAKE", '"',
    )
    assert not _line_allowed(allowlists, smuggled)


# ---------------------------------------------------------------------------
# .gitleaksignore stays commit-pinned (historical findings only)
# ---------------------------------------------------------------------------


def test_gitleaksignore_entries_are_commit_pinned():
    # A fingerprint without a commit prefix suppresses the finding in the
    # working tree and all future commits — too broad. Require every entry
    # to name the single historical commit it applies to.
    ignore = (_REPO_ROOT / ".gitleaksignore").read_text(encoding="utf-8")
    entry_re = re.compile(r"^[0-9a-f]{40}:[^:]+:[a-z0-9-]+:\d+$")
    entries = [
        line.strip()
        for line in ignore.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert entries, ".gitleaksignore should list the known historical findings"
    for entry in entries:
        assert entry_re.match(entry), f"not commit-pinned: {entry}"


# ---------------------------------------------------------------------------
# CI action pin left the deprecated Node 20 release behind
# ---------------------------------------------------------------------------


def test_gitleaks_action_pin_is_node24_release():
    yml = _WORKFLOW_PATH.read_text(encoding="utf-8")
    pins = re.findall(r"gitleaks/gitleaks-action@([0-9a-f]{40})\s*#\s*(\S+)", yml)
    assert pins, "gitleaks-action must stay SHA-pinned with a version comment"
    for sha, version in pins:
        # ff98106e... is v2.3.9, the Node 20 runtime release.
        assert sha != "ff98106e4c7b2bc287b24eaf42907196329070c7"
        major = int(version.lstrip("v").split(".")[0])
        assert major >= 3, "gitleaks-action must be v3+ (Node 24 runtime)"
