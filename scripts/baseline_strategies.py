"""Deterministic baseline strategies for replay comparison.

These strategies are *baselines*, not investment advice. They exist so a
labelled replay run can compare the system's predicted action against a
trivially predictable reference. Without baselines, any system metric
is meaningless.

All strategies are deterministic given the same input sequence and seed.
"""
from __future__ import annotations

import abc
import random
from dataclasses import dataclass
from typing import Any, Iterable, Sequence


_DEFAULT_ACTION_SPACE: tuple[str, ...] = (
    "EXIT_NOW",
    "REDUCE",
    "HOLD",
    "MONITOR",
    "BLOCK_ENTRY",
    "REVIEW_FOR_ENTRY",
)


@dataclass(frozen=True)
class BaselineDecision:
    """One baseline prediction for a single replay record."""

    record_id: str
    instrument: str
    predicted_action: str
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "instrument": self.instrument,
            "predicted_action": self.predicted_action,
            "rationale": self.rationale,
        }


class BaselineStrategy(abc.ABC):
    """Abstract base class for deterministic replay baselines."""

    name: str = "baseline"

    @abc.abstractmethod
    def act(self, record: dict[str, Any]) -> BaselineDecision:
        ...

    def decide(self, records: Iterable[dict[str, Any]]) -> list[BaselineDecision]:
        return [self.act(record) for record in records]


class AlwaysHoldBaseline(BaselineStrategy):
    name = "always_hold"

    def act(self, record: dict[str, Any]) -> BaselineDecision:
        return BaselineDecision(
            record_id=str(record.get("record_id") or ""),
            instrument=str(record.get("instrument") or ""),
            predicted_action="HOLD",
            rationale="always_hold_baseline_emits_hold_for_every_record",
        )


class RandomChoiceBaseline(BaselineStrategy):
    name = "random_choice"

    def __init__(
        self,
        seed: int = 0,
        action_space: Sequence[str] = _DEFAULT_ACTION_SPACE,
    ) -> None:
        self._seed = int(seed)
        self._action_space = tuple(action_space)
        self._rng = random.Random(self._seed)

    def reset(self) -> None:
        self._rng = random.Random(self._seed)

    def act(self, record: dict[str, Any]) -> BaselineDecision:
        choice = self._rng.choice(self._action_space)
        return BaselineDecision(
            record_id=str(record.get("record_id") or ""),
            instrument=str(record.get("instrument") or ""),
            predicted_action=choice,
            rationale=f"random_choice_with_seed={self._seed}",
        )

    def decide(self, records: Iterable[dict[str, Any]]) -> list[BaselineDecision]:
        # Reset so iterating multiple times yields the same sequence.
        self.reset()
        return super().decide(records)


class NaiveMomentumBaseline(BaselineStrategy):
    """Trivial momentum baseline.

    If ``feature_value`` exceeds an upper threshold, predict
    ``REVIEW_FOR_ENTRY``. Below a lower threshold, predict
    ``BLOCK_ENTRY``. Otherwise, ``MONITOR``.

    No claim of profitability — this is a deterministic reference, not
    advice. The thresholds are arbitrary by construction.
    """

    name = "naive_momentum"

    def __init__(self, upper: float = 0.6, lower: float = 0.3) -> None:
        if upper <= lower:
            raise ValueError("upper threshold must exceed lower threshold")
        self._upper = float(upper)
        self._lower = float(lower)

    def act(self, record: dict[str, Any]) -> BaselineDecision:
        feature = record.get("feature_value")
        try:
            value = float(feature)
        except (TypeError, ValueError):
            value = 0.0
        if value >= self._upper:
            action = "REVIEW_FOR_ENTRY"
            rationale = f"feature_value={value:.4f}>=upper={self._upper}"
        elif value <= self._lower:
            action = "BLOCK_ENTRY"
            rationale = f"feature_value={value:.4f}<=lower={self._lower}"
        else:
            action = "MONITOR"
            rationale = (
                f"lower={self._lower}<feature_value={value:.4f}<upper={self._upper}"
            )
        return BaselineDecision(
            record_id=str(record.get("record_id") or ""),
            instrument=str(record.get("instrument") or ""),
            predicted_action=action,
            rationale=rationale,
        )


def summarise_baseline_decisions(
    name: str,
    decisions: Sequence[BaselineDecision],
) -> dict[str, Any]:
    """Build a deterministic summary of baseline decisions."""

    counts: dict[str, int] = {}
    for decision in decisions:
        counts[decision.predicted_action] = counts.get(decision.predicted_action, 0) + 1
    return {
        "baseline_name": name,
        "decision_count": len(decisions),
        "action_counts": dict(sorted(counts.items())),
        "note": (
            "baseline output is a deterministic reference; it is not "
            "investment advice and is not validated against live data."
        ),
    }


__all__ = [
    "AlwaysHoldBaseline",
    "BaselineDecision",
    "BaselineStrategy",
    "NaiveMomentumBaseline",
    "RandomChoiceBaseline",
    "summarise_baseline_decisions",
]
