from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class InterpretationFailureRecord:
    signal_id: str
    failure_type: str
    scores: dict[str, float]
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_interpretation_failure(
    packet: dict[str, Any],
    *,
    realized_outcome: dict[str, Any] | None = None,
) -> InterpretationFailureRecord:
    outcome = realized_outcome if isinstance(realized_outcome, dict) else {}
    scores = {
        "DetectionError": float(outcome.get("detection_error_score", 0.1) or 0.0),
        "InterpretationError": float(packet.get("interpretation_drift", 0.0) or 0.0),
        "ValidationError": float(outcome.get("validation_error_score", 0.2 if packet.get("interpretation_confidence", 0.0) < 0.55 else 0.1) or 0.0),
        "ExecutionError": float(outcome.get("execution_error_score", 0.0 if packet.get("recommended_action") == "BLOCK" else 0.1) or 0.0),
        "RegimeShift": float(outcome.get("regime_shift_score", 1.0 if "SHOCK_RECLASSIFICATION" in packet.get("reason_codes", []) else 0.0) or 0.0),
    }
    failure_type = max(scores, key=scores.get)
    explanation = {
        "DetectionError": "The raw signal was weak or malformed before interpretation.",
        "InterpretationError": "Meaning diverged across operator lenses and context was unstable.",
        "ValidationError": "The interpreted thesis lacked confirmation depth.",
        "ExecutionError": "Downstream execution discipline degraded the interpreted edge.",
        "RegimeShift": "A shock or context break invalidated the prior interpretation.",
    }[failure_type]
    return InterpretationFailureRecord(
        signal_id=str(packet.get("signal_id", "UNKNOWN")),
        failure_type=failure_type,
        scores=scores,
        explanation=explanation,
    )
