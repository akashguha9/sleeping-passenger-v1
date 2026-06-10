"""Calibration metric proofs (Pass 4, Phase 6) — known mathematical answers."""
from __future__ import annotations

import pytest

from scripts import model_calibration as mc


def test_brier_known_values():
    # Perfect: p=y everywhere → 0. Worst confident: |p-y|=1 → 1.
    assert mc.brier_score([1.0, 0.0], [1, 0]) == 0.0
    assert mc.brier_score([1.0, 0.0], [0, 1]) == 1.0
    assert mc.brier_score([0.7], [1]) == pytest.approx(0.09)


def test_log_loss_finite_and_ordered():
    good = mc.log_loss([0.9, 0.1], [1, 0])
    bad = mc.log_loss([0.1, 0.9], [1, 0])
    assert good < bad
    # Confident-and-wrong is brutal but finite (epsilon clipping).
    assert mc.log_loss([1.0], [0]) < float("inf")


def test_perfect_calibration_gives_low_ece():
    # 50 samples at p=0.8 with exactly 80% hits, 50 at p=0.2 with 20% hits.
    probs = [0.8] * 50 + [0.2] * 50
    outcomes = [1] * 40 + [0] * 10 + [1] * 10 + [0] * 40
    assert mc.expected_calibration_error(probs, outcomes) == pytest.approx(0.0, abs=1e-9)


def test_overconfident_model_has_worse_ece():
    outcomes = [1] * 30 + [0] * 70
    honest = [0.3] * 100          # claims 0.3, base rate is 0.3
    overconfident = [0.9] * 100   # claims 0.9, base rate is 0.3
    assert mc.expected_calibration_error(overconfident, outcomes) > \
        mc.expected_calibration_error(honest, outcomes) + 0.5


@pytest.mark.parametrize("bad_p", [-0.01, 1.01, float("nan")])
def test_probabilities_outside_unit_interval_rejected(bad_p):
    with pytest.raises(mc.CalibrationError):
        mc.brier_score([bad_p], [1])


def test_outcomes_must_be_binary():
    with pytest.raises(mc.CalibrationError):
        mc.brier_score([0.5], [2])  # type: ignore[list-item]


def test_empty_bins_handled_safely():
    bins = mc.reliability_bins([0.05] * 20, [0] * 20, n_bins=10)
    populated = [b for b in bins if b["n"]]
    assert len(populated) == 1
    empty = [b for b in bins if not b["n"]]
    assert all(b["gap"] is None for b in empty)
    # ECE over mostly-empty bins still computes.
    assert mc.expected_calibration_error([0.05] * 20, [0] * 20) == pytest.approx(0.05)


def test_small_sample_warnings():
    summary = mc.calibration_summary([0.6] * 12, [1] * 12)
    assert any("SMALL SAMPLE" in w for w in summary["warnings"])
    with pytest.raises(mc.CalibrationError):
        mc.expected_calibration_error([0.6] * 5, [1] * 5)  # N < 10 refused
    tiny = mc.calibration_summary([0.6] * 5, [1] * 5)
    assert tiny["ece"] is None  # refused, not faked


def test_abstention_analysis_known_tradeoff():
    # 0.95s always right; 0.55s coin flips → higher τ = better accuracy, less coverage.
    probs = [0.95] * 10 + [0.55] * 10
    outcomes = [1] * 10 + [1, 0] * 5
    rows = {r["threshold"]: r for r in mc.abstention_analysis(probs, outcomes)}
    assert rows[0.9]["coverage"] == pytest.approx(0.5)
    assert rows[0.9]["accuracy_on_kept"] == pytest.approx(1.0)
    assert rows[0.5]["coverage"] == pytest.approx(1.0)
    assert rows[0.5]["accuracy_on_kept"] < 1.0


def test_report_written_with_advisory_framing(tmp_path):
    path = mc.write_report([0.7] * 30 + [0.3] * 30, [1] * 21 + [0] * 9 + [1] * 9 + [0] * 21,
                           model_name="synthetic", out_dir=tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "calibration_report_" in path.name
    assert "Advisory-only" in text
    assert "Reliability bins" in text and "Abstention analysis" in text
