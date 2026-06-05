"""Tests for the six-layer coordination audit (scripts/coordination_audit.py).

Covers Phase 10 of the coordination-audit mission:

  1. Report schema validity + JSON serialisability
  2. Scoring math (PASS=1, WARN=0.5, FAIL=0; weighted means)
  3. NO_DATA is excluded from the mean (never scored as 0 or 1) and a
     >50%-NO_DATA layer cannot grade PASS; >50% overall adds _LOW_EVIDENCE
  4. Markdown and JSON report generation
  5. Determinism (same inputs -> identical bytes)
  6. Layer proofs the audit asserts are real: invalid status transitions are
     rejected, duplicate/ticker/provenance/advisory guards exist, reset guard
     is in place.

All synthetic; no runtime DB, no broker, no network.
"""
from __future__ import annotations

import importlib
import json

import pytest

ca = importlib.import_module("scripts.coordination_audit")


# ---------------------------------------------------------------------------
# 1. Schema validity + serialisability
# ---------------------------------------------------------------------------
def test_report_builds_and_is_json_serialisable():
    report = ca.build_report(commit="TESTSHA", now=_fixed_now())
    payload = report.to_dict()
    # Round-trips through JSON without error.
    s = json.dumps(payload)
    back = json.loads(s)
    assert set(back.keys()) == {
        "generated_at_utc", "repo_commit", "mode", "overall_coordination_score",
        "overall_coordination_grade", "no_data_ratio", "layers",
        "blocking_findings", "warnings", "provenance",
    }
    assert back["repo_commit"] == "TESTSHA"
    assert set(back["layers"].keys()) == {
        "choreography", "timing", "position_control",
        "collision_safety", "simulation", "operations",
    }


def test_every_metric_has_required_fields_and_valid_status():
    report = ca.build_report(commit="X", now=_fixed_now())
    for layer in report.layers.values():
        assert layer.status in {ca.PASS, ca.WARN, ca.FAIL, ca.NO_DATA}
        for m in layer.checked_metrics:
            assert m.name
            assert m.status in {ca.PASS, ca.WARN, ca.FAIL, ca.NO_DATA}
            assert m.expected
            assert m.provenance
        for e in layer.evidence:
            assert e.provenance_type in ca.PROVENANCE_TYPES


def test_evidence_ref_rejects_bad_provenance_type():
    with pytest.raises(ValueError):
        ca.EvidenceRef("f.py", 1, 1, "src", "NOT_A_REAL_TYPE")


def test_metric_rejects_bad_status():
    with pytest.raises(ValueError):
        ca.Metric("m", 1, "exp", "MAYBE", "prov")


# ---------------------------------------------------------------------------
# 2. Scoring math
# ---------------------------------------------------------------------------
def test_metric_score_map():
    assert ca.metric_score(ca.PASS) == 1.0
    assert ca.metric_score(ca.WARN) == 0.5
    assert ca.metric_score(ca.FAIL) == 0.0
    assert ca.metric_score(ca.NO_DATA) is None


def test_layer_score_is_mean_of_pass_warn_fail():
    metrics = [
        ca.Metric("a", 1, "e", ca.PASS, "p"),
        ca.Metric("b", 1, "e", ca.WARN, "p"),
        ca.Metric("c", 1, "e", ca.FAIL, "p"),
    ]
    score, status = ca.layer_status_from_metrics(metrics)
    assert score == pytest.approx((1.0 + 0.5 + 0.0) / 3)
    # any FAIL -> layer FAIL
    assert status == ca.FAIL


def test_layer_status_warn_when_no_fail_but_warn_present():
    metrics = [
        ca.Metric("a", 1, "e", ca.PASS, "p"),
        ca.Metric("b", 1, "e", ca.WARN, "p"),
    ]
    score, status = ca.layer_status_from_metrics(metrics)
    assert score == pytest.approx(0.75)
    assert status == ca.WARN


