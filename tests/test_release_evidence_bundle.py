"""Release evidence bundle: tamper-evidence, honesty, schema, no secrets."""
from __future__ import annotations

import json

from scripts import build_release_evidence_bundle as rel
from scripts import verify_release_evidence_bundle as verify
from scripts import secret_fixture_lint as lint


def _fake_runner(rc_by_marker: dict[str, int] | None = None):
    rc_by_marker = rc_by_marker or {}

    def run(cmd: list[str]) -> int:
        joined = " ".join(cmd)
        for marker, rc in rc_by_marker.items():
            if marker in joined:
                return rc
        return 0
    return run


def _collect(rc_by_marker: dict[str, int] | None = None):
    return rel.collect(runner=_fake_runner(rc_by_marker), skip_pytest=True)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_required_fields_present():
    b = _collect()
    for field in rel.REQUIRED_FIELDS:
        assert field in b, field
    json.dumps(b)


def test_not_real_money_flag_is_hard_true():
    assert _collect()["not_real_money_execution_software"] is True


def test_lockfile_and_workflow_and_core_hashes_present():
    b = _collect()
    locked = {e["path"] for e in b["dependency_lockfile_hashes"]}
    assert "requirements.lock" in locked
    assert "frontend/package-lock.json" in locked
    wf = {e["path"] for e in b["workflow_hashes"]}
    assert ".github/workflows/dep_audit.yml" in wf
    core = {e["path"] for e in b["core_source_hashes"]}
    assert "scripts/persistence.py" in core
    assert "scripts/audit_advisory_only_boundary.py" in core


# ---------------------------------------------------------------------------
# Tamper evidence
# ---------------------------------------------------------------------------


def test_bundle_sha_matches_canonical_content():
    b = _collect()
    assert b["bundle_sha256"] == rel.canonical_bundle_sha256(b)
    code, problems = verify.verify(b)
    assert code == verify.EXIT_OK, problems


def test_tampering_with_bundle_fails_verification():
    b = _collect()
    b["overall_pass"] = True  # the classic lie
    code, problems = verify.verify(b)
    assert code == verify.EXIT_TAMPERED_BUNDLE
    assert any("modified after generation" in p for p in problems)


def test_bundle_hash_changes_when_a_critical_file_changes():
    b = _collect()
    mutated = json.loads(json.dumps(b))
    for entry in mutated["core_source_hashes"]:
        if entry["path"] == "scripts/persistence.py":
            entry["sha256"] = "0" * 64  # simulate a changed file fingerprint
    assert rel.canonical_bundle_sha256(mutated) != b["bundle_sha256"]


def test_file_drift_after_generation_fails_verification(tmp_path):
    """A fingerprinted file changing AFTER bundle generation is caught."""
    b = _collect()
    # Re-sign the bundle but verify against a tree where the file differs.
    (tmp_path / "scripts").mkdir(parents=True)
    for entry in b["core_source_hashes"]:
        p = tmp_path / entry["path"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("changed content\n", encoding="utf-8")
    for entry in b["dependency_lockfile_hashes"] + b["workflow_hashes"]:
        p = tmp_path / entry["path"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("changed content\n", encoding="utf-8")
    code, problems = verify.verify(b, repo_root=tmp_path)
    assert code == verify.EXIT_FILE_DRIFT
    assert any("hash mismatch" in p for p in problems)


# ---------------------------------------------------------------------------
# Honesty
# ---------------------------------------------------------------------------


def test_failed_audit_fails_the_bundle():
    b = _collect({"audit_advisory_only_boundary": 1})
    assert b["checks"]["advisory_only_boundary"]["status"] == "fail"
    assert b["overall_pass"] is False
    assert "advisory_only_boundary" in b["failed_checks"]


def test_skipped_pytest_is_not_pass():
    b = _collect()
    assert b["checks"]["pytest_release_subset"]["status"] == "skipped"
    assert b["overall_pass"] is False


def test_verifier_rejects_dishonest_aggregation():
    b = _collect({"audit_model_evaluation_honesty.py": 1})
    b["overall_pass"] = True
    b["bundle_sha256"] = rel.canonical_bundle_sha256(b)  # re-signed lie
    code, problems = verify.verify(b)
    assert code == verify.EXIT_INCONSISTENT
    assert any("dishonest aggregation" in p for p in problems)


def test_dirty_tree_is_reported_as_boolean():
    assert isinstance(_collect()["dirty_tree"], bool)


def test_known_blockers_include_the_honest_alpha_line():
    blockers = " ".join(_collect()["known_blockers"])
    assert "out-of-sample" in blockers


# ---------------------------------------------------------------------------
# No secrets
# ---------------------------------------------------------------------------


def test_bundle_never_embeds_environment_values(monkeypatch):
    canary = "RELEASE_CANARY_VALUE_THAT_MUST_NOT_APPEAR_7K2"
    monkeypatch.setenv("MVP_API_TOKEN", canary)
    monkeypatch.setenv("EDINET_API_KEY", canary)
    assert canary not in json.dumps(_collect())


def test_serialized_bundle_is_scanner_clean():
    serialized = json.dumps(_collect(), indent=2)
    assert lint.scan_text(serialized, "bundle.json") == []
