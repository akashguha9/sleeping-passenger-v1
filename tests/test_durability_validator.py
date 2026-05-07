from src.scoring.durability_validator import score_durability


def test_persistent_signal_gets_higher_ds() -> None:
    durable = score_durability(
        {
            "persistence": 0.8,
            "stress_survival": 0.8,
            "cross_source_confirmation": 0.8,
            "time_stability": 0.7,
            "contradiction_resistance": 0.7,
        }
    )
    weak = score_durability(
        {
            "persistence": 0.2,
            "stress_survival": 0.2,
            "cross_source_confirmation": 0.3,
            "time_stability": 0.2,
            "contradiction_resistance": 0.2,
        }
    )
    assert durable.score > weak.score


def test_one_shot_spike_gets_lower_ds() -> None:
    result = score_durability(
        {
            "persistence": 0.2,
            "stress_survival": 0.3,
            "cross_source_confirmation": 0.2,
            "time_stability": 0.2,
            "contradiction_resistance": 0.3,
        }
    )
    assert "ONE_SHOT_SPIKE" in result.reason_codes
