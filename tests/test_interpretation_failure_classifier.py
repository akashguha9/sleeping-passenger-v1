from scripts.contextual_interpretation.interpretation_failure_classifier import (
    classify_interpretation_failure,
)


def test_interpretation_error_is_classified_separately_from_detection_error() -> None:
    record = classify_interpretation_failure(
        {
            "signal_id": "sig-3",
            "interpretation_drift": 0.82,
            "interpretation_confidence": 0.35,
            "recommended_action": "REDUCE_SIZE",
            "reason_codes": ["HIGH_INTERPRETATION_DRIFT"],
        }
    )
    assert record.failure_type == "InterpretationError"
