"""Market snapshot model used by the public-data refinery MVP."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class MarketSnapshot:
    market_id: str
    event_id: str
    question: str
    description: str
    category: str
    outcomes: list[str]
    yes_price: float
    no_price: float
    implied_probability: float
    volume: float
    liquidity: float
    best_bid: float
    best_ask: float
    spread: float
    end_date: str
    active: bool
    closed: bool
    source_url: str
    fetched_at: str
    order_book_depth: float = 0.0
    source_credibility: float = 0.5
    evidence_density: float = 0.5
    emotional_intensity: float = 0.5
    headline_extremity: float = 0.5
    narrative_recycling: float = 0.5
    virality_spike: float = 0.5
    curiosity_gap: float = 0.5
    primary_source_weight: float = 0.5
    confirmation_count_norm: float = 0.5
    recency_score: float = 0.5
    cross_source_diversity: float = 0.5
    contradiction_penalty: float = 0.0
    persistence: float = 0.5
    stress_survival: float = 0.5
    cross_source_confirmation: float = 0.5
    time_stability: float = 0.5
    contradiction_resistance: float = 0.5
    volatility_penalty: float = 0.2
    timing_risk: float = 0.2
    api_uncertainty_penalty: float = 0.0
    narrative_type: str = "unknown"
    entities: list[str] = field(default_factory=list)
    source: str = "polymarket_public"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
