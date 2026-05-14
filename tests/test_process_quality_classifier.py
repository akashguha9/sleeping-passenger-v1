"""Tests for ``scripts.process_quality_classifier``.

Pin
---
- Good process + WIN  -> good_process_good_outcome
- Good process + LOSS -> good_process_bad_outcome
- Bad process  + WIN  -> bad_process_good_outcome
- Bad process  + LOSS -> bad_process_bad_outcome
- Missing required fields -> incomplete_record
- Unknown outcome -> unknown
- Process error string trumps a strong journal (signals "bad process")
- Aggregate computes correct skill_evidence_score and luck_risk_score
- Safety stamps locked, operator_action present, no execution permission,
  classifier is deterministic.
"""
from __future__ import annotations

import pytest

from scripts import process_quality_classifier as pqc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strong_journal(**overrides):
    base = {
        "thesis": "post-FOMC volatility crush; mean-revert IV",
        "invalidation_level": "VIX > 28",
        "exit_plan": "exit at 50% of credit or 2x debit",
        "risk_reason": "max 1R on portfolio",
        "entry_reason": "breakout retest",
        "expected_horizon": "5 trading days",
        "confidence_before": 0.6,
        "emotional_state": "calm",
        "mistake_tags": "",
        "lesson": "",
        "journal_completeness_score": 0.85,
        "learning_ready": True,
        "process_error": "",
        "process_error_notes": "",
    }
    base.update(overrides)
    return base


