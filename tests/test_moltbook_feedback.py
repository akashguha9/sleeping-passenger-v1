from __future__ import annotations

from pathlib import Path

import scripts.run_diagnostics_pipeline as run_diagnostics_pipeline_module
from scripts.moltbook_feedback import (
    MoltbookFeedbackCase,
    append_feedback_case,
    build_feedback_case_from_reconciliation_row,
    build_feedback_summary,
    load_feedback_cases,
)
from scripts.pipeline_health_report import format_pipeline_health_summary


FIXED_TIMESTAMP = "2026-04-24T00:00:00+00:00"
REPO_ROOT = Path(__file__).resolve().parents[1]


def _base_reconciliation_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "ticker": "RTX",
        "signal_id": "SIG_TEST_001",
        "close_id": "paper_close_test_001",
        "position_id": "paper_position_test_001",
        "paper_fill_id": "paper_fill_test_001",
        "side": "BUY",
        "entry_time": "2026-04-24T00:00:00+00:00",
        "exit_time": "2026-04-24T00:30:00+00:00",
        "realized_pnl": 2.5,
        "realized_return_pct": 2.5,
        "close_reason": "target_hit",
        "thesis_state": "confirmed",
        "truth_origin": "external",
        "operating_mode": "hybrid",
        "reconciliation_status": "partially_reconciled",
        "mark_source": "yahoo_finance",
        "mark_staleness": "fresh",
        "source_quality_note": "timestamped paper reconciliation",
        "data_gap_flags": [],
        "holding_period_days": 0.02,
        "mfe": None,
        "entry_delay_seconds": None,
        "exit_delay_seconds": None,
    }
    row.update(overrides)
    return row


def _make_case(classification: str, *, case_id: str, asset: str = "RTX") -> MoltbookFeedbackCase:
    return MoltbookFeedbackCase(
        case_id=case_id,
        created_at_utc=FIXED_TIMESTAMP,
        trade_id=case_id.replace("feedback_case_", "trade_"),
        asset=asset,
        symbol=asset,
        side="BUY",
        direction="LONG",
        entry_time=FIXED_TIMESTAMP,
        exit_time="2026-04-24T00:10:00+00:00",
        holding_period_seconds=600.0,
        expected_outcome="positive_return",
        actual_outcome="negative_return" if classification.startswith("FAIL_") else "positive_return",
        pnl=-1.0 if classification.startswith("FAIL_") else 1.0,
        return_pct=-1.0 if classification.startswith("FAIL_") else 1.0,
        classification=classification,
        classification_confidence=0.7,
        primary_reason="test reason",
        contributing_reasons=["test_reason"],
        data_quality_flags=[],
        truth_origin="external",
        operating_mode="hybrid",
        regime_context={},
        signal_context={},
        operator_override_context={},
        source_context={},
        suggested_adjustment="test adjustment",
    )


def test_feedback_case_classifies_success_valid_signal() -> None:
    case = build_feedback_case_from_reconciliation_row(
        _base_reconciliation_row(),
        generated_at_utc=FIXED_TIMESTAMP,
    )

    assert case.classification == "SUCCESS_VALID_SIGNAL"
    assert case.classification_confidence == 0.9
    assert case.suggested_adjustment == (
        "Preserve this setup pattern but continue collecting paper evidence."
    )


def test_feedback_case_classifies_fail_signal() -> None:
    case = build_feedback_case_from_reconciliation_row(
        _base_reconciliation_row(
            ticker="ZIM",
            signal_id="SIG_TEST_002",
            close_id="paper_close_test_002",
            realized_pnl=-4.0,
            realized_return_pct=-4.0,
            close_reason="stop_hit",
            thesis_state="invalidated",
        ),
        generated_at_utc=FIXED_TIMESTAMP,
    )

    assert case.classification == "FAIL_SIGNAL"
    assert case.classification_confidence == 0.9
    assert "directional_contradiction" in case.contributing_reasons


def test_feedback_case_classifies_fail_timing() -> None:
    case = build_feedback_case_from_reconciliation_row(
        _base_reconciliation_row(
            close_id="paper_close_test_003",
            realized_pnl=0.1,
            realized_return_pct=0.1,
            close_reason="flat_exit",
            thesis_state="partial",
            mfe=3.2,
        ),
        generated_at_utc=FIXED_TIMESTAMP,
    )

    assert case.classification == "FAIL_TIMING"
    assert case.classification_confidence == 0.9
    assert "favorable_excursion_not_captured" in case.contributing_reasons


