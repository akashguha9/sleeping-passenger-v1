"""Tests for the Operational Readiness Audit (scripts/operational_readiness_audit.py).

Covers Phase 12 items 1-8, 25-30:
  schema validity, scoring math, evidence-quality penalty, NO_DATA penalty,
  real outcomes not fabricated, synthetic cannot be MEASURED, imported cannot
  be LIVE_MANUAL, paper cannot be real, release thresholds, markdown + JSON
  generation, determinism, advisory-only preserved, no broker execution added.

All deterministic; runtime counts are injected so the suite never depends on
the live DB.
"""
from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone

import pytest

ora = importlib.import_module("scripts.operational_readiness_audit")


def _now():
    return datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)


def _counts(**kw):
    return ora.OutcomeCounts(**kw)


# --- 1. schema validity -----------------------------------------------------
def test_report_builds_and_json_serialises():
    r = ora.build_report(commit="SHA", now=_now(), outcome_counts=_counts())
    payload = r.to_dict()
    s = json.dumps(payload)
    back = json.loads(s)
    assert set(back["sections"].keys()) == set(ora.SECTION_KEYS)
    for key in ("readiness_score", "readiness_grade", "evidence_quality_score",
                "no_data_ratio", "real_outcome_count", "mode", "raw_readiness_score"):
        assert key in back


def test_metric_and_evidence_validation():
    with pytest.raises(ValueError):
        ora.Metric("m", 1, "e", "MAYBE", 1.0, "STATIC_CODE")
    with pytest.raises(ValueError):
        ora.Metric("m", 1, "e", "PASS", 1.0, "NOPE")
    with pytest.raises(ValueError):
        ora.EvidenceRef("f", 1, 1, "src", "BAD_PROV")


def test_every_metric_has_score_consistent_with_status():
    r = ora.build_report(commit="X", now=_now(), outcome_counts=_counts())
    for sec in r.sections.values():
        for m in sec.metrics:
            if m.status == "NO_DATA":
                assert m.score is None
            else:
                assert m.score == {"PASS": 1.0, "WARN": 0.5, "FAIL": 0.0}[m.status]


# --- 2. scoring math --------------------------------------------------------
def test_section_status_and_score():
    metrics = [
        ora._M("a", 1, "e", "PASS", "STATIC_CODE"),
        ora._M("b", 1, "e", "WARN", "STATIC_CODE"),
    ]
    score, status = ora.section_status_and_score(metrics)
    assert score == pytest.approx(0.75)
    assert status == "WARN"


def test_fail_dominates_section_status():
    metrics = [
        ora._M("a", 1, "e", "PASS", "STATIC_CODE"),
        ora._M("b", 1, "e", "FAIL", "STATIC_CODE"),
    ]
    _, status = ora.section_status_and_score(metrics)
    assert status == "FAIL"


def test_readiness_grade_thresholds():
    assert ora.readiness_grade(None) == "NO_MEASURABLE_DATA"
    assert ora.readiness_grade(0.95) == "FIELD_READY"
    assert ora.readiness_grade(0.85) == "OPERATIONALLY_READY"
    assert ora.readiness_grade(0.72) == "PILOT_READY"
    assert ora.readiness_grade(0.63) == "PAPER_READY"
    assert ora.readiness_grade(0.50) == "REHEARSAL_READY"
    assert ora.readiness_grade(0.20) == "NOT_READY"


# --- 3. evidence-quality penalty -------------------------------------------
def test_evidence_quality_weights():
    metrics = [
        ora._M("real", 1, "e", "PASS", "LIVE_MANUAL"),      # 1.00
        ora._M("static", 1, "e", "PASS", "STATIC_CODE"),    # 0.30
        ora._M("nd", None, "e", "NO_DATA", "NO_DATA"),      # 0.00
    ]
    eq = ora.evidence_quality(metrics)
    assert eq == pytest.approx((1.00 + 0.30 + 0.00) / 3)


def test_static_only_cannot_reach_field_ready():
    """A perfectly-structured static-only system must not grade FIELD_READY."""
    r = ora.build_report(commit="X", now=_now(), outcome_counts=_counts())
    # raw is high, but evidence quality drags the final score well below 0.90.
    assert r.raw_readiness_score is not None and r.raw_readiness_score >= 0.80
    assert r.readiness_score < 0.45
    assert not r.readiness_grade.startswith("FIELD_READY")
    assert "_NO_REAL_OUTCOMES" in r.readiness_grade


# --- 4. NO_DATA penalty -----------------------------------------------------
def test_no_data_excluded_from_section_mean():
    metrics = [
        ora._M("a", 1, "e", "PASS", "STATIC_CODE"),
        ora._M("b", None, "e", "NO_DATA", "NO_DATA"),
    ]
    score, status = ora.section_status_and_score(metrics)
    assert score == 1.0  # NO_DATA not treated as 0
    assert status == "PASS"  # exactly 50% is not >50%


