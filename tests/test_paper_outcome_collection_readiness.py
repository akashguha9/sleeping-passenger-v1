"""Tests — paper-outcome collection readiness (deterministic, pure).

Kanté Continuation sprint, Workstream C.  Proves the readiness maths,
threshold labels, the linked-evidence ratio, the unconditional real-money
prohibition, that report mode performs no writes, and that the daily
synthesis result surfaces the readiness summary.  No fabricated outcomes.
"""
from __future__ import annotations

import pytest

from scripts.paper_outcome_collection_readiness import (
    LABEL_COLD_START,
    LABEL_EARLY_SAMPLE,
    LABEL_PAPER_CALIBRATED,
    LABEL_PROVISIONAL,
    build_paper_outcome_collection_readiness,
    load_paper_outcome_inputs,
)


def test_paper_outcome_readiness_zero_outcomes():
    r = build_paper_outcome_collection_readiness(closed_paper_outcomes_count=0)
    assert r["readiness_label"] == LABEL_COLD_START
    assert r["closed_paper_outcomes_count"] == 0
    assert r["paper_outcome_progress"] == 0.0
    assert r["calibration_readiness_score"] == 0.0


def test_paper_outcome_readiness_30_outcomes():
    r = build_paper_outcome_collection_readiness(closed_paper_outcomes_count=30)
    assert r["readiness_label"] == LABEL_EARLY_SAMPLE


def test_paper_outcome_readiness_50_outcomes():
    r = build_paper_outcome_collection_readiness(closed_paper_outcomes_count=50)
    assert r["readiness_label"] == LABEL_PROVISIONAL
    assert r["paper_outcome_progress"] == 0.5


def test_paper_outcome_readiness_100_outcomes():
    r = build_paper_outcome_collection_readiness(closed_paper_outcomes_count=100)
    assert r["readiness_label"] == LABEL_PAPER_CALIBRATED
    assert r["paper_outcome_progress"] == 1.0


def test_paper_outcome_readiness_linked_ratio():
    r = build_paper_outcome_collection_readiness(
        closed_paper_outcomes_count=10,
        linked_external_evidence_outcomes_count=5,
    )
    assert r["linked_evidence_progress"] == 0.5
    # bucket maturity bands
    r2 = build_paper_outcome_collection_readiness(
        closed_paper_outcomes_count=60,
        buckets=[
            {"sample_count": 2},   # cold
            {"sample_count": 10},  # early
            {"sample_count": 35},  # provisional
            {"sample_count": 80},  # mature
        ],
    )
    assert r2["cold_bucket_count"] == 1
    assert r2["early_bucket_count"] == 1
    assert r2["provisional_bucket_count"] == 1
    assert r2["mature_bucket_count"] == 1
    assert r2["bucket_count"] == 4
    assert r2["mature_bucket_ratio"] == 0.25


def test_paper_outcome_readiness_real_money_prohibited():
    for n in (0, 30, 50, 100, 250):
        r = build_paper_outcome_collection_readiness(closed_paper_outcomes_count=n)
        assert r["real_money_sizing_impact"] == "PROHIBITED"
        assert r["real_money_weight_allowed"] is False
        assert r["execution_gate"] == "LOCKED"
        assert r["broker_api_called"] is False
        assert r["ai_execution_count"] == 0


def test_paper_outcome_readiness_no_writes(tmp_path, monkeypatch):
    """Report mode (loader) performs no data mutation: an empty temp DB stays
    empty of outcome rows after a read."""
    import scripts.persistence as _persistence

    db_path = tmp_path / "report_only.db"
    monkeypatch.setattr(_persistence, "DB_PATH", str(db_path), raising=False)

    inputs = load_paper_outcome_inputs(db_path)
    assert inputs["closed_paper_outcomes_count"] == 0
    assert inputs["linked_external_evidence_outcomes_count"] == 0

    # A second read returns identical results — fully idempotent / read-only.
    inputs2 = load_paper_outcome_inputs(db_path)
    assert inputs2 == inputs

    # No external-evidence outcome rows were inserted by the report.
    import scripts.external_evidence_persistence as _eep

    conn = _eep._open(db_path)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM external_evidence_outcomes"
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 0


def test_daily_artifact_includes_outcome_readiness_summary():
    from scripts.daily_synthesis_pipeline import (
        _paper_outcome_readiness_summary,
        run_daily_synthesis,
    )

    summary = _paper_outcome_readiness_summary(
        build_paper_outcome_collection_readiness(closed_paper_outcomes_count=0)
    )
    assert summary["readiness_label"] == LABEL_COLD_START
    assert summary["real_money_sizing_impact"] == "PROHIBITED"

    # The live pipeline result surfaces the readiness block.
    result = run_daily_synthesis()
    assert "paper_outcome_collection_readiness" in result
    block = result["paper_outcome_collection_readiness"]
    assert block["real_money_sizing_impact"] == "PROHIBITED"
    assert block["readiness_label"] in {
        LABEL_COLD_START,
        LABEL_EARLY_SAMPLE,
        LABEL_PROVISIONAL,
        LABEL_PAPER_CALIBRATED,
    }


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
