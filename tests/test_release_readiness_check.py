"""Operator readiness check: schema, failure propagation, honest output."""
from __future__ import annotations

import json

from scripts import run_release_readiness_check as check


def _runner(rc_by_marker: dict[str, int] | None = None):
    rc_by_marker = rc_by_marker or {}

    def run(cmd: list[str]) -> int:
        joined = " ".join(str(c) for c in cmd)
        for marker, rc in rc_by_marker.items():
            if marker in joined:
                return rc
        return 0
    return run


def _report(rc_by_marker=None, *, full=True, gitleaks="/fake/gitleaks"):
    return check.run_checks(
        full=full, runner=_runner(rc_by_marker), gitleaks_bin=gitleaks
    )


def test_json_schema_and_gate_order():
    report = _report()
    assert report["schema_version"] == 1
    json.dumps(report)
    names = [c["name"] for c in report["checks"]]
    assert names == [
        "secret_fixture_lint",
        "gitleaks_tree_scan",
        "security_gate_integrity",
        "dependency_reproducibility",
        "advisory_only_boundary",
        "model_evaluation_honesty",
        "local_data_protection",
        "release_evidence_bundle",
        "pytest_security_subset",
    ]
    assert report["final_status"] == "PASS"


def test_any_gate_failure_propagates_to_final_status():
    for marker, name in (
        ("secret_fixture_lint", "secret_fixture_lint"),
        ("audit_security_gate_integrity", "security_gate_integrity"),
        ("audit_advisory_only_boundary", "advisory_only_boundary"),
        ("audit_model_evaluation_honesty", "model_evaluation_honesty"),
        ("build_release_evidence_bundle", "release_evidence_bundle"),
        ("pytest", "pytest_security_subset"),
    ):
        report = _report({marker: 1})
        assert report["final_status"] == "FAIL", name
        assert name in report["failed"], name


def test_no_false_pass_when_gitleaks_missing():
    report = _report(gitleaks=None)
    by_name = {c["name"]: c for c in report["checks"]}
    assert by_name["gitleaks_tree_scan"]["status"] == "skipped"
    assert report["final_status"] == "PASS_WITH_SKIPS"


def test_quick_mode_skips_pytest_and_says_so():
    report = _report(full=False)
    by_name = {c["name"]: c for c in report["checks"]}
    assert by_name["pytest_security_subset"]["status"] == "skipped"
    assert report["final_status"] == "PASS_WITH_SKIPS"
    assert report["mode"] == "quick"


def test_fail_beats_skip_in_final_status():
    report = _report({"secret_fixture_lint": 1}, full=False)
    assert report["final_status"] == "FAIL"


def test_table_output_is_readable():
    table = check.render_table(_report({"audit_advisory_only_boundary": 1}))
    assert "advisory_only_boundary" in table
    assert "FAIL" in table and "FINAL" in table
    # one row per gate, aligned columns
    assert table.count("\n") >= 11


def test_status_vocabulary_is_closed():
    report = _report(full=False, gitleaks=None)
    assert {c["status"] for c in report["checks"]} <= {
        "pass", "fail", "skipped"
    }
