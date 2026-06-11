"""Historical secret ledger: schema, classification logic, fail-closed rules.

These tests exercise the pure classification function so they run in CI
without a gitleaks binary; the actual scan is run locally / via the
manual history-audit workflow.
"""
from __future__ import annotations

import re

from scripts import audit_historical_secret_ledger as hist


def _finding(fp: str, file: str = "tests/x.py", line: int = 1) -> dict:
    return {"Fingerprint": fp, "File": file, "StartLine": line,
            "RuleID": "generic-api-key"}


def _ledger(*fingerprints: str) -> dict:
    return {
        "schema_version": 1,
        "known_findings": [
            {"fingerprint": fp, "classification": "synthetic_fixture"}
            for fp in fingerprints
        ],
    }


# ---------------------------------------------------------------------------
# The committed ledger itself
# ---------------------------------------------------------------------------


def test_committed_ledger_schema_and_classifications():
    ledger = hist.load_ledger()
    assert ledger["schema_version"] == 1
    entries = ledger["known_findings"]
    assert entries, "ledger must document the known historical findings"
    fp_re = re.compile(r"^[0-9a-f]{40}:.+:[\w-]+:\d+$")
    for entry in entries:
        # Fingerprint-specific only — broad suppressions are forbidden.
        assert fp_re.match(entry["fingerprint"]), entry["fingerprint"]
        # Every entry must be an explicitly verified synthetic fixture;
        # a real or unverified secret may never be parked here.
        assert entry["classification"] == "synthetic_fixture", entry
        assert entry["note"].strip(), "every entry needs a verification note"


def test_committed_ledger_fingerprints_are_unique():
    ledger = hist.load_ledger()
    fps = [e["fingerprint"] for e in ledger["known_findings"]]
    assert len(fps) == len(set(fps))


# ---------------------------------------------------------------------------
# Classification rules (pure function)
# ---------------------------------------------------------------------------


def test_known_historical_finding_is_reported_not_failed():
    fp = "a" * 40 + ":tests/x.py:generic-api-key:1"
    out = hist.classify_findings([_finding(fp)], [], _ledger(fp))
    assert out["historical_known_synthetic"] == [fp]
    assert out["historical_unknown"] == []
    assert out["current_tree_findings"] == []


def test_unknown_historical_finding_is_flagged():
    known = "a" * 40 + ":tests/x.py:generic-api-key:1"
    unknown = "b" * 40 + ":scripts/y.py:aws-access-token:9"
    out = hist.classify_findings(
        [_finding(known), _finding(unknown)], [], _ledger(known)
    )
    assert out["historical_unknown"] == [unknown]


def test_current_tree_finding_is_never_suppressed_by_ledger():
    fp = "c" * 40 + ":tests/x.py:generic-api-key:7"
    out = hist.classify_findings([], [_finding(fp, "tests/x.py", 7)], _ledger(fp))
    # In the ledger or not — a finding in HEAD content is always surfaced.
    assert out["current_tree_findings"] == ["tests/x.py:7:generic-api-key"]


def test_tree_findings_never_echo_matched_content():
    tree = [{"Fingerprint": "x", "File": "f.py", "StartLine": 3,
             "RuleID": "generic-api-key", "Secret": "SHOULD_NOT_APPEAR",
             "Match": "SHOULD_NOT_APPEAR"}]
    out = hist.classify_findings([], tree, _ledger())
    assert "SHOULD_NOT_APPEAR" not in str(out)


def test_exit_codes_are_distinct():
    codes = {hist.EXIT_CLEAN, hist.EXIT_UNKNOWN_HISTORICAL,
             hist.EXIT_CURRENT_TREE, hist.EXIT_NO_GITLEAKS, hist.EXIT_SHALLOW}
    assert len(codes) == 5 and hist.EXIT_CLEAN == 0


def test_committed_ledger_is_actually_tracked_by_git():
    """The ledger must be a *tracked* file: a defensive .gitignore pattern
    (e.g. ``*secret*.json``) silently dropped its first filename, which only
    surfaced as a CI-only failure. Never again."""
    import subprocess

    out = subprocess.run(
        ["git", "ls-files", "--error-unmatch",
         "docs/security/historical_findings_ledger.json"],
        cwd=hist._REPO_ROOT, capture_output=True, text=True, check=False,
    )
    assert out.returncode == 0, "ledger JSON is not tracked by git"
