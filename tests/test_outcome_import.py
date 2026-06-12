"""Outcome import + streak audit proofs: the bridge from doctrine to
evidence, and the guard against the model believing its own streak."""

from __future__ import annotations

import json

import pytest

from src.strategy.outcome_import import (
    ImportedOutcome,
    audit_streak,
    load_resolved_outcomes,
    streak_inputs_from_outcomes,
)


def case_row(**overrides) -> dict:
    row = {
        "id": "case_001", "ticker": "xyz",
        "entry_date": "2025-01-01", "entry_price": 100.0,
        "exit_date": "2025-03-01", "exit_price": 118.0,
        "benchmark_entry": 5000.0, "benchmark_exit": 5100.0,
        "narrative_phase_entry": "early",
        "narrative_phase_exit": "consensus",
        "predicted_edge": 0.18, "predicted_expiry_days": 45,
        "actual_resolution_days": 32,
        "thesis_tags": ["belief_gap", "capacity_runway"],
    }
    row.update(overrides)
    return row


# --- Import contract -----------------------------------------------------------
def test_mission_worked_example_imports_exactly() -> None:
    report = load_resolved_outcomes([case_row()])
    outcome = report.imported[0]
    assert outcome.ticker == "XYZ"
    assert outcome.asset_return == pytest.approx(0.18)
    assert outcome.benchmark_return == pytest.approx(0.02)
    assert outcome.realized_alpha == pytest.approx(0.16)
    assert outcome.prediction_error == pytest.approx(0.02)
    assert outcome.expiry_accuracy == pytest.approx(13.0)
    assert outcome.expired_before_resolution is False
    assert outcome.win is True
    assert outcome.holding_days == 59


def test_invalid_rows_fail_safely_without_poisoning_the_batch() -> None:
    rows = [
        case_row(),
        {"id": "bad_1", "ticker": "x"},  # missing almost everything
        case_row(id="bad_2", entry_price=-5.0),
        case_row(id="bad_3", exit_date="2024-01-01"),  # before entry
        "not even a dict",
    ]
    report = load_resolved_outcomes(rows)
    assert len(report.imported) == 1
    assert len(report.errors) == 4
    assert {e["row"] for e in report.errors} == {
        "bad_1", "bad_2", "bad_3", "4",
    }
    assert json.dumps(report.to_dict())


def test_optional_predictions_stay_none_not_zero() -> None:
    row = case_row()
    for key in ("predicted_edge", "predicted_expiry_days",
                "actual_resolution_days"):
        row.pop(key)
    outcome = load_resolved_outcomes([row]).imported[0]
    assert outcome.prediction_error is None
    assert outcome.expiry_accuracy is None
    assert outcome.expired_before_resolution is None


def test_negative_alpha_against_rising_benchmark() -> None:
    row = case_row(exit_price=104.0, benchmark_exit=5500.0)
    outcome = load_resolved_outcomes([row]).imported[0]
    # +4% asset return is still a LOSS against a +10% benchmark.
    assert outcome.realized_alpha == pytest.approx(-0.06)
    assert outcome.win is False


def test_summary_is_honest_about_thin_samples_and_tier() -> None:
    report = load_resolved_outcomes(
        [case_row(id=f"c{i}") for i in range(3)],
        data_tier="synthetic_fixture",
    )
    assert report.summary["status"] == "require_more_data"
    assert report.summary["data_tier"] == "synthetic_fixture"
    assert report.summary["mean_prediction_error"] == pytest.approx(0.02)
    assert any("plumbing" in r for r in report.summary["rationale"])


def test_unknown_tier_collapses_downward_never_upward() -> None:
    report = load_resolved_outcomes([case_row()], data_tier="live_feed")
    assert report.data_tier == "synthetic_fixture"


# --- Streak audit ----------------------------------------------------------------
def test_three_blind_wins_do_not_mint_conviction() -> None:
    audit = audit_streak(
        [{"win": True, "attributed": False, "confidence": 0.8}] * 3,
    )
    assert audit.win_rate == 1.0
    assert audit.streak_reliability == 0.0  # no named mechanism
    assert audit.hot_hand_risk == 1.0
    assert audit.causal_confidence <= 0.4  # synthetic tier cap
    assert "WINS_WITHOUT_ATTRIBUTION" in audit.warnings
    assert "SMALL_SAMPLE" in audit.warnings


def test_attributed_mechanism_beats_raw_streak() -> None:
    blind = audit_streak(
        [{"win": True, "attributed": False, "confidence": 0.6}] * 6,
    )
    causal = audit_streak(
        [{"win": True, "attributed": True, "confidence": 0.6}] * 6,
    )
    assert causal.streak_reliability == 1.0
    assert causal.hot_hand_risk < blind.hot_hand_risk
    assert "WINS_WITHOUT_ATTRIBUTION" not in causal.warnings


def test_confidence_cannot_exceed_calibration_tier() -> None:
    rows = [{"win": True, "attributed": True, "confidence": 0.9}] * 20
    synthetic = audit_streak(rows, data_tier="synthetic_fixture")
    backtest = audit_streak(rows, data_tier="backtest_replay")
    empirical = audit_streak(rows, data_tier="empirical")
    assert synthetic.causal_confidence == pytest.approx(0.40)
    assert backtest.causal_confidence == pytest.approx(0.60)
    assert empirical.causal_confidence == pytest.approx(0.90)
    assert "CONFIDENCE_CAPPED_BY_TIER_OR_RECORD" in synthetic.warnings


def test_overconfidence_gap_flags_confidence_above_record() -> None:
    audit = audit_streak(
        [{"win": i % 2 == 0, "attributed": True, "confidence": 0.85}
         for i in range(12)],
    )
    assert audit.win_rate == pytest.approx(0.5)
    assert audit.overconfidence_gap == pytest.approx(0.35)
    assert "OVERCONFIDENCE" in audit.warnings
    # Confidence is also capped by the realized record itself.
    assert audit.causal_confidence <= 0.5


def test_empty_history_reports_nothing_honestly() -> None:
    audit = audit_streak([])
    assert audit.sample_size == 0
    assert audit.causal_confidence == 0.0
    assert "NO_RESOLVED_OUTCOMES" in audit.warnings
    assert json.dumps(audit.to_dict())


def test_outcomes_bridge_into_streak_rows() -> None:
    report = load_resolved_outcomes([
        case_row(),
        case_row(id="c2", thesis_tags=[]),  # win of unknown cause
    ])
    rows = streak_inputs_from_outcomes(report.imported)
    assert rows[0]["win"] and rows[0]["attributed"]
    assert rows[1]["win"] and not rows[1]["attributed"]
    audit = audit_streak(rows, data_tier=report.data_tier)
    assert audit.attributed_wins == 1
    assert audit.streak_reliability == pytest.approx(0.5)
