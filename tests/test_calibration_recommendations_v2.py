"""Tests for metrics-driven calibration recommendation math (never applied)."""
from __future__ import annotations

from scripts import outcome_evidence as oe
from scripts import score_calibration as sc
from scripts import calibration_recommendations as cr


def _o(label, score, count, source=oe.REAL_MANUAL_TRADE, entry=100.0, exit_=None):
    out = []
    for i in range(count):
        ex = exit_ if exit_ is not None else (110.0 if label == "WIN" else 90.0 if label == "LOSS" else 100.0)
        out.append(oe.build_outcome(
            outcome_id=f"{label}{score}_{i}_{id(object())}", source_type=source,
            ticker="X", direction="LONG", entry_price=entry, exit_price=ex,
            score_at_entry=score, opened_at="a", closed_at="b",
            outcome_label_override=label,
        ))
    return out


def _metrics(outs):
    return sc.compute_calibration_metrics(outs)


def test_insufficient_n_refuses_adjustment():
    m = _metrics(_o("WIN", 0.8, 10))
    rec = cr.build_recommendation_from_metrics(m)
    assert rec["recommendation"] == cr.OBSERVE_MORE_DATA
    assert rec["recommended_threshold_shift"] == 0.0
    assert rec["applied"] is False


def test_low_sample_band_does_not_adjust():
    m = _metrics(_o("WIN", 0.8, 20) + _o("LOSS", 0.8, 10))  # n=30
    rec = cr.build_recommendation_from_metrics(m)
    assert rec["recommendation"] == cr.LOW_SAMPLE_DO_NOT_ADJUST
    assert rec["recommended_threshold_shift"] == 0.0


def test_high_fpr_recommends_tightening():
    # n=60, mostly losses at a confident score -> high FPR, also high ECE.
    # Use score 0.5 to keep ECE low but FPR high: 0.5 score, 40 losses 20 wins.
    m = _metrics(_o("WIN", 0.5, 20) + _o("LOSS", 0.5, 40))
    rec = cr.build_recommendation_from_metrics(m)
    # FPR = 40/60 = 0.667 > 0.35; ECE at 0.5 confidence vs 0.333 accuracy is
    # 0.167 (>0.10) -> miscalibrated review takes precedence per priority order.
    assert rec["recommendation"] in {cr.TIGHTEN_THRESHOLDS, cr.MIS_CALIBRATED_REVIEW_REQUIRED}


def test_pure_high_fpr_low_ece_tightens():
    # Construct low-ECE but FPR>target: scores matching accuracy.
    # 60 outcomes at score 0.4, 24 wins 36 losses -> accuracy 0.4 == confidence 0.4 -> ECE 0.
    # FPR = 36/60 = 0.6 > 0.35.
    m = _metrics(_o("WIN", 0.4, 24) + _o("LOSS", 0.4, 36))
    rec = cr.build_recommendation_from_metrics(m)
    assert m["ece"] < 0.10
    assert rec["recommendation"] == cr.TIGHTEN_THRESHOLDS
    assert rec["recommended_threshold_shift"] > 0


def test_good_calibration_maintains():
    # n=60, score 0.5, 30/30 -> accuracy 0.5 == confidence -> ECE 0, FPR 0.5.
    # FPR 0.5 > 0.35 would tighten; make FPR<=target: score 0.65, 39 wins 21 losses
    # accuracy 0.65 == confidence 0.65 -> ECE 0; FPR = 21/60 = 0.35 == target (not >).
    m = _metrics(_o("WIN", 0.65, 39) + _o("LOSS", 0.65, 21))
    rec = cr.build_recommendation_from_metrics(m)
    assert m["ece"] < 0.10
    assert rec["recommendation"] in {cr.MAINTAIN_THRESHOLDS, cr.CONSIDER_MINOR_LOOSENING}


def test_high_ece_triggers_miscalibration_review():
    m = _metrics(_o("LOSS", 0.9, 60))  # confident but all lose -> ECE ~0.9
    rec = cr.build_recommendation_from_metrics(m)
    assert rec["recommendation"] == cr.MIS_CALIBRATED_REVIEW_REQUIRED
    assert rec["recommended_threshold_shift"] == 0.0


def test_dtau_bounded():
    m = _metrics(_o("LOSS", 0.4, 60))  # extreme FPR
    rec = cr.build_recommendation_from_metrics(m)
    assert -0.10 <= rec["recommended_threshold_shift"] <= 0.10
    assert -0.10 <= rec["dtau_global"] <= 0.10


def test_applied_always_false_and_advisory():
    for m in [_metrics([]), _metrics(_o("WIN", 0.5, 60))]:
        rec = cr.build_recommendation_from_metrics(m)
        assert rec["applied"] is False
        assert rec["auto_apply"] is False
        assert rec["advisory_status"] == "ADVISORY_ONLY"
        assert rec["broker_api_called"] is False
        assert rec["human_review_required"] is True


def test_no_threshold_file_modified(tmp_path, monkeypatch):
    # Building a recommendation must not write config/thresholds.yaml.
    import os
    thresholds = os.path.join(os.getcwd(), "config", "thresholds.yaml")
    before = os.path.getmtime(thresholds) if os.path.exists(thresholds) else None
    cr.build_recommendation_from_metrics(_metrics(_o("LOSS", 0.4, 60)))
    after = os.path.getmtime(thresholds) if os.path.exists(thresholds) else None
    assert before == after
