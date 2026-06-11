"""Operator checklist: what journaling unlocks calibration."""

from __future__ import annotations

from src.alpha.operator_checklist import (
    MINIMUM_RECORDS_FOR_CALIBRATION,
    build_operator_checklist,
)


def _bridge(records, discovered=None, skip_reasons=None):
    return {
        "records": records,
        "discovered_records": discovered if discovered is not None else len(records),
        "skip_reasons": skip_reasons or {},
    }


def _full_record() -> dict:
    return {
        "as_of_date": "2026-01-05T10:00:00+00:00",
        "ticker": "EXMPL",
        "raw_score": 62.0,
        "verdict": "deep_research",
        "subsequent_observation_window_days": 30,
        "observed_outcome": {
            "price_return": 0.04,
            "drawdown": -0.02,
            "fundamental_confirmation": True,
            "narrative_persistence": 0.7,
            "filing_confirmation": True,
        },
    }


def test_empty_journal_needs_full_floor() -> None:
    checklist = build_operator_checklist(bridge_result=_bridge([]))
    assert checklist["records_needed"] == MINIMUM_RECORDS_FOR_CALIBRATION
    assert checklist["current_resolved_records"] == 0
    assert checklist["data_quality_score"] == 0.0
    assert len(checklist["missing_fields"]) == len(checklist["required_fields"])
    assert any("Journal and reconcile" in action for action in checklist["next_actions"])


def test_partial_journal_reports_missing_fields() -> None:
    sparse = _full_record()
    sparse["observed_outcome"]["drawdown"] = None
    sparse["observed_outcome"]["narrative_persistence"] = None
    checklist = build_operator_checklist(bridge_result=_bridge([sparse] * 10))
    assert "drawdown" in checklist["missing_fields"]
    assert "narrative_persistence" in checklist["missing_fields"]
    assert "ticker" not in checklist["missing_fields"]
    assert any("drawdown" in action for action in checklist["next_actions"])


def test_sufficient_complete_journal_raises_quality_score() -> None:
    sparse = build_operator_checklist(bridge_result=_bridge([_full_record()] * 5))
    full = build_operator_checklist(
        bridge_result=_bridge([_full_record()] * MINIMUM_RECORDS_FOR_CALIBRATION)
    )
    assert full["data_quality_score"] > sparse["data_quality_score"]
    assert full["records_needed"] == 0
    assert full["data_quality_score"] == 100.0
    assert any("re-fit calibration" in action.lower() for action in full["next_actions"])


def test_skip_reasons_drive_specific_actions() -> None:
    checklist = build_operator_checklist(
        bridge_result=_bridge(
            [_full_record()],
            discovered=10,
            skip_reasons={"open_or_unknown_outcome": 7, "missing_score_at_entry": 2},
        )
    )
    assert any("Reconcile 7 open" in action for action in checklist["next_actions"])
    assert any("score_at_entry for 2" in action for action in checklist["next_actions"])


def test_absent_db_does_not_crash(tmp_path) -> None:
    checklist = build_operator_checklist(tmp_path / "missing.db")
    assert checklist["current_resolved_records"] == 0
    assert checklist["records_needed"] == MINIMUM_RECORDS_FOR_CALIBRATION


def test_quality_score_bounded_and_advisory() -> None:
    checklist = build_operator_checklist(
        bridge_result=_bridge([_full_record()] * 200)
    )
    assert 0.0 <= checklist["data_quality_score"] <= 100.0
    assert "Advisory-only" in checklist["disclaimer"]
