"""Phase 4 — MISSING_PROBABILITY resolved honestly (no fabrication)."""
from __future__ import annotations

from scripts.missing_probability_resolution import (
    SCORE_VECTOR_INCOMPLETE,
    SCORE_VECTOR_MISSING,
    audit_missing_probability,
    resolve_probability,
)
from tests._forward_snapshot_helpers import init_db, seed_score_vector

_COMPLETE = {"EMS": 0.6, "EQS": 0.55, "DS": 0.5, "LS": 0.45, "EFS": 0.6, "APS": 0.5}


def test_complete_vector_always_yields_probability():
    p, reason = resolve_probability(_COMPLETE)
    assert reason == "OK"
    assert p is not None and 0.0 <= p <= 1.0


def test_incomplete_vector_yields_null_probability_with_reason():
    partial = dict(_COMPLETE)
    del partial["APS"]
    p, reason = resolve_probability(partial)
    assert p is None
    assert reason == SCORE_VECTOR_INCOMPLETE


def test_missing_vector_yields_null_probability_with_reason():
    p, reason = resolve_probability(None)
    assert p is None
    assert reason == SCORE_VECTOR_MISSING
    p2, reason2 = resolve_probability({})
    assert p2 is None and reason2 == SCORE_VECTOR_MISSING


def test_probability_in_range():
    for axes in ({k: 0.0 for k in _COMPLETE}, {k: 1.0 for k in _COMPLETE}, _COMPLETE):
        p, _ = resolve_probability(axes)
        assert 0.0 <= p <= 1.0


def test_out_of_range_axis_is_incomplete():
    bad = dict(_COMPLETE)
    bad["EMS"] = 1.7
    p, reason = resolve_probability(bad)
    assert p is None and reason == SCORE_VECTOR_INCOMPLETE


def test_missing_probability_count_decreases_for_complete_vectors(tmp_path):
    p = tmp_path / "t.db"
    init_db(p)
    seed_score_vector(p, event_id="e1", source_name="sec_edgar", ticker="AAPL", scored=True)
    seed_score_vector(p, event_id="e2", source_name="sec_edgar", ticker="MSFT", scored=True)
    audit = audit_missing_probability(p)
    assert audit["complete_vectors"] == 2
    assert audit["complete_resolved_to_probability"] == 2
    assert audit["complete_unresolved"] == 0
    assert audit["wiring_ok"] is True


def test_no_fake_probability_for_unscored_rows(tmp_path):
    p = tmp_path / "t.db"
    init_db(p)
    # An unscored (SCORE_UNAVAILABLE) row must NOT resolve a probability.
    seed_score_vector(p, event_id="e1", source_name="newsapi", ticker="AAPL", scored=False)
    audit = audit_missing_probability(p)
    assert audit["complete_vectors"] == 0
    assert audit["missing_or_unscored_vectors"] == 1
    assert audit["predictive_claim_allowed"] is False