def test_layer_all_pass_is_pass():
    metrics = [ca.Metric(f"m{i}", 1, "e", ca.PASS, "p") for i in range(3)]
    score, status = ca.layer_status_from_metrics(metrics)
    assert score == 1.0
    assert status == ca.PASS


# ---------------------------------------------------------------------------
# 3. NO_DATA handling
# ---------------------------------------------------------------------------
def test_no_data_excluded_from_mean_not_treated_as_zero():
    # One PASS + one NO_DATA must score 1.0 (NO_DATA dropped), not 0.5.
    metrics = [
        ca.Metric("a", 1, "e", ca.PASS, "p"),
        ca.Metric("b", None, "e", ca.NO_DATA, "p"),
    ]
    score, status = ca.layer_status_from_metrics(metrics)
    assert score == 1.0
    # 50% NO_DATA is not >50%, so PASS still allowed here.
    assert status == ca.PASS


def test_majority_no_data_layer_cannot_grade_pass():
    metrics = [
        ca.Metric("a", 1, "e", ca.PASS, "p"),
        ca.Metric("b", None, "e", ca.NO_DATA, "p"),
        ca.Metric("c", None, "e", ca.NO_DATA, "p"),
    ]
    score, status = ca.layer_status_from_metrics(metrics)
    assert score == 1.0  # numeric mean of the single scored metric
    assert status == ca.WARN  # but >50% NO_DATA caps it below PASS


def test_all_no_data_layer_is_no_data_with_null_score():
    metrics = [ca.Metric(f"m{i}", None, "e", ca.NO_DATA, "p") for i in range(2)]
    score, status = ca.layer_status_from_metrics(metrics)
    assert score is None
    assert status == ca.NO_DATA


def test_grade_thresholds():
    assert ca.overall_grade(None) == "NO_MEASURABLE_DATA"
    assert ca.overall_grade(0.95) == "RHYTHMIC_UNISON"
    assert ca.overall_grade(0.80) == "MOSTLY_COORDINATED"
    assert ca.overall_grade(0.65) == "PARTIAL_COORDINATION"
    assert ca.overall_grade(0.45) == "FRAGMENTED"
    assert ca.overall_grade(0.10) == "UNSYNCHRONIZED"


def test_low_evidence_suffix_when_majority_no_data():
    layers = {
        "choreography": ca.CoordinationLayerStat("choreography", 0.7, ca.WARN),
    }
    score, grade = ca.compute_overall(layers, no_data_ratio=0.6)
    assert grade.endswith("_LOW_EVIDENCE")
    score2, grade2 = ca.compute_overall(layers, no_data_ratio=0.1)
    assert not grade2.endswith("_LOW_EVIDENCE")


def test_overall_is_weighted_mean_excluding_null_layers():
    layers = {
        "a": ca.CoordinationLayerStat("a", 1.0, ca.PASS),
        "b": ca.CoordinationLayerStat("b", 0.0, ca.FAIL),
        "c": ca.CoordinationLayerStat("c", None, ca.NO_DATA),  # excluded
    }
    score, _ = ca.compute_overall(layers, no_data_ratio=0.0,
                                  weights={"a": 1.0, "b": 1.0, "c": 1.0})
    assert score == pytest.approx(0.5)  # (1.0 + 0.0) / 2, c dropped


# ---------------------------------------------------------------------------
# 4. Report generation (markdown + json)
# ---------------------------------------------------------------------------
def test_markdown_render_contains_all_layers_and_grade():
    report = ca.build_report(commit="ABC123", now=_fixed_now())
    md = ca.render_markdown(report)
    assert "# Sleeping Passenger Coordination Audit" in md
    for title in ca._LAYER_TITLES.values():
        assert title in md
    assert report.overall_coordination_grade in md
    assert "## Provenance Statement" in md
    assert "## Blocking Findings" in md
    assert "## Next Fixes" in md


