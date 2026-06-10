"""Offline-safe signal models for future ingestion adapters.

These dataclasses define the contract between the alpha framework and
future live ingestion (Kalshi/Polymarket odds, filings parsers, social
narrative feeds).  No live APIs are called here.

TODO(ingestion): wire real adapters behind these shapes —
  - prediction markets via src/ingestion/kalshi_public_client.py /
    polymarket_public_client.py (read-only, already in repo);
  - filings via an offline-parsed EDGAR snapshot;
  - narrative velocity via licensed social/news data.
Until then the ``stub_*`` factories return deterministic fixtures with
``source`` set to ``manual_stub`` so downstream scoring stays testable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.utils.math_utils import clip


@dataclass(slots=True)
class PredictionMarketSignal:
    """A priced event probability and the model's edge against it."""

    event_name: str
    market_probability: float
    model_probability: float
    resolution_date: str
    source: str = "manual_stub"
    confidence: float = 50.0

    @property
    def probability_edge(self) -> float:
        return self.model_probability - self.market_probability

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["probability_edge"] = self.probability_edge
        data["confidence"] = clip(self.confidence, 0.0, 100.0)
        return data


@dataclass(slots=True)
class FilingSignal:
    """Hard-proof evidence extracted from filings or company documents."""

    company: str
    ticker: str
    filing_type: str = "manual_stub"
    claims: list[str] = field(default_factory=list)
    verified_evidence: list[str] = field(default_factory=list)
    embedded_proof_score: float = 0.0
    source_date: str = ""
    confidence: float = 50.0

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["embedded_proof_score"] = clip(self.embedded_proof_score, 0.0, 100.0)
        data["confidence"] = clip(self.confidence, 0.0, 100.0)
        return data


@dataclass(slots=True)
class NarrativeSignal:
    """Rising-attention signal from social/news sources."""

    theme: str
    source: str = "manual_stub"
    mention_velocity: float = 0.0
    sentiment_intensity: float = 0.0
    source_quality: float = 50.0
    half_life_estimate_days: float = 10.0

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["source_quality"] = clip(self.source_quality, 0.0, 100.0)
        return data


@dataclass(slots=True)
class ValueChainSignal:
    """A theme-to-node mapping candidate awaiting node scoring."""

    theme: str
    node_name: str
    position: str = "midstream_assembly"
    source: str = "manual_stub"
    notes: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def stub_prediction_market_signal() -> PredictionMarketSignal:
    """Deterministic offline example: a water-infrastructure funding event."""
    return PredictionMarketSignal(
        event_name="US municipal water infrastructure bill passes by year-end",
        market_probability=0.34,
        model_probability=0.41,
        resolution_date="2026-12-31",
        source="manual_stub",
        confidence=40.0,
    )


def stub_filing_signal() -> FilingSignal:
    """Deterministic offline example: plumbing distributor with sensor unit."""
    return FilingSignal(
        company="Example Plumbing Distribution Co",
        ticker="EXAMPLE",
        filing_type="manual_stub",
        claims=["smart leak-detection growth segment"],
        verified_evidence=[
            "revenue_segment: leak-detection hardware disclosed in 10-K",
            "capex_commitment: sensor warehouse automation",
        ],
        embedded_proof_score=62.0,
        source_date="2026-01-01",
        confidence=55.0,
    )


def stub_narrative_signal() -> NarrativeSignal:
    """Deterministic offline example: rising water-damage insurance chatter."""
    return NarrativeSignal(
        theme="residential water damage costs",
        source="manual_stub",
        mention_velocity=2.4,
        sentiment_intensity=0.6,
        source_quality=55.0,
        half_life_estimate_days=45.0,
    )