def test_feedback_case_classifies_fail_data_quality_when_outcome_missing() -> None:
    case = build_feedback_case_from_reconciliation_row(
        _base_reconciliation_row(
            close_id="paper_close_test_004",
            realized_pnl=None,
            realized_return_pct=None,
            close_reason="",
            thesis_state="",
            truth_origin="seeded",
            operating_mode="seeded",
            reconciliation_status="data_gap_unresolved",
            source_quality_note="placeholder external observation only",
            data_gap_flags=["missing_exit_mark"],
        ),
        generated_at_utc=FIXED_TIMESTAMP,
    )

    assert case.classification == "FAIL_DATA_QUALITY"
    assert case.classification_confidence == 0.5
    assert "truth_origin_seeded" in case.data_quality_flags
    assert "missing_exit_mark" in case.data_quality_flags


def test_build_feedback_summary_empty_state_returns_no_feedback() -> None:
    summary = build_feedback_summary([])

    assert summary["feedback_learning_state"] == "NO_FEEDBACK"
    assert summary["feedback_cases_total"] == 0
    assert summary["feedback_readiness_penalty"] == 0.0


def test_build_feedback_summary_detects_failure_cluster() -> None:
    cases = [
        _make_case("FAIL_TIMING", case_id=f"feedback_case_fail_{index}", asset="RTX")
        for index in range(6)
    ] + [
        _make_case("SUCCESS_VALID_SIGNAL", case_id=f"feedback_case_success_{index}", asset="ZIM")
        for index in range(4)
    ]

    summary = build_feedback_summary(cases)

    assert summary["feedback_learning_state"] == "FAILURE_CLUSTER_DETECTED"
    assert summary["feedback_top_failure_mode"] == "FAIL_TIMING"
    assert summary["feedback_readiness_penalty"] == 0.25


def test_feedback_jsonl_roundtrip() -> None:
    scratch_dir = REPO_ROOT / "tests" / "_tmp_runtime"
    feedback_path = scratch_dir / "moltbook_feedback_cases_roundtrip.jsonl"
    first_case = _make_case("SUCCESS_VALID_SIGNAL", case_id="feedback_case_001")
    second_case = _make_case("FAIL_SIGNAL", case_id="feedback_case_002", asset="ZIM")

    scratch_dir.mkdir(exist_ok=True)
    if feedback_path.exists():
        feedback_path.unlink()

    try:
        append_feedback_case(first_case, feedback_path)
        append_feedback_case(second_case, feedback_path)
        rows = load_feedback_cases(feedback_path)

        assert [row["case_id"] for row in rows] == ["feedback_case_001", "feedback_case_002"]
        assert rows[1]["classification"] == "FAIL_SIGNAL"
        assert rows[1]["asset"] == "ZIM"
    finally:
        if feedback_path.exists():
            feedback_path.unlink()
        if scratch_dir.exists() and not any(scratch_dir.iterdir()):
            scratch_dir.rmdir()


def test_run_diagnostics_pipeline_exposes_feedback_fields(monkeypatch) -> None:
    fake_feedback_report = {
        "moltbook_feedback_available": True,
        "feedback_learning_state": "INSUFFICIENT_FEEDBACK",
        "feedback_cases_total": 3,
        "feedback_success_rate": 0.3333,
        "feedback_top_failure_mode": "FAIL_TIMING",
        "feedback_readiness_penalty": 0.05,
        "suggested_feedback_adjustments": [
            "Increase timing confirmation threshold before promotion.",
            "Collect more reconciled paper outcomes before upgrading readiness.",
        ],
    }
    monkeypatch.setattr(
        run_diagnostics_pipeline_module,
        "build_moltbook_feedback_report",
        lambda **_: fake_feedback_report,
    )

    payload = run_diagnostics_pipeline_module.run_diagnostics_pipeline(write_runtime=False)
    summary = format_pipeline_health_summary(payload)

    assert payload["feedback_learning_state"] == "INSUFFICIENT_FEEDBACK"
    assert payload["feedback_cases_total"] == 3
    assert payload["feedback_top_failure_mode"] == "FAIL_TIMING"
    assert payload["moltbook_feedback_available"] is True
    assert "feedback_learning_state=INSUFFICIENT_FEEDBACK" in summary
    assert "feedback_top_failure_mode=FAIL_TIMING" in summary
    assert "moltbook_feedback_available=true" in summary
