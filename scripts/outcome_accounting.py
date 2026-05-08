"""False-positive / false-negative accounting for replay metrics.

Given (predicted_action, observed_outcome) pairs, classify each as TP /
FP / TN / FN and compute precision, recall, FPR, and FNR. These metrics
are *replay metrics*, not live validity metrics. They never claim
predictive power; they describe agreement on a labelled replay slice.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence


# Predicted-actions that count as a "positive" prediction
# (i.e. the system suggested action / risk-on).
POSITIVE_PREDICTIONS: frozenset[str] = frozenset(
    {"REVIEW_FOR_ENTRY", "EXIT_NOW", "REDUCE"}
)

# Outcome labels that count as a "positive" realised outcome (the
# instrument moved in the predicted direction).
POSITIVE_OUTCOMES: frozenset[str] = frozenset(
    {"up_2pct_in_24h", "up_5pct_in_24h", "down_2pct_in_24h", "down_5pct_in_24h"}
)

# Minimum sample count below which we mark metrics as insufficient.
INSUFFICIENT_SAMPLE_THRESHOLD = 5


def _is_positive_prediction(action: Any) -> bool:
    return str(action or "").upper() in POSITIVE_PREDICTIONS


def _is_positive_outcome(label: Any) -> bool:
    return str(label or "").lower() in {x.lower() for x in POSITIVE_OUTCOMES}


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


@dataclass(frozen=True)
class OutcomeAccountingResult:
    """Deterministic FP/FN accounting summary."""

    sample_count: int
    labeled_count: int
    true_positive: int
    false_positive: int
    true_negative: int
    false_negative: int
    precision: float | None
    recall: float | None
    false_positive_rate: float | None
    false_negative_rate: float | None
    insufficient_sample: bool
    note: str = field(default="")

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_count": int(self.sample_count),
            "labeled_count": int(self.labeled_count),
            "true_positive": int(self.true_positive),
            "false_positive": int(self.false_positive),
            "true_negative": int(self.true_negative),
            "false_negative": int(self.false_negative),
            "precision": self.precision,
            "recall": self.recall,
            "false_positive_rate": self.false_positive_rate,
            "false_negative_rate": self.false_negative_rate,
            "insufficient_sample": bool(self.insufficient_sample),
            "note": self.note,
        }


def compute_outcome_accounting(
    pairs: Iterable[tuple[Any, Any]] | Sequence[dict[str, Any]],
) -> OutcomeAccountingResult:
    """Compute deterministic FP/FN accounting from prediction/outcome pairs.

    ``pairs`` may be a sequence of ``(predicted_action, outcome_label)``
    tuples or a sequence of dicts with ``predicted_action`` and
    ``outcome_label`` keys. Records whose outcome label is missing or
    empty are excluded from the labelled count.
    """

    sample_count = 0
    labeled_count = 0
    tp = fp = tn = fn = 0

    for entry in pairs:
        sample_count += 1
        if isinstance(entry, dict):
            predicted = entry.get("predicted_action")
            outcome = entry.get("outcome_label")
        else:
            try:
                predicted, outcome = entry  # type: ignore[misc]
            except Exception:
                predicted, outcome = None, None
        if outcome is None or str(outcome).strip() == "":
            continue
        labeled_count += 1
        positive_prediction = _is_positive_prediction(predicted)
        positive_outcome = _is_positive_outcome(outcome)
        if positive_prediction and positive_outcome:
            tp += 1
        elif positive_prediction and not positive_outcome:
            fp += 1
        elif not positive_prediction and positive_outcome:
            fn += 1
        else:
            tn += 1

    precision = _safe_ratio(tp, tp + fp)
    recall = _safe_ratio(tp, tp + fn)
    false_positive_rate = _safe_ratio(fp, fp + tn)
    false_negative_rate = _safe_ratio(fn, fn + tp)

    insufficient_sample = labeled_count < INSUFFICIENT_SAMPLE_THRESHOLD
    note = (
        "replay/sample metrics only — these counts describe agreement on a "
        "labelled replay slice and never validate live predictive power."
    )
    if insufficient_sample:
        note = (
            f"insufficient_sample: labeled_count={labeled_count} below "
            f"threshold={INSUFFICIENT_SAMPLE_THRESHOLD}; treat metrics as advisory only."
        )
    return OutcomeAccountingResult(
        sample_count=sample_count,
        labeled_count=labeled_count,
        true_positive=tp,
        false_positive=fp,
        true_negative=tn,
        false_negative=fn,
        precision=precision,
        recall=recall,
        false_positive_rate=false_positive_rate,
        false_negative_rate=false_negative_rate,
        insufficient_sample=insufficient_sample,
        note=note,
    )


__all__ = [
    "INSUFFICIENT_SAMPLE_THRESHOLD",
    "POSITIVE_OUTCOMES",
    "POSITIVE_PREDICTIONS",
    "OutcomeAccountingResult",
    "compute_outcome_accounting",
]
