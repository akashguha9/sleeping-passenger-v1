"""Post-outcome review proofs (Pass 4, Phase 11) — synthetic predictions."""
from __future__ import annotations

import pytest

from scripts import review_signal_outcomes as rev


def test_error_formulas_exact():
    r = rev.review_sample({"signal_id": "S1", "p": 0.8, "y": 0,
                           "expected_return": 0.05, "actual_return": -0.02})
    assert r["error"] == pytest.approx(-0.8)
    assert r["absolute_error"] == pytest.approx(0.8)
    assert r["prediction_error"] == pytest.approx(-0.07)
    assert any("overconfident" in l for l in r["lessons"])


def test_underconfidence_detected():
    r = rev.review_sample({"p": 0.2, "y": 1})
    assert any("underconfident" in l for l in r["lessons"])


def test_mae_and_bias_known_answers():
    samples = [
        {"p": 0.6, "y": 1, "expected_return": 0.05, "actual_return": 0.02},
        {"p": 0.6, "y": 0, "expected_return": 0.05, "actual_return": -0.01},
    ]
    report = rev.aggregate_review(samples)
    # PredictionErrors: -0.03, -0.06 → MAE 0.045, Bias -0.045
    assert report["mae_return"] == pytest.approx(0.045)
    assert report["bias_return"] == pytest.approx(-0.045)
    assert any("optimistic" in l for l in report["top_lessons"])
    assert report["thesis_hit_rate"] == pytest.approx(0.5)
    assert report["advisory_only"] is True


def test_stale_evidence_flagged():
    r = rev.review_sample({"p": 0.6, "y": 1, "evidence_age_days_at_decision": 30})
    assert r["evidence_was_stale"] is True
    assert any("stale" in l.lower() for l in r["lessons"])
    fresh = rev.review_sample({"p": 0.6, "y": 1, "evidence_age_days_at_decision": 2})
    assert fresh["evidence_was_stale"] is False


def test_abstention_hindsight_recorded():
    r = rev.review_sample({"p": 0.7, "y": 0, "stability_recommendation": "ABSTAIN"})
    assert r.get("should_have_abstained") is True


def test_benchmark_underperformance_lesson():
    r = rev.review_sample({"p": 0.7, "y": 1, "actual_return": 0.02,
                           "benchmark_return": 0.05})
    assert r["excess_vs_benchmark"] == pytest.approx(-0.03)
    assert any("benchmark" in l for l in r["lessons"])


def test_overweighted_feature_lesson_on_failure():
    r = rev.review_sample({"p": 0.7, "y": 0, "dominant_feature": "narrative_velocity"})
    assert any("narrative_velocity" in l for l in r["lessons"])


@pytest.mark.parametrize("bad", [{"p": 1.3, "y": 1}, {"p": 0.5, "y": 2}])
def test_malformed_input_rejected(bad):
    with pytest.raises(rev.ReviewError):
        rev.review_sample(bad)


def test_aggregate_handles_missing_fields():
    report = rev.aggregate_review([{"signal_id": "S1"}])
    assert report["n_reviewed"] == 1
    assert report["mae_return"] is None
    assert report["thesis_hit_rate"] is None
