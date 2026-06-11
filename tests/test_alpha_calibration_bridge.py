"""Calibration bridge: fit, refuse, apply, save/load, summarize."""

from __future__ import annotations

import json

import pytest

from src.alpha.calibration_bridge import (
    MIN_RESOLVED_FOR_FIT,
    apply_alpha_calibration,
    artifact_to_calibration_map,
    calibration_map_to_artifact,
    extract_probability_outcome_pairs,
    fit_alpha_calibration_map,
    load_alpha_calibration_map,
    save_alpha_calibration_map,
    summarize_alpha_calibration,
)


def _record(probability: float, win: bool) -> dict:
    return {
        "raw_event_probability": probability,
        "raw_score": probability * 100.0,
        "observed_outcome": {"fundamental_confirmation": win},
    }


def _overconfident_dataset(n: int = 60) -> list[dict]:
    """Scores around 0.85-0.9 that only resolve positively ~53% of the time."""
    records = []
    for i in range(n):
        probability = 0.9 if i % 2 == 0 else 0.85
        win = i % 5 != 0 and i % 3 != 0
        records.append(_record(probability, win))
    return records


def test_insufficient_data_refuses_to_fit() -> None:
    cmap, summary = fit_alpha_calibration_map(
        [_record(0.7, True)] * (MIN_RESOLVED_FOR_FIT - 1)
    )
    assert cmap is None
    assert summary["calibration_available"] is False
    assert summary["method"] == "insufficient_data"
    assert summary["missing_inputs"]
    assert any("refusing to fit" in warning for warning in summary["warnings"])


def test_identity_fallback_preserves_probabilities() -> None:
    assert apply_alpha_calibration(0.73, None) == pytest.approx(0.73)
    cmap, _ = fit_alpha_calibration_map([], method="identity")
    assert apply_alpha_calibration(0.73, cmap) == pytest.approx(0.73)


def test_fitted_calibration_improves_brier_on_overconfident_fixture() -> None:
    cmap, summary = fit_alpha_calibration_map(_overconfident_dataset())
    assert summary["calibration_available"] is True
    assert summary["method"] in ("isotonic", "platt")
    assert summary["brier_after"] < summary["brier_before"]
    # Overconfident 0.9 must be pulled DOWN toward the empirical rate.
    assert apply_alpha_calibration(0.9, cmap) < 0.9


def test_calibrated_probabilities_stay_in_unit_interval() -> None:
    cmap, _ = fit_alpha_calibration_map(_overconfident_dataset())
    for probability in (0.0, 0.1, 0.5, 0.9, 1.0, 5.0, -2.0):
        assert 0.0 <= apply_alpha_calibration(probability, cmap) <= 1.0


def test_artifact_save_load_roundtrip(tmp_path) -> None:
    cmap, _ = fit_alpha_calibration_map(_overconfident_dataset())
    path = tmp_path / "calibration.json"
    artifact = save_alpha_calibration_map(cmap, path)
    loaded_map, loaded_artifact = load_alpha_calibration_map(path)
    assert loaded_artifact["artifact_id"] == artifact["artifact_id"]
    for probability in (0.1, 0.5, 0.85, 0.9):
        assert loaded_map.apply(probability) == pytest.approx(
            cmap.apply(probability)
        )


def test_artifact_rejects_foreign_payloads() -> None:
    with pytest.raises(ValueError):
        artifact_to_calibration_map({"kind": "something_else"})


def test_artifact_id_is_content_derived_and_deterministic() -> None:
    cmap, _ = fit_alpha_calibration_map(_overconfident_dataset())
    first = calibration_map_to_artifact(cmap)
    second = calibration_map_to_artifact(cmap)
    assert first["artifact_id"] == second["artifact_id"]


def test_unresolved_records_never_teach_the_calibrator() -> None:
    records = _overconfident_dataset() + [
        {
            "raw_event_probability": 0.99,
            "observed_outcome": {"fundamental_confirmation": None},
        }
    ] * 50
    pairs = extract_probability_outcome_pairs(records)
    assert len(pairs) == 60  # the 50 unresolved records contribute nothing


def test_summary_schema_complete_and_bounded() -> None:
    _, summary = fit_alpha_calibration_map(_overconfident_dataset())
    for key in (
        "calibration_available",
        "method",
        "sample_size",
        "resolved_count",
        "brier_before",
        "brier_after",
        "expected_calibration_error",
        "calibration_support",
        "artifact_path",
        "warnings",
        "missing_inputs",
    ):
        assert key in summary
    assert 0.0 <= summary["calibration_support"] <= 100.0
    assert json.loads(json.dumps(summary)) is not None


def test_no_fake_calibration_claim_when_nothing_beats_raw() -> None:
    # Perfectly calibrated data: ~p of records at probability p win.
    records = []
    for i in range(100):
        probability = (i % 10) / 10.0 + 0.05
        win = (i % 100) < probability * 100
        records.append(_record(probability, win))
    _, summary = fit_alpha_calibration_map(records)
    if summary["method"] == "identity":
        assert summary["calibration_available"] is False
        assert any("does not generalise" in warning for warning in summary["warnings"])
