"""Tests — event study, walk-forward/purge/embargo/no-lookahead, lead-lag."""
from __future__ import annotations

import math
import random

import pytest

from scripts.quant_event_study_engine import compare_to_baseline, event_study
from scripts.quant_lead_lag_engine import (
    NOT_PREDICTIVE,
    PREDICTIVE,
    cross_correlation,
    granger_style_oos,
    lead_lag_study,
)
from scripts.quant_statistics_engine import INSUFFICIENT_DATA, OK
from scripts.quant_walk_forward_split import (
    LookaheadError,
    assert_no_lookahead,
    walk_forward_folds,
)


class TestEventStudy:
    def test_aar_and_hit_rate_with_n_always_shown(self):
        events = {f"e{i}": {1: 0.01, 5: 0.02 + 0.001 * i} for i in range(10)}
        out = event_study(events, horizons=(1, 5))
        assert out["status"] == OK
        assert out["horizons"][1]["n"] == 10
        assert out["horizons"][1]["stats"]["mean"] == pytest.approx(0.01)
        assert out["horizons"][1]["hit_rate"] == 1.0

    def test_insufficient_events_gate(self):
        out = event_study({"e1": {1: 0.01}}, horizons=(1,))
        assert out["status"] == INSUFFICIENT_DATA
        assert out["horizons"][1]["stats"]["status"] == INSUFFICIENT_DATA

    def test_missing_horizon_reduces_n_never_imputed(self):
        events = {f"e{i}": ({1: 0.01} if i < 8 else {1: 0.01, 5: 0.05})
                  for i in range(16)}
        out = event_study(events, horizons=(1, 5))
        assert out["horizons"][1]["n"] == 16
        assert out["horizons"][5]["n"] == 8

    def test_baseline_comparison(self):
        sig = {f"s{i}": {5: 0.03} for i in range(10)}
        base = {f"b{i}": {5: 0.01} for i in range(10)}
        cmp_ = compare_to_baseline(event_study(sig, horizons=(5,)),
                                   event_study(base, horizons=(5,)))
        assert cmp_["horizons"][5]["edge_vs_baseline"] == pytest.approx(0.02)
        assert 5 in cmp_["beats_baseline_horizons"]


class TestWalkForward:
    def test_chronological_folds_no_leak(self):
        times = [f"2026-01-{d:02d}" for d in range(1, 29)]
        out = walk_forward_folds(times, n_folds=3, min_train=10)
        assert out["status"] == OK
        for f in out["folds"]:
            assert max(f["train_times"]) < min(f["test_times"])

    def test_purge_removes_overlapping_labels(self):
        times = [f"t{str(i).zfill(3)}" for i in range(30)]
        purged = walk_forward_folds(times, n_folds=2, min_train=10, horizon=3)
        unpurged = walk_forward_folds(times, n_folds=2, min_train=10)
        assert len(purged["folds"][0]["train_times"]) == \
            len(unpurged["folds"][0]["train_times"]) - 3
        assert purged["folds"][0]["purged"] == 3

    def test_insufficient_gate(self):
        assert walk_forward_folds(["a", "b"], n_folds=3)["status"] == \
            INSUFFICIENT_DATA

    def test_unsorted_times_rejected(self):
        with pytest.raises(ValueError):
            walk_forward_folds(["b", "a"] * 10)

    def test_no_lookahead_guard(self):
        good = [{"t": "2026-01-05", "t_available": "2026-01-05"}]
        assert assert_no_lookahead(good) == 1
        bad = [{"t": "2026-01-05", "t_available": "2026-01-06"}]
        with pytest.raises(LookaheadError):
            assert_no_lookahead(bad)
        with pytest.raises(LookaheadError):
            assert_no_lookahead([{"t": "2026-01-05"}])


class TestLeadLag:
    def test_planted_lead_detected(self):
        rng = random.Random(3)
        x = [rng.gauss(0, 1) for _ in range(140)]
        # y follows x with lag 2 plus small noise -> x leads y.
        y = [0.0, 0.0] + [0.8 * x[i - 2] + rng.gauss(0, 0.2)
                          for i in range(2, 140)]
        cc = cross_correlation(x, y, max_lag=4)
        assert cc["status"] == OK
        assert cc["best_lag"] == 2
        assert abs(cc["best_rho"]) > 0.5
        gr = granger_style_oos(x, y, p=2, q=3)
        assert gr["relationship"] == PREDICTIVE
        study = lead_lag_study(x, y, label_x="x", label_y="y")
        assert study["verdict"] == PREDICTIVE

    def test_independent_noise_not_predictive(self):
        rng = random.Random(9)
        x = [rng.gauss(0, 1) for _ in range(140)]
        y = [rng.gauss(0, 1) for _ in range(140)]
        study = lead_lag_study(x, y, label_x="x", label_y="y")
        assert study["verdict"] in (NOT_PREDICTIVE, "ASSOCIATED")
        assert study.get("granger_style_oos", {}).get("relationship") != \
            PREDICTIVE

    def test_never_labels_causal(self):
        rng = random.Random(5)
        x = [rng.gauss(0, 1) for _ in range(120)]
        y = [0.9 * xi + rng.gauss(0, 0.1) for xi in x]
        study = lead_lag_study(x, y, label_x="x", label_y="y")
        # The emitted labels must never claim causality (mission 42);
        # disclaimers in notes are allowed.
        labels = {study.get("verdict"),
                  study.get("cross_correlation", {}).get("relationship"),
                  study.get("granger_style_oos", {}).get("relationship")}
        assert "CAUSAL" not in labels
        assert "CAUSALLY_IDENTIFIED" not in labels

    def test_short_series_gated(self):
        cc = cross_correlation([1.0, 2.0], [1.0, 2.0])
        assert cc["status"] == INSUFFICIENT_DATA

    def test_sine_lead_relationship_math(self):
        # x_t = sin(t), y_t = sin(t - 3): x leads y by 3 steps exactly.
        x = [math.sin(0.3 * t) for t in range(160)]
        y = [math.sin(0.3 * (t - 3)) for t in range(160)]
        cc = cross_correlation(x, y, max_lag=5)
        assert cc["best_lag"] == 3
