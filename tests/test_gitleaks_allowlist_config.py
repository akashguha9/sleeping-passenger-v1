"""Regression guard for the gitleaks secret-scanning config.

Root cause (scheduled dep-audit #42): gitleaks scans full history and flagged
16 `generic-api-key` matches that are intentional synthetic / redacted
placeholders in test fixtures. The fix suppresses ONLY those exact findings, by
fingerprint, in `.gitleaksignore`, while `.gitleaks.toml` keeps the full default
ruleset active (`useDefault = true`).

These tests lock that scope so a future change cannot silently broaden the
allowlist into "ignore secret scanning":

- `.gitleaks.toml` exists, extends the default ruleset, defines no custom rules,
  and contains no broad/global allowlist that would disable generic-api-key.
- `.gitleaksignore` exists, every entry is a well-formed fingerprint, scoped to
  `tests/` paths only (never production code), for the generic-api-key rule.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TOML = _REPO_ROOT / ".gitleaks.toml"
_IGNORE = _REPO_ROOT / ".gitleaksignore"

# A fingerprint line: <40-hex-commit>:<path>:<rule-id>:<line-number>
_FINGERPRINT = re.compile(r"^(?P<commit>[0-9a-f]{40}):(?P<path>[^:]+):(?P<rule>[a-z0-9-]+):(?P<line>\d+)$")

# Paths that must NEVER appear in the allowlist (production / runtime surface).
_FORBIDDEN_PATH_PREFIXES = ("scripts/", "src/", "frontend/", "api/", "data/", "runtime/")


def _ignore_fingerprints() -> list[str]:
    lines = _IGNORE.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]


# ---------------------------------------------------------------------------
# .gitleaks.toml — keep the default ruleset, add no global weakening
# ---------------------------------------------------------------------------


def test_gitleaks_toml_exists():
    assert _TOML.is_file(), ".gitleaks.toml must exist at the repo root"


def test_toml_extends_default_ruleset():
    cfg = _load_toml()
    assert cfg.get("extend", {}).get("useDefault") is True, (
        "config must `extend.useDefault = true` so generic-api-key and every "
        "other default rule stay active everywhere"
    )


def test_toml_defines_no_custom_rules():
    # We must not redefine/replace rules (that could weaken generic-api-key).
    cfg = _load_toml()
    assert "rules" not in cfg, ".gitleaks.toml must not define [[rules]] (no rule weakening)"


def test_toml_has_no_broad_allowlist():
    cfg = _load_toml()
    # Neither the singular [allowlist] nor the [[allowlists]] array form should
    # be present — suppression is via per-finding fingerprints, not regex/path
    # globs that could disable detection broadly.
    assert "allowlist" not in cfg, "no [allowlist] block — use .gitleaksignore fingerprints"
    assert "allowlists" not in cfg, "no [[allowlists]] block — use .gitleaksignore fingerprints"


def test_toml_does_not_disable_generic_api_key():
    text = _TOML.read_text(encoding="utf-8").lower()
    # A bare `.*redacted.*`-style global allowlist is exactly what we forbid.
    assert ".*redacted.*" not in text
    assert "stopwords" not in text  # no global stopword weakening


# ---------------------------------------------------------------------------
# .gitleaksignore — exact, tests-only fingerprints
# ---------------------------------------------------------------------------


def test_gitleaksignore_exists():
    assert _IGNORE.is_file(), ".gitleaksignore must exist at the repo root"


def test_every_entry_is_a_wellformed_fingerprint():
    bad = [fp for fp in _ignore_fingerprints() if not _FINGERPRINT.match(fp)]
    assert not bad, f"non-fingerprint lines in .gitleaksignore: {bad}"


def test_all_fingerprints_are_tests_only():
    offenders = []
    for fp in _ignore_fingerprints():
        path = _FINGERPRINT.match(fp).group("path")
        if not path.startswith("tests/"):
            offenders.append(path)
        if path.startswith(_FORBIDDEN_PATH_PREFIXES):
            offenders.append(path)
    assert not offenders, f"allowlist must be limited to tests/ — found: {offenders}"


def test_fingerprints_are_generic_api_key_only():
    # The #42 failure was generic-api-key; we do not silence other rule classes.
    rules = {_FINGERPRINT.match(fp).group("rule") for fp in _ignore_fingerprints()}
    assert rules == {"generic-api-key"}, f"unexpected rule ids allowlisted: {rules}"


def test_no_broad_glob_or_regex_in_ignore():
    # .gitleaksignore is fingerprints only; reject wildcards that would widen scope.
    for fp in _ignore_fingerprints():
        assert "*" not in fp and ".*" not in fp, f"wildcard in fingerprint: {fp}"


def test_expected_false_positive_count():
    # 16 findings from dep-audit #42 + 3 of the identical synthetic-fixture
    # class surfaced by the full-history scan on this branch. Pinned so the
    # allowlist cannot grow silently — a change to this number forces review.
    assert len(_ignore_fingerprints()) == 19


def _load_toml() -> dict:
    try:
        import tomllib  # py3.11+
    except ModuleNotFoundError:  # pragma: no cover
        pytest.skip("tomllib unavailable")
    return tomllib.loads(_TOML.read_text(encoding="utf-8"))
