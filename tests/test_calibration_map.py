"""Exact + behavioural tests for isotonic/Platt recalibration."""
from __future__ import annotations

import math
import random

from scripts import calibration_map as cm
from scripts import outcome_evidence as oe


# --- Isotonic PAV exact ------------------------------------------------------

def test_pav_pools_violators():
    # ys not monotone: [0, 1, 0] at xs [1,2,3] -> middle/last pool to mean.
    xs, fitted = cm.isotonic_pav([1, 2, 3], [0.0, 1.0, 0.0])
    # PAV: 0, then 1>... 1 then 0 violates -> pool {1,0}->0.5; then 0<=0.5 ok.
    assert fitted[0] == 0.0
    assert math.isclose(fitted[1], 0.5)
    assert math.isclose(fitted[2], 0.5)


def test_pav_already_monotone_unchanged():
    xs, fitted = cm.isotonic_pav([1, 2, 3], [0.1, 0.5, 0.9])
    assert fitted == [0.1, 0.5, 0.9]


def test_isotonic_is_monotone_nondecreasing():
    model = cm.fit_isotonic([0.1, 0.2, 0.3, 0.4, 0.5], [0, 1, 0, 1, 1])
    preds = [model.predict(s) for s in [0.05, 0.15, 0.25, 0.35, 0.45, 0.55]]
    for a, b in zip(preds, preds[1:]):
        assert b >= a - 1e-9


def test_isotonic_maps_overconfident_to_baserate():
    # All scores 0.9 but base rate 0.5 -> isotonic should map ~0.9 to ~0.5.
    scores = [0.9] * 20
    ys = [1.0 if i % 2 == 0 else 0.0 for i in range(20)]
    model = cm.fit_isotonic(scores, ys)
    assert abs(model.predict(0.9) - 0.5) < 1e-6


# --- Platt scaling -----------------------------------------------------------

def test_platt_increasing_when_score_predicts():
    # high score -> win, low score -> loss
    scores = [0.1, 0.2, 0.3, 0.7, 0.8, 0.9] * 5
    ys = [0, 0, 0, 1, 1, 1] * 5
    m = cm.fit_platt(scores, ys, iters=800)
    assert m.predict(0.9) > m.predict(0.1)


def test_platt_reduces_logloss_vs_raw():
    scores = [0.1, 0.2, 0.3, 0.7, 0.8, 0.9] * 8
    ys = [0, 0, 0, 1, 1, 1] * 8
    m = cm.fit_platt(scores, ys, iters=800)
    def ll(ps):
        return -sum(y * math.log(max(1e-6, min(1 - 1e-6, p))) +
                    (1 - y) * math.log(max(1e-6, min(1 - 1e-6, 1 - p)))
                    for p, y in zip(ps, ys)) / len(ys)
    raw = ll(scores)
    cal = ll([m.predict(s) for s in scores])
    assert cal < raw


# --- Chooser / OOS validation -----------------------------------------------

def test_too_little_data_is_identity():
    m = cm.fit_calibration_map([0.5, 0.6], [1, 0])
    assert m.method == "identity"
    assert m.improved is False


def test_recalibration_reduces_ece_out_of_sample():
    # Systematically overconfident: score 0.9 everywhere, true win rate 0.4.
    random.seed(7)
    scores, ys = [], []
    for _ in range(120):
        scores.append(0.9)
        ys.append(1.0 if random.random() < 0.4 else 0.0)
    # add a low-score cohort that loses, so the map has range
    for _ in range(120):
        scores.append(0.2)
        ys.append(1.0 if random.random() < 0.15 else 0.0)
    m = cm.fit_calibration_map(scores, ys, test_frac=0.34)
    assert m.method in {"isotonic", "platt"}
    assert m.improved is True
    # OOS ECE strictly improved
    assert m.cal_test_ece < m.raw_test_ece
    # the 0.9 raw score now maps well below 0.9
    assert m.apply(0.9) < 0.7


def test_identity_when_already_calibrated():
    # Perfectly calibrated: P(win)=score. Recalibration shouldn't help OOS.
    random.seed(11)
    scores, ys = [], []
    for s in [0.1, 0.3, 0.5, 0.7, 0.9]:
        for _ in range(40):
            scores.append(s)
            ys.append(1.0 if random.random() < s else 0.0)
    m = cm.fit_calibration_map(scores, ys, test_frac=0.34)
    # Either identity, or an improvement that is tiny — never a big false gain.
    assert m.cal_test_brier <= m.raw_test_brier + 1e-9


def test_apply_is_monotone_for_isotonic():
    random.seed(3)
    scores = [random.random() for _ in range(200)]
    ys = [1.0 if random.random() < s else 0.0 for s in scores]
    m = cm.fit_calibration_map(scores, ys)
    grid = [i / 20 for i in range(21)]
    preds = [m.apply(g) for g in grid]
    for a, b in zip(preds, preds[1:]):
        # platt or isotonic are both monotone non-decreasing
        assert b >= a - 1e-6


# --- From outcomes + advisory invariants ------------------------------------

def _o(label, score, source=oe.IMPORTED_BACKTEST):
    ex = 110.0 if label == "WIN" else 90.0 if label == "LOSS" else 100.0
    return oe.build_outcome(
        outcome_id=f"{label}{score}_{id(object())}", source_type=source,
        ticker="X", direction="LONG", entry_price=100.0, exit_price=ex,
        score_at_entry=score, opened_at="a", closed_at="b",
        outcome_label_override=label,
    )


def test_fit_from_outcomes_uses_eligible_only():
    outs = [_o("WIN", 0.9) for _ in range(30)] + [_o("LOSS", 0.9) for _ in range(30)]
    outs += [_o("WIN", 0.2, source=oe.SYNTHETIC_FIXTURE) for _ in range(50)]  # excluded
    m = cm.fit_from_outcomes(outs)
    d = m.to_dict()
    assert d["advisory_only"] is True
    assert d["broker_api_called"] is False
    # 60 eligible -> not identity-for-lack-of-data
    assert m.train_n + m.test_n == 60


def test_map_dict_reports_improvement_fields():
    random.seed(5)
    scores = [0.9] * 100 + [0.2] * 100
    ys = [1.0 if random.random() < 0.4 else 0.0 for _ in range(100)]
    ys += [1.0 if random.random() < 0.1 else 0.0 for _ in range(100)]
    d = cm.fit_calibration_map(scores, ys).to_dict()
    for k in ("raw_test_ece", "cal_test_ece", "ece_improvement", "method", "improved_out_of_sample"):
        assert k in d
