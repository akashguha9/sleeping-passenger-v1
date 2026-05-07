from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import pstdev
from typing import Any


@dataclass(frozen=True)
class InterpretationDriftReport:
    signal_id: str
    drift_score: float
    max_min_range: float
    stddev: float
    threshold: float
    chaos_veto: bool
    disagreement_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_interpretation_drift(
    signal_id: str,
    lens_interpretations: list[dict[str, Any]],
    threshold: float,
) -> InterpretationDriftReport:
    scores = [float(item.get("meaning_score", 0.0) or 0.0) for item in lens_interpretations]
    labels = {str(item.get("meaning_label", "UNKNOWN")).upper() for item in lens_interpretations}
    if not scores:
        return InterpretationDriftReport(
            signal_id=signal_id,
            drift_score=0.0,
            max_min_range=0.0,
            stddev=0.0,
            threshold=threshold,
            chaos_veto=False,
            disagreement_count=0,
        )
    score_range = max(scores) - min(scores)
    score_stddev = pstdev(scores) if len(scores) > 1 else 0.0
    drift_score = max(score_range, min(1.0, score_stddev * 2.0))
    return InterpretationDriftReport(
        signal_id=signal_id,
        drift_score=drift_score,
        max_min_range=score_range,
        stddev=score_stddev,
        threshold=threshold,
        chaos_veto=drift_score > threshold,
        disagreement_count=max(0, len(labels) - 1),
    )
