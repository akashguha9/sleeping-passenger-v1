"""Evidence-bundle honesty contract: stable schema, no lying, no secrets."""
from __future__ import annotations

import json
import os

from scripts import build_security_evidence_bundle as bundle
from scripts import secret_fixture_lint as lint


def _fake_runner(rc_by_marker: dict[str, int]):
    """Runner returning a canned exit code per command-substring marker."""
    def run(cmd: list[str]) -> int:
        joined = " ".join(cmd)
        for marker, rc in rc_by_marker.items():
            if marker in joined:
                return rc
        return 0
    return run


def _collect(rc_by_marker: dict[str, int] | None = None, **kw):
    return bundle.collect(runner=_fake_runner(rc_by_marker or {}), **kw)


# ---------------------------------------------------------------------------
# Schema stability
# ---------------------------------------------------------------------------


def test_required_fields_present_and_schema_versioned():
    b = _collect(skip_pytest=True)
    for field in bundle.REQUIRED_FIELDS:
        assert field in b, field
    assert b["schema_version"] == bundle.SCHEMA_VERSION == 1
    json.dumps(b)  # must be serializable as-is


def test_required_fields_contract_is_frozen():
    # Renaming/removing a field is a schema break: bump SCHEMA_VERSION and
    # update consumers deliberately, never silently.
    assert bundle.REQUIRED_FIELDS == (
        "schema_version",
        "generated_at_utc",
        "commit_sha",
        "python_version",
        "platform",
        "gitleaks_version",
        "gitleaks_config_sha256",
        "checks",
        "security_file_hashes",
        "overall_pass",
        "failed_checks",
        "skipped_checks",
    )


def test_security_file_hashes_cover_the_critical_files():
    b = _collect(skip_pytest=True)
    hashed = {entry["path"] for entry in b["security_file_hashes"]}
    for required in (
        ".gitleaks.toml",
        ".github/workflows/dep_audit.yml",
        "scripts/secret_fixture_lint.py",
        "scripts/audit_security_gate_integrity.py",
        "scripts/persistence.py",
        "SECURITY.md",
    ):
        assert required in hashed, required
    for entry in b["security_file_hashes"]:
        assert len(entry["sha256"]) == 64


# ---------------------------------------------------------------------------
# Honest aggregation — failed/skipped can never read as passed
# ---------------------------------------------------------------------------


def test_failed_check_fails_the_bundle():
    b = _collect({"secret_fixture_lint.py": 1}, skip_pytest=True)
    assert b["checks"]["secret_fixture_lint"]["status"] == "fail"
    assert b["overall_pass"] is False
    assert "secret_fixture_lint" in b["failed_checks"]


def test_every_check_can_independently_fail_the_bundle():
    for marker, name in (
        ("audit_github_actions_pinning", "workflow_pinning_audit"),
        ("audit_security_gate_integrity", "security_gate_integrity_audit"),
        ("audit_local_data_protection", "local_data_protection_audit"),
    ):
        b = _collect({marker: 1}, skip_pytest=True)
        assert b["checks"][name]["status"] == "fail", name
        assert b["overall_pass"] is False, name


def test_skipped_is_not_pass():
    b = _collect(skip_pytest=True)
    assert b["checks"]["pytest_security_subset"]["status"] == "skipped"
    assert "pytest_security_subset" in b["skipped_checks"]
    assert b["overall_pass"] is False  # skipped evidence is no evidence


def test_check_status_vocabulary_is_closed():
    b = _collect(skip_pytest=True)
    assert {c["status"] for c in b["checks"].values()} <= {
        "pass", "fail", "skipped"
    }


# ---------------------------------------------------------------------------
# No secrets in the bundle
# ---------------------------------------------------------------------------


def test_bundle_does_not_embed_environment_values(monkeypatch):
    canary = "BUNDLE_CANARY_VALUE_THAT_MUST_NOT_APPEAR_9Q4"
    monkeypatch.setenv("MVP_API_TOKEN", canary)
    monkeypatch.setenv("EDINET_API_KEY", canary)
    b = _collect(skip_pytest=True)
    assert canary not in json.dumps(b)


def test_serialized_bundle_is_scanner_clean():
    b = _collect(skip_pytest=True)
    serialized = json.dumps(b, indent=2)
    assert lint.scan_text(serialized, "bundle.json") == []


def test_bundle_records_only_commands_and_exit_codes():
    b = _collect(skip_pytest=True)
    for check in b["checks"].values():
        assert set(check) == {"status", "command", "returncode"}
