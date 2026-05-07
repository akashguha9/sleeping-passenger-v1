"""Signal, decision, and cluster dataclasses for the MVP refinery."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class SignalScore:
    market_id: str
    engagement_manipulation_score: float
    evidence_quality_score: float
    durability_score: float
    liquidity_score: float
    execution_friction_score: float
    market_mispricing_estimate: float
    model_probability: float
    net_signal_value: float
    admission_priority_score: float
    state: str
    reason_codes: list[str]
    explanation: str
    scored_at: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class AttentionCluster:
    market_id: str
    topic: str
    entities: list[str]
    narrative_type: str
    emotional_category: str
    source: str
    timestamp: str
    attention_cluster_score: float
    engagement_manipulation_score: float
    evidence_quality_score: float
    reason_codes: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class StateDecision:
    state: str
    reason_codes: list[str] = field(default_factory=list)
    explanation: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
