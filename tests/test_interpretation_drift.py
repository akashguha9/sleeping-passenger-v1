from scripts.contextual_interpretation.interpretation_drift import compute_interpretation_drift


def test_high_interpretation_drift_triggers_chaos_veto() -> None:
    report = compute_interpretation_drift(
        "sig-1",
        [
            {"meaning_label": "BREAKOUT", "meaning_score": 0.95},
            {"meaning_label": "EXHAUSTION", "meaning_score": 0.15},
            {"meaning_label": "STOP_RUN", "meaning_score": 0.88},
        ],
        0.35,
    )
    assert report.drift_score > 0.35
    assert report.chaos_veto is True


def test_low_interpretation_drift_stays_below_threshold() -> None:
    report = compute_interpretation_drift(
        "sig-2",
        [
            {"meaning_label": "CONTINUATION", "meaning_score": 0.60},
            {"meaning_label": "CONTINUATION", "meaning_score": 0.62},
            {"meaning_label": "ACCUMULATION", "meaning_score": 0.58},
        ],
        0.35,
    )
    assert report.drift_score < 0.35
    assert report.chaos_veto is False
