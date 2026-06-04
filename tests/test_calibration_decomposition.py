"""Murphy decomposition + bootstrap ECE CI + reliability diagram tests."""
from __future__ import annotations

import math

from scripts import outcome_evidence as oe
from scripts import score_calibration as sc


def _o(label, score, count, source=oe.REAL_MANUAL_TRADE):
    out = []
    for i in range(count):
        ex = 110.0 if label == "WIN" else 90.0 if label == "LOSS" else 100.0
        out.append(oe.build_outcome(
            outcome_id=f"{label}{score}_{i}_{id(object())}", source_type=source,
            ticker="X", direction="LONG", entry_price=100.0, exit_price=ex,
            score_at_entry=score, opened_at="a", closed_at="b",
            outcome_label_override=label,
        ))
    return out


def test_murphy_decomposition_holds():
    # Brier (binned) == reliability - resolution + uncertainty, exactly.
    m = sc.compute_calibration_metrics(
        _o("WIN", 0.9, 27) + _o("LOSS", 0.9, 3) + _o("WIN", 0.4, 12) + _o("LOSS", 0.4, 18)
    )
    lhs = m["binned_brier"]
    rhs = m["reliability"] - m["resolution"] + m["uncertainty"]
    assert math.isclose(lhs, rhs, abs_tol=1e-12)


def test_uncertainty_is_baserate_variance():
    m = sc.compute_calibration_metrics(_o("WIN", 0.5, 30) + _o("LOSS", 0.5, 30))
    # base rate 0.5 -> uncertainty 0.25
    assert math.isclose(m["base_rate"], 0.5, abs_tol=1e-9)
    assert math.isclose(m["uncertainty"], 0.25, abs_tol=1e-9)


def test_reliability_low_when_well_calibrated():
    # score 0.9 with 90% wins -> confidence==accuracy in that bucket -> rel ~ 0.
    m = sc.compute_calibration_metrics(_o("WIN", 0.9, 54) + _o("LOSS", 0.9, 6))
    assert m["reliability"] < 1e-9


def test_reliability_high_when_overconfident():
    m = sc.compute_calibration_metrics(_o("LOSS", 0.9, 60))  # conf 0.9 acc 0
    # reliability = (0.9-0)^2 = 0.81
    assert math.isclose(m["reliability"], 0.81, abs_tol=1e-9)


def test_resolution_zero_when_no_discrimination():
    # both buckets have the same accuracy as base rate -> resolution 0.
    m = sc.compute_calibration_metrics(_o("WIN", 0.3, 30) + _o("LOSS", 0.3, 30)
                                       + _o("WIN", 0.8, 30) + _o("LOSS", 0.8, 30))
    # each bucket acc 0.5, base rate 0.5 -> resolution 0
    assert math.isclose(m["resolution"], 0.0, abs_tol=1e-9)


def test_bootstrap_ece_ci_brackets_point_and_deterministic():
    outs = _o("WIN", 0.9, 30) + _o("LOSS", 0.9, 30)
    m1 = sc.compute_calibration_metrics(outs)
    m2 = sc.compute_calibration_metrics(outs)
    assert m1["ece_ci_lower"] == m2["ece_ci_lower"]  # deterministic seed
    assert m1["ece_ci_upper"] == m2["ece_ci_upper"]
    assert m1["ece_ci_lower"] <= m1["ece"] <= m1["ece_ci_upper"] + 1e-9


def test_reliability_diagram_points():
    m = sc.compute_calibration_metrics(_o("WIN", 0.9, 54) + _o("LOSS", 0.9, 6))
    rd = m["reliability_diagram"]
    assert len(rd) >= 1
    pt = rd[0]
    assert set(pt) == {"confidence", "accuracy", "n"}
