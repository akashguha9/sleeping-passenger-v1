"""Tests for contamination strictness in moltbook feedback summaries.

A SUCCESS_VALID_SIGNAL case that carries serious data_quality_flags
(seeded truth_origin, missing feedback, data gaps, legacy_incomplete,
placeholder, missing_mark) must:
  * be counted in ``contaminated_case_count``
  * reduce ``clean_success_rate`` below ``raw_success_rate``
  * trigger ``learning_quality_warning``
  * inflate ``effective_data_quality_failure_ratio`` above
    ``data_quality_failure_ratio``
"""
from __future__ import annotations

from scripts.moltbook_feedback import MoltbookFeedbackCase, build_feedback_summary


FIXED_TIMESTAMP = "2026-04-24T00:00:00+00:00"


def _case(
    case_id: str,
    classification: str,
    data_quality_flags: list[str] | None = None,
    asset: str = "RTX",
) -> MoltbookFeedbackCase:
    return MoltbookFeedbackCase(
        case_id=case_id,
        created_at_utc=FIXED_TIMESTAMP,
        trade_id=f"trade_{case_id}",
        asset=asset,
        symbol=asset,
        side="BUY",
        direction="LONG",
        entry_time=FIXED_TIMESTAMP,
        exit_time=FIXED_TIMESTAMP,
        holding_period_seconds=60.0,
        expected_outcome="positive_return",
        actual_outcome="positive_return" if classification == "SUCCESS_VALID_SIGNAL" else "negative_return",
        pnl=1.0 if classification == "SUCCESS_VALID_SIGNAL" else -1.0,
        return_pct=1.0 if classification == "SUCCESS_VALID_SIGNAL" else -1.0,
        classification=classification,
        classification_confidence=0.8,
        primary_reason="test",
        contributing_reasons=[],
        data_quality_flags=list(data_quality_flags or []),
        truth_origin="seeded",
        operating_mode="seeded",
        suggested_adjustment="fix" if classification.startswith("FAIL_") else "",
    )


def test_clean_successes_produce_raw_equal_to_clean_rate():
    cases = [
        _case("c1", "SUCCESS_VALID_SIGNAL"),
        _case("c2", "SUCCESS_VALID_SIGNAL"),
        _case("c3", "FAIL_DATA_QUALITY", ["data_gap_unresolved"]),
    ]
    summary = build_feedback_summary(cases)
    assert summary["raw_success_rate"] == summary["clean_success_rate"]
    assert summary["contaminated_success_count"] == 0
    assert summary["learning_quality_warning"] is None or (
        summary["contaminated_case_count"] > 0
        and "contaminated" in summary["learning_quality_warning"].lower()
    )


def test_contaminated_success_is_subtracted_from_clean_rate():
    cases = [
        _case("c1", "SUCCESS_VALID_SIGNAL", ["truth_origin_seeded", "missing_feedback"]),
        _case("c2", "SUCCESS_VALID_SIGNAL"),
        _case("c3", "FAIL_DATA_QUALITY", ["data_gap_unresolved"]),
    ]
    summary = build_feedback_summary(cases)
    assert summary["total_cases"] == 3
    assert summary["raw_success_rate"] > summary["clean_success_rate"]
    assert summary["contaminated_success_count"] == 1
    assert summary["contaminated_case_count"] == 2  # c1 and c3 both flagged
    assert summary["clean_success_count"] == 1
    assert summary["learning_quality_warning"] is not None
    assert "successes carry" in summary["learning_quality_warning"]


def test_effective_data_quality_failure_ratio_captures_contamination():
    cases = [
        _case("c1", "SUCCESS_VALID_SIGNAL", ["truth_origin_seeded"]),
        _case("c2", "FAIL_DATA_QUALITY", ["data_gap_unresolved"]),
    ]
    summary = build_feedback_summary(cases)
    # Original field still reflects explicit FAIL_DATA_QUALITY only: 1/2 = 0.5
    assert summary["data_quality_failure_ratio"] == 0.5
    # Effective field blends in contaminated cases: (1 + 2 contaminated) / 2 = 1.5 -> 1.0
    # Both cases are contaminated-or-explicitly-failed, so effective = 1.0.
    assert summary["effective_data_quality_failure_ratio"] >= summary["data_quality_failure_ratio"]
    assert summary["effective_data_quality_failure_ratio"] == 1.0


def test_backward_compatibility_success_rate_fields_preserved():
    cases = [_case("c1", "SUCCESS_VALID_SIGNAL")]
    summary = build_feedback_summary(cases)
    # Legacy fields remain.
    assert "success_rate" in summary
    assert "feedback_success_rate" in summary
    assert summary["success_rate"] == summary["raw_success_rate"]
    assert summary["feedback_success_rate"] == summary["raw_success_rate"]
    # New fields are additive.
    assert "clean_success_rate" in summary
    assert "contaminated_case_count" in summary
    assert "contaminated_success_count" in summary


def test_empty_cases_returns_zero_and_no_warning():
    summary = build_feedback_summary([])
    assert summary["total_cases"] == 0
    assert summary["raw_success_rate"] == 0.0
    assert summary["clean_success_rate"] == 0.0
    assert summary["contaminated_case_count"] == 0
    assert summary["contaminated_success_count"] == 0
    assert summary["learning_quality_warning"] is None


def test_contaminated_non_success_triggers_fleet_warning():
    # Three cases, all non-success, two with flags.
    cases = [
        _case("c1", "FAIL_SIGNAL", ["truth_origin_seeded"]),
        _case("c2", "FAIL_TIMING", ["data_gap_unresolved"]),
        _case("c3", "INCONCLUSIVE"),
    ]
    summary = build_feedback_summary(cases)
    assert summary["contaminated_success_count"] == 0
    assert summary["contaminated_case_count"] == 2
    # With >= 3 cases and no contaminated successes, we still warn because
    # evidence quality is compromised.
    assert summary["learning_quality_warning"] is not None
    assert "contaminated" in summary["learning_quality_warning"].lower()