def test_majority_no_data_section_capped_below_pass():
    metrics = [
        ora._M("a", 1, "e", "PASS", "STATIC_CODE"),
        ora._M("b", None, "e", "NO_DATA", "NO_DATA"),
        ora._M("c", None, "e", "NO_DATA", "NO_DATA"),
    ]
    score, status = ora.section_status_and_score(metrics)
    assert score == 1.0
    assert status == "WARN"


def test_low_evidence_suffix_applied():
    g = ora._apply_suffixes("PILOT_READY", no_data_ratio=0.6, real_outcome_count=5,
                            has_blocker=False)
    assert g == "PILOT_READY_LOW_EVIDENCE"


# --- 5/6/7/8. provenance boundaries ----------------------------------------
def test_real_outcomes_not_fabricated_when_absent():
    r = ora.build_report(commit="X", now=_now(), outcome_counts=_counts(real_n=0))
    assert r.real_outcome_count == 0
    assert r.mode == "PARTIAL_DATA"
    sec = r.sections["calibration_readiness"]
    statuses = {m.name: m.status for m in sec.metrics}
    assert statuses["calibration_dataset_availability"] == "NO_DATA"
    assert statuses["brier_score_readiness"] == "NO_DATA"


def test_synthetic_only_cannot_be_measured_mode():
    r = ora.build_report(commit="X", now=_now(),
                         outcome_counts=_counts(synthetic_n=500, real_n=0))
    assert r.mode != "MEASURED"  # synthetic never promotes mode
    sec = r.sections["calibration_readiness"]
    cmode = next(m for m in sec.metrics if m.name == "calibration_mode_assignment")
    assert cmode.value == "SYNTHETIC_ONLY"
    assert cmode.status == "NO_DATA"


def test_imported_backtest_is_not_live_manual():
    r = ora.build_report(commit="X", now=_now(),
                         outcome_counts=_counts(imported_n=200, real_n=0))
    assert r.mode == "PARTIAL_DATA"  # imported does not become MEASURED
    assert r.real_outcome_count == 0
    cmode = next(m for m in r.sections["calibration_readiness"].metrics
                 if m.name == "calibration_mode_assignment")
    assert cmode.value == "IMPORTED_BACKTEST_ONLY"
    assert cmode.provenance_type == "IMPORTED_BACKTEST"


def test_paper_outcomes_are_not_real_outcomes():
    r = ora.build_report(commit="X", now=_now(),
                         outcome_counts=_counts(paper_n=200, real_n=0))
    assert r.real_outcome_count == 0
    assert r.mode == "PARTIAL_DATA"
    assert "_NO_REAL_OUTCOMES" in r.readiness_grade


def test_real_outcomes_promote_to_measured():
    r = ora.build_report(commit="X", now=_now(),
                         outcome_counts=_counts(real_n=40, runtime_records=40))
    assert r.mode == "MEASURED"
    assert "_NO_REAL_OUTCOMES" not in r.readiness_grade


# --- 25. release threshold logic -------------------------------------------
def test_release_section_present_and_documents_gate():
    r = ora.build_report(commit="X", now=_now(), outcome_counts=_counts())
    sec = r.sections["release_readiness"]
    names = {m.name for m in sec.metrics}
    assert "release_gate_includes_operational_audit" in names
    assert "minimum_readiness_threshold" in names


# --- 26/27. report generation ----------------------------------------------
def test_markdown_render_has_all_sections_and_formula():
    r = ora.build_report(commit="ABC", now=_now(), outcome_counts=_counts())
    md = ora.render_markdown(r)
    for title in ora._SECTION_TITLES.values():
        assert title in md
    assert "readiness_score = raw_readiness_score" in md
    assert "This report measures operational readiness, not trading edge." in md
    assert "## Pilot Gate" in md


def test_json_render_matches_to_dict():
    r = ora.build_report(commit="ABC", now=_now(), outcome_counts=_counts())
    assert json.loads(ora.render_json(r)) == r.to_dict()


# --- 28. determinism --------------------------------------------------------
def test_deterministic_for_fixed_inputs():
    a = ora.render_json(ora.build_report(commit="S", now=_now(), outcome_counts=_counts()))
    b = ora.render_json(ora.build_report(commit="S", now=_now(), outcome_counts=_counts()))
    assert a == b


# --- 29/30. advisory-only preserved; no broker execution -------------------
def test_no_broker_execution_tokens_in_new_modules():
    forbidden = ("place_order", "submit_order", "execute_trade", "broker_execute",
                 "auto_execute")
    for rel in ("scripts/operational_readiness_audit.py",
                "scripts/manual_trade_validation.py",
                "scripts/performance_truthfulness.py",
                "scripts/export_envelope.py"):
        text = ora._read(ora.REPO_ROOT, rel) or ""
        low = text.lower()
        for tok in forbidden:
            assert tok not in low, f"{tok} appears in {rel}"


def test_advisory_only_guard_not_weakened():
    # The advisory contract + persistence stamps must still be present.
    assert ora._has(ora.REPO_ROOT, "scripts/advisory_contract.py", "advisory_safety_stamps")
    assert ora._has(ora.REPO_ROOT, "scripts/persistence.py", "_ADVISORY_STATUS")
