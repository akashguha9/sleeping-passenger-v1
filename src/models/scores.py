"""Scoring dataclasses for deterministic decision outputs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class ScoreResult:
    score: float
    explanation: str
    reason_codes: list[str] = field(default_factory=list)
    raw_components: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