def _weak_journal(**overrides):
    base = {
        "thesis": "",
        "invalidation_level": "",
        "exit_plan": "",
        "risk_reason": "",
        "journal_completeness_score": 0.2,
        "learning_ready": False,
        "process_error": "",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Single-record classification
# ---------------------------------------------------------------------------


def test_good_process_good_outcome():
    rec = _strong_journal(outcome_status="WIN")
    r = pqc.classify_trade(rec)
    assert r["process_quality_state"] == pqc.GOOD_PROCESS_GOOD_OUTCOME
    assert r["skill_evidence_score"] == 1.0
    assert r["luck_risk_score"] == 0.0
    assert r["execution_permission"] is False
    assert r["can_execute"] is False
    assert r["broker_api_called"] is False
    assert r["ai_execution_count"] == 0
    assert r["operator_action"]


def test_good_process_bad_outcome():
    rec = _strong_journal(outcome_status="LOSS")
    r = pqc.classify_trade(rec)
    assert r["process_quality_state"] == pqc.GOOD_PROCESS_BAD_OUTCOME
    assert r["skill_evidence_score"] == 1.0
    assert r["luck_risk_score"] == 0.0


def test_bad_process_good_outcome_via_process_error():
    rec = _strong_journal(
        outcome_status="WIN",
        process_error="size_too_large",
        process_error_notes="entered 3R instead of 1R",
    )
    r = pqc.classify_trade(rec)
    assert r["process_quality_state"] == pqc.BAD_PROCESS_GOOD_OUTCOME
    assert r["skill_evidence_score"] == 0.0
    assert r["luck_risk_score"] == 1.0
    assert "process_error_logged" in r["classification_reasons"]


def test_bad_process_bad_outcome_via_weak_journal_but_fields_present():
    rec = _weak_journal(
        outcome_status="LOSS",
        # Fill required fields just enough that we *can* classify, but the
        # journal_completeness_score is below the threshold.
        thesis="something",
        invalidation_level="something",
        exit_plan="something",
        risk_reason="something",
        learning_ready=False,
        journal_completeness_score=0.3,
    )
    r = pqc.classify_trade(rec)
    assert r["process_quality_state"] == pqc.BAD_PROCESS_BAD_OUTCOME


def test_incomplete_record_when_required_missing():
    rec = {
        "outcome_status": "WIN",
        "journal_completeness_score": 0.9,
    }
    r = pqc.classify_trade(rec)
    assert r["process_quality_state"] == pqc.INCOMPLETE_RECORD
    assert any(
        reason.startswith("missing_required_fields:")
        for reason in r["classification_reasons"]
    )


def test_unknown_outcome():
    rec = _strong_journal(outcome_status="")
    r = pqc.classify_trade(rec)
    assert r["process_quality_state"] == pqc.STATE_UNKNOWN
    assert "outcome_unknown_or_pending" in r["classification_reasons"]


def test_process_error_none_token_is_not_a_real_error():
    # "none" / "no" / "clean" must NOT trip the bad-process branch.
    for sentinel in ["none", "None", "NONE", "no", "clean", "n/a", "NA"]:
        rec = _strong_journal(outcome_status="WIN", process_error=sentinel)
        r = pqc.classify_trade(rec)
        assert r["process_quality_state"] == pqc.GOOD_PROCESS_GOOD_OUTCOME, sentinel


def test_breakeven_treated_as_non_win():
    rec = _strong_journal(outcome_status="BREAKEVEN")
    r = pqc.classify_trade(rec)
    # Good process + breakeven rolls into good_process_bad_outcome with a
    # reason that says so.
    assert r["process_quality_state"] == pqc.GOOD_PROCESS_BAD_OUTCOME
    assert "breakeven_counted_as_non_win" in r["classification_reasons"]


def test_non_dict_input_returns_unknown_with_safety_stamps():
    r = pqc.classify_trade("nope")
    assert r["process_quality_state"] == pqc.STATE_UNKNOWN
    assert r["broker_api_called"] is False
    assert r["execution_permission"] is False


def test_deterministic():
    rec = _strong_journal(outcome_status="WIN")
    a = pqc.classify_trade(rec)
    b = pqc.classify_trade(rec)
    assert a == b


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------


def test_aggregate_skill_evidence_and_luck_risk():
    records = [
        _strong_journal(outcome_status="WIN"),   # good/good
        _strong_journal(outcome_status="WIN"),   # good/good
        _strong_journal(outcome_status="LOSS"),  # good/bad
        _strong_journal(
            outcome_status="WIN",
            process_error="size_too_large",
        ),  # bad/good
    ]
    agg = pqc.aggregate(records)
    assert agg["trade_count"] == 4
    assert agg["classified_count"] == 4
    assert agg["state_distribution"][pqc.GOOD_PROCESS_GOOD_OUTCOME] == 2
    assert agg["state_distribution"][pqc.GOOD_PROCESS_BAD_OUTCOME] == 1
    assert agg["state_distribution"][pqc.BAD_PROCESS_GOOD_OUTCOME] == 1
    assert agg["skill_evidence_score"] == pytest.approx(3 / 4, rel=1e-6)
    # 1 lucky win out of 3 total wins.
    assert agg["luck_risk_score"] == pytest.approx(1 / 3, rel=1e-6)
    assert agg["execution_permission"] is False
    assert agg["broker_api_called"] is False


def test_aggregate_excludes_incomplete_from_classified():
    records = [
        _strong_journal(outcome_status="WIN"),
        {"outcome_status": "WIN"},  # missing required fields
    ]
    agg = pqc.aggregate(records)
    assert agg["trade_count"] == 2
    assert agg["classified_count"] == 1
    assert agg["incomplete_record_count"] == 1
    assert agg["state_distribution"][pqc.INCOMPLETE_RECORD] == 1


def test_aggregate_empty_input():
    agg = pqc.aggregate([])
    assert agg["trade_count"] == 0
    assert agg["classified_count"] == 0
    assert agg["skill_evidence_score"] == 0.0
    assert agg["luck_risk_score"] == 0.0
    assert agg["validation_status"] == "not_applicable"


def test_aggregate_non_iterable_returns_invalid():
    agg = pqc.aggregate(42)  # type: ignore[arg-type]
    assert agg["validation_status"] == "invalid"
    assert agg["execution_permission"] is False
