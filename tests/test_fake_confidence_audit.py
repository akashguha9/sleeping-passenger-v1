"""Tests for the fake-confidence defensive layer (WORKSTREAM D)."""
from __future__ import annotations

import pytest

from scripts import fake_confidence_audit as fca


def test_overconfidence_score_math() -> None:
    """OCR = 0.50*false + 0.30*harm + 0.20*max(weight-help, 0), clipped [0,1]."""
    out = fca.compute_overconfidence(
        sample_count=40,
        advisory_weight=0.9,
        help_rate=0.2,
        harm_rate=0.4,
        false_confidence_rate=0.6,
    )
    expected = 0.50 * 0.6 + 0.30 * 0.4 + 0.20 * max(0.9 - 0.2, 0.0)
    assert out["overconfidence_score"] == pytest.approx(min(expected, 1.0))
    assert out["confidence_gap"] == pytest.approx(0.7)


def test_high_fake_confidence_blocks_positive_delta() -> None:
    out = fca.compute_overconfidence(
        sample_count=50,
        advisory_weight=1.0,
        help_rate=0.05,
        harm_rate=0.8,
        false_confidence_rate=0.9,
    )
    assert out["overconfidence_score"] >= fca.HIGH_RISK_THRESHOLD
    assert out["fake_confidence_label"] == fca.LABEL_HIGH
    assert out["positive_delta_allowed"] is False

    blocked = fca.apply_fake_confidence_block(0.5, out["overconfidence_score"], 50)
    assert blocked["positive_delta_blocked"] is True
    assert blocked["delta_out"] == 0.0

    # A negative delta (risk reduction) still passes through under HIGH risk.
    neg = fca.apply_fake_confidence_block(-0.7, out["overconfidence_score"], 50)
    assert neg["positive_delta_blocked"] is False
    assert neg["delta_out"] == pytest.approx(-0.7)


def test_cold_start_labeled_unknown() -> None:
    out = fca.compute_overconfidence(
        sample_count=3, advisory_weight=1.0, harm_rate=0.9, false_confidence_rate=0.9
    )
    assert out["fake_confidence_label"] == fca.LABEL_COLD_START
    # Cold start is UNKNOWN, not LOW — absence of harm data is not safety.
    assert out["fake_confidence_label"] != fca.LABEL_LOW
    # Cold start does not (by itself) block a positive delta.
    blocked = fca.apply_fake_confidence_block(0.4, out["overconfidence_score"], 3)
    assert blocked["positive_delta_blocked"] is False


def test_harm_rate_damps_weight() -> None:
    """Higher harm rate -> higher OCR -> closer to a block."""
    low = fca.compute_overconfidence(
        sample_count=40, advisory_weight=0.5, help_rate=0.5, harm_rate=0.0,
        false_confidence_rate=0.0,
    )
    high = fca.compute_overconfidence(
        sample_count=40, advisory_weight=0.5, help_rate=0.5, harm_rate=0.9,
        false_confidence_rate=0.0,
    )
    assert high["overconfidence_score"] > low["overconfidence_score"]


def test_false_confidence_rate_damps_weight() -> None:
    low = fca.compute_overconfidence(
        sample_count=40, advisory_weight=0.5, help_rate=0.5, harm_rate=0.0,
        false_confidence_rate=0.0,
    )
    high = fca.compute_overconfidence(
        sample_count=40, advisory_weight=0.5, help_rate=0.5, harm_rate=0.0,
        false_confidence_rate=0.9,
    )
    assert high["overconfidence_score"] > low["overconfidence_score"]
    # False-confidence is weighted most heavily (0.50).
    assert high["overconfidence_score"] >= 0.45


def test_summary_honest_when_empty() -> None:
    summary = fca.build_fake_confidence_summary([])
    assert summary["data_available"] is False
    assert summary["overall_fake_confidence_label"] == fca.LABEL_COLD_START
    assert summary["real_money_sizing_impact"] == "PROHIBITED"
    assert summary["advisory_status"] == "ADVISORY_ONLY"


def test_summary_identifies_worst_bucket() -> None:
    buckets = [
        {
            "bucket_id": "good|T|WATCH|MID", "source_name": "good",
            "sample_count": 60, "advisory_weight": 0.4, "help_rate": 0.7,
            "harm_rate": 0.0, "false_confidence_rate": 0.0,
        },
        {
            "bucket_id": "bad|T|WATCH|HIGH", "source_name": "bad",
            "sample_count": 60, "advisory_weight": 1.0, "help_rate": 0.1,
            "harm_rate": 0.8, "false_confidence_rate": 0.9,
        },
    ]
    summary = fca.build_fake_confidence_summary(buckets)
    assert summary["data_available"] is True
    assert summary["overall_fake_confidence_label"] == fca.LABEL_HIGH
    assert summary["worst_source_bucket"]["source_name"] == "bad"
    assert summary["best_source_bucket"]["source_name"] == "good"
