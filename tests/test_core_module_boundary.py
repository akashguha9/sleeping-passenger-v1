"""Core module boundary + import-hygiene tests."""
from __future__ import annotations

from scripts import core_module_boundary as b


def test_production_core_modules_are_classified_core():
    for m in [
        "leverage_governance", "score_calibration", "calibration_recommendations",
        "score_output_contract", "pre_real_money_preflight", "diablo_narrative_veto",
        "event_prior_detector", "moltbook_feedback", "signal_inbox_api",
        "persistence", "api_server", "outcome_evidence", "securities_master_coverage",
    ]:
        assert b.classify(m) == b.CORE, f"{m} should be CORE"


def test_archetype_modules_are_experimental():
    for m in ["chess_archetype_decision_layer", "tennis_archetype_execution",
              "jkd_decision_discipline", "optical_operating_system"]:
        assert b.classify(m) == b.EXPERIMENTAL


def test_no_core_imports_experimental_or_archived():
    violations = b.core_import_violations()
    assert violations == [], f"CORE import hygiene broken: {violations}"


def test_import_isolation_is_one():
    rep = b.build_report()
    assert rep["import_isolation_I"] == 1


def test_boundary_score_reported_and_strong():
    rep = b.build_report()
    assert "code_hygiene_CH" in rep
    assert "boundary_clarity_H" in rep
    # With the closure-based classification, hygiene should be clearly >= 7.
    assert rep["code_hygiene_CH"] >= 7.0
    assert 0.0 <= rep["boundary_clarity_H"] <= 1.0


def test_no_new_unclassified_modules():
    """A new unclassified script must be CORE/EXPERIMENTAL/SUPPORT-pattern or be
    explicitly added to the accepted baseline. This fails loudly otherwise."""
    new_unknown = b.new_unknown_modules()
    assert new_unknown == [], (
        "New unclassified module(s) detected — classify them in "
        f"core_module_boundary.py or add to ACCEPTED_UNKNOWN_BASELINE: {new_unknown}"
    )


def test_classification_buckets_sum_to_total():
    rep = b.build_report()
    assert (rep["n_core"] + rep["n_support"] + rep["n_experimental"] + rep["n_unknown"]
            == rep["n_total"])


def test_report_advisory_stamps():
    rep = b.build_report()
    assert rep["advisory_status"] == "ADVISORY_ONLY"
    assert rep["broker_api_called"] is False


# --- Phase 7: unknown-surface reduction -------------------------------------

def test_unknown_surface_is_small_after_review():
    rep = b.build_report()
    # The 54-module UNKNOWN backlog was reviewed (docs/UNKNOWN_MODULE_REVIEW.md);
    # only deliberate ARCHIVE_LATER candidates remain UNKNOWN.
    assert rep["n_unknown"] <= 5


def test_code_hygiene_is_strong():
    rep = b.build_report()
    assert rep["code_hygiene_CH"] >= 9.0
    assert rep["boundary_clarity_H"] >= 0.95


def test_no_core_imports_experimental_after_review():
    assert b.core_import_violations() == []
