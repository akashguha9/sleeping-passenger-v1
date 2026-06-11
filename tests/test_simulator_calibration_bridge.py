"""Calibration bridge tests: Brier/ECE reuse, segment drift, safe proposals.

The bridge must (a) reuse the journal's canonical metric implementations,
(b) never claim fixture replay is empirical, and (c) never mark autotune
safe outside the strict gate.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from scripts.calibration_map import _brier, _ece
from src.simulator.calibration_bridge import (
    CRASH_BETA_MAX,
    CRASH_BETA_MIN,
    HALF_LIFE_LAMBDA,
    MODE_EMPIRICAL,
    MODE_FIXTURE,
    MODE_INSUFFICIENT,
    autotune_safety_gate,
    build_calibration_report,
    propose_crash_beta,
    propose_half_life,
)
from src.simulator.telemetry import load_telemetry_rows

FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "simulator_replay_fixture.jsonl"
)


def _row(
    predicted: float,
    actual: float,
    *,
    compound: str = "hard",
    bucket: str = "low",
    data_source: str = "caller_payload",
) -> dict:
    return {
        "predicted_probability": predicted,
        "actual_outcome_placeholder": actual,
        "calibration_status": "resolved",
        "data_source": data_source,
        "segments": {
            "circuit": "mid_cap",
            "signal_compound": compound,
            "exposure_class": "direct_beneficiary",
            "crash_density_bucket": bucket,
            "driver_license": "pro_am",
            "narrative_state": "emerging",
        },
    }


def test_empty_rows_report_insufficient_data() -> None:
    report = build_calibration_report([])
    assert report.calibration_mode == MODE_INSUFFICIENT
    assert report.sample_size == 0
    assert report.brier is None
    assert report.unsafe_to_autotune is True


def test_unresolved_rows_are_excluded() -> None:
    rows = [
        {"predicted_probability": 0.7, "actual_outcome_placeholder": None},
        {"predicted_probability": None, "actual_outcome_placeholder": 1.0},
        {
            "predicted_probability": 0.7,
            "actual_outcome_placeholder": 1.0,
            "calibration_status": "pending",
        },
    ]
    assert build_calibration_report(rows).sample_size == 0


def test_brier_and_ece_match_repo_canonical_implementations() -> None:
    rows = [_row(0.8, 1.0), _row(0.3, 0.0), _row(0.6, 1.0)] * 4
    report = build_calibration_report(rows)
    predictions = [0.8, 0.3, 0.6] * 4
    outcomes = [1.0, 0.0, 1.0] * 4
    assert report.brier == pytest.approx(_brier(predictions, outcomes))
    assert report.ece == pytest.approx(_ece(predictions, outcomes))


def test_fixture_rows_never_report_empirical() -> None:
    rows = [_row(0.6, 1.0) for _ in range(20)]
    rows.append(_row(0.6, 1.0, data_source="fixture_replay"))
    report = build_calibration_report(rows)
    assert report.calibration_mode == MODE_FIXTURE
    assert report.fixture_rows == 1
    assert report.unsafe_to_autotune is True
    assert any("fixture" in b or "empirical" in b for b in report.autotune_blockers)


def test_segment_drift_is_segment_minus_global() -> None:
    # Soft rows overpredict (+0.5 error); hard rows perfect (0 error).
    rows = [_row(0.5, 0.0, compound="soft") for _ in range(10)]
    rows += [_row(1.0, 1.0, compound="hard") for _ in range(10)]
    report = build_calibration_report(rows)
    by_compound = {
        s.segment_value: s for s in report.error_by_segment["signal_compound"]
    }
    global_mean = report.global_mean_error
    assert by_compound["soft"].drift_vs_global == pytest.approx(0.5 - global_mean)
    assert by_compound["hard"].drift_vs_global == pytest.approx(0.0 - global_mean)


def test_half_life_proposal_follows_exponential_law() -> None:
    h_new = propose_half_life(18.0, 0.3)
    assert h_new == pytest.approx(18.0 * math.exp(-HALF_LIFE_LAMBDA * 0.3))
    # Bounds respected for extreme drift.
    assert propose_half_life(18.0, 10.0) == pytest.approx(18.0 * 0.25)
    assert propose_half_life(18.0, -10.0) == pytest.approx(18.0 * 4.0)


def test_crash_beta_proposal_is_clamped() -> None:
    assert propose_crash_beta(0.5, 0.5) == pytest.approx(0.6)
    assert propose_crash_beta(0.5, 100.0) == CRASH_BETA_MAX
    assert propose_crash_beta(0.5, -100.0) == CRASH_BETA_MIN


def test_overconfident_soft_segment_gets_shorter_half_life_proposal() -> None:
    rows = [_row(0.8, 0.0, compound="soft") for _ in range(12)]
    rows += [_row(0.5, 0.5, compound="hard") for _ in range(12)]
    report = build_calibration_report(rows)
    proposals = report.recommended_adjustments.get("half_life_hours", {})
    assert "soft" in proposals
    assert proposals["soft"]["h_new_hours"] < proposals["soft"]["h_old_hours"]
    assert report.recommended_adjustments["applied"] is False
    assert report.recommended_adjustments["auto_apply"] is False


def test_crashy_bucket_residual_raises_beta_proposal() -> None:
    rows = [_row(0.8, 0.0, bucket="extreme") for _ in range(12)]
    report = build_calibration_report(rows)
    beta = report.recommended_adjustments.get("crash_pair_beta")
    assert beta is not None
    assert beta["beta_new"] > beta["beta_old"]


def test_autotune_gate_requires_everything() -> None:
    safe, blockers = autotune_safety_gate(
        calibration_mode=MODE_EMPIRICAL, sample_size=100, ece=0.05
    )
    assert safe and not blockers
    for mode, n, ece in (
        (MODE_FIXTURE, 100, 0.05),
        (MODE_EMPIRICAL, 10, 0.05),
        (MODE_EMPIRICAL, 100, 0.5),
        (MODE_EMPIRICAL, 100, None),
    ):
        safe, blockers = autotune_safety_gate(
            calibration_mode=mode, sample_size=n, ece=ece
        )
        assert not safe and blockers


def test_committed_fixture_replays_deterministically() -> None:
    rows = load_telemetry_rows(FIXTURE_PATH)
    assert len(rows) == 48
    assert all(r["data_source"] == "fixture_replay" for r in rows)
    report = build_calibration_report(rows)
    assert report.calibration_mode == MODE_FIXTURE
    assert report.sample_size == 48
    assert report.unsafe_to_autotune is True
    # Per-compound proposals exist (12 rows per compound in the fixture).
    assert "half_life_hours" in report.recommended_adjustments
    # Determinism: same input, same numbers.
    again = build_calibration_report(rows)
    assert again.brier == report.brier
    assert again.ece == report.ece


def test_report_is_json_serializable_with_required_contract_keys() -> None:
    report = build_calibration_report(
        [_row(0.7, 1.0) for _ in range(12)]
    ).to_dict()
    for key in (
        "sample_size", "calibration_mode", "error_by_segment",
        "recommended_adjustments", "unsafe_to_autotune", "advisory_note",
    ):
        assert key in report
    json.dumps(report)