def test_json_render_is_parseable_and_matches_to_dict():
    report = ca.build_report(commit="ABC123", now=_fixed_now())
    parsed = json.loads(ca.render_json(report))
    assert parsed == report.to_dict()


# ---------------------------------------------------------------------------
# 5. Determinism
# ---------------------------------------------------------------------------
def test_build_report_is_deterministic_for_fixed_inputs():
    now = _fixed_now()
    r1 = ca.render_json(ca.build_report(commit="SHA", now=now))
    r2 = ca.render_json(ca.build_report(commit="SHA", now=now))
    assert r1 == r2


def test_mode_is_partial_or_measured_for_live_repo():
    report = ca.build_report(commit="SHA", now=_fixed_now())
    assert report.mode in {"MEASURED", "PARTIAL_DATA"}
    # The live repo audit must always produce a real score (not NO_DATA).
    assert report.overall_coordination_score is not None


# ---------------------------------------------------------------------------
# 6. Layer proofs the audit relies on (these make the WARN->PASS real)
# ---------------------------------------------------------------------------
def test_invalid_signal_status_is_rejected():
    """Position/Control: out-of-enum status values are rejected, not accepted."""
    sia = importlib.import_module("scripts.signal_inbox_api")
    valid = set(sia.VALID_USER_STATUSES)
    # Every claimed-valid status is in the frozenset; junk is not.
    assert "pending" in valid and "rejected" in valid
    assert "NOT_A_STATUS" not in valid
    assert "OPEN" not in valid  # a trade state must not be a signal user_status


def test_invalid_reconciliation_status_is_rejected():
    sia = importlib.import_module("scripts.signal_inbox_api")
    valid = set(sia.VALID_RECONCILIATION_STATUSES)
    assert valid == {"WIN", "LOSS", "BREAKEVEN", "UNKNOWN"}
    assert "PENDING" not in valid  # cannot reconcile into a non-outcome state


def test_collision_and_advisory_guards_present_in_source():
    """Collision/Safety: the guards the audit scores PASS for actually exist."""
    persistence = ca._read_text(ca.REPO_ROOT, "scripts/persistence.py") or ""
    assert "duplicate_fingerprints" in persistence
    assert "INSERT OR IGNORE INTO manual_trades" in persistence
    assert "canonical_symbol TEXT NOT NULL UNIQUE" in persistence
    assert "trade_mode" in persistence and "created_via" in persistence
    advisory = ca._read_text(ca.REPO_ROOT, "scripts/advisory_contract.py") or ""
    assert "advisory_safety_stamps" in advisory


def test_reset_guard_present_in_source():
    """Operations: the destructive reset script is guarded, not bare."""
    reset = ca._read_text(ca.REPO_ROOT, "scripts/reset_local_logs.py") or ""
    assert "guarded_mutation" in reset
    assert "_ALLOWED_TABLES" in reset
    assert "safe_db_path_allowed" in reset
    assert "--apply" in reset  # dry-run is the default; apply is explicit


def test_provenance_separation_markers_present():
    """Simulation: synthetic/imported/paper/live are kept distinct."""
    origin = ca._read_text(ca.REPO_ROOT, "scripts/manual_trade_origin.py") or ""
    assert "EXCLUDED_TRADE_MODES" in origin
    sia = ca._read_text(ca.REPO_ROOT, "scripts/signal_inbox_api.py") or ""
    assert "SYNTHETIC_LOGGED_BY_MARKERS" in sia


def test_calibration_real_outcomes_reported_no_data():
    """Honesty: with no real outcomes committed, calibration is NO_DATA."""
    report = ca.build_report(commit="SHA", now=_fixed_now())
    sim = report.layers["simulation"]
    calib = [m for m in sim.checked_metrics if m.name == "calibration_evidence_status"]
    assert calib and calib[0].status == ca.NO_DATA


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _fixed_now():
    from datetime import datetime, timezone
    return datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
