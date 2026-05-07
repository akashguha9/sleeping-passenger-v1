"""Read-only public Polymarket client.

MVP_1 is read-only. Trading integration is intentionally out of scope.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import requests

from src.models.market import MarketSnapshot
from src.utils.config_loader import load_yaml_config
from src.utils.logging_utils import get_logger, log_event
from src.utils.math_utils import clip
from src.utils.time_utils import utc_now_iso

LOGGER = get_logger("polymarket_public_client")
DEFAULT_SOURCES_PATH = Path("config/sources.yaml")


class PolymarketPublicClient:
    """Read-only public client with deterministic mock fallback."""

    def __init__(self, config_path: str | Path = DEFAULT_SOURCES_PATH) -> None:
        config = load_yaml_config(config_path)
        poly = config.get("polymarket", {})
        self.gamma_base_url = str(poly.get("gamma_base_url", "https://gamma-api.polymarket.com")).rstrip("/")
        self.data_base_url = str(poly.get("data_base_url", "https://data-api.polymarket.com")).rstrip("/")
        self.clob_base_url = str(poly.get("clob_base_url", "https://clob.polymarket.com")).rstrip("/")
        self.timeout_seconds = int(poly.get("timeout_seconds", 10))
        self.retries = int(poly.get("retries", 2))
        self.backoff_seconds = float(poly.get("backoff_seconds", 1.0))
        self.max_markets = int(poly.get("max_markets", 25))
        self.use_mock_on_failure = bool(poly.get("use_mock_on_failure", True))
        self.session = requests.Session()

    def _request_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout_seconds)
                response.raise_for_status()
                return response.json()
            except requests.RequestException as exc:
                last_error = exc
                log_event(LOGGER, "api_call_failed", module="polymarket_public_client", url=url, attempt=attempt, error=str(exc))
        if self.use_mock_on_failure:
            return None
        if last_error is not None:
            raise last_error
        return None

    def fetch_markets(self) -> list[MarketSnapshot]:
        log_event(LOGGER, "ingestion_started", module="polymarket_public_client")
        data = self._request_json(
            f"{self.gamma_base_url}/markets",
            params={"limit": self.max_markets, "closed": "false", "active": "true"},
        )
        if not data:
            snapshots = self._mock_markets()
            log_event(LOGGER, "ingestion_completed", module="polymarket_public_client", market_count=len(snapshots), fallback="mock")
            return snapshots
        items = data if isinstance(data, list) else data.get("markets", [])
        snapshots = [self.normalize_market(item) for item in items[: self.max_markets]]
        log_event(LOGGER, "ingestion_completed", module="polymarket_public_client", market_count=len(snapshots), fallback="none")
        return snapshots

    def fetch_events(self) -> list[dict[str, Any]]:
        data = self._request_json(f"{self.gamma_base_url}/events", params={"limit": self.max_markets})
        if not data:
            return [{"event_id": snapshot.event_id, "title": snapshot.question} for snapshot in self._mock_markets()]
        return data if isinstance(data, list) else data.get("events", [])

    def fetch_market_detail(self, market_id: str) -> MarketSnapshot:
        data = self._request_json(f"{self.gamma_base_url}/markets/{market_id}")
        if not data:
            return next(snapshot for snapshot in self._mock_markets() if snapshot.market_id == market_id)
        return self.normalize_market(data)

    def fetch_orderbook_public(self, token_id: str) -> dict[str, Any]:
        data = self._request_json(f"{self.clob_base_url}/book", params={"token_id": token_id})
        if not data:
            return {"token_id": token_id, "best_bid": 0.48, "best_ask": 0.52, "spread": 0.04, "depth": 5000.0}
        return dict(data)

    def normalize_market(self, payload: dict[str, Any]) -> MarketSnapshot:
        yes_price = float(payload.get("outcomePrices", [payload.get("yes_price", 0.5), 1 - payload.get("yes_price", 0.5)])[0] if payload.get("outcomePrices") else payload.get("yes_price", 0.5))
        no_price = float(payload.get("outcomePrices", [yes_price, payload.get("no_price", 1 - yes_price)])[1] if payload.get("outcomePrices") and len(payload.get("outcomePrices", [])) > 1 else payload.get("no_price", 1 - yes_price))
        best_bid = float(payload.get("bestBid", payload.get("best_bid", max(yes_price - 0.02, 0.01))))
        best_ask = float(payload.get("bestAsk", payload.get("best_ask", min(yes_price + 0.02, 0.99))))
        spread = max(best_ask - best_bid, 0.0)
        snapshot = MarketSnapshot(
            market_id=str(payload.get("id", payload.get("market_id", payload.get("conditionId", "mock-market")))),
            event_id=str(payload.get("eventId", payload.get("event_id", "mock-event"))),
            question=str(payload.get("question", payload.get("title", "Unknown market"))),
            description=str(payload.get("description", "")),
            category=str(payload.get("category", "general")),
            outcomes=list(payload.get("outcomes", ["YES", "NO"])),
            yes_price=yes_price,
            no_price=no_price,
            implied_probability=clip(yes_price, 0.01, 0.99),
            volume=float(payload.get("volume", 0.0)),
            liquidity=float(payload.get("liquidity", 0.0)),
            best_bid=best_bid,
            best_ask=best_ask,
            spread=spread,
            end_date=str(payload.get("endDate", payload.get("end_date", ""))),
            active=bool(payload.get("active", True)),
            closed=bool(payload.get("closed", False)),
            source_url=str(payload.get("url", f"{self.gamma_base_url}/markets/{payload.get('id', 'unknown')}")),
            fetched_at=utc_now_iso(),
            order_book_depth=float(payload.get("order_book_depth", payload.get("volume", 0.0))),
            source_credibility=clip(float(payload.get("source_credibility", 0.65)), 0.0, 1.0),
            evidence_density=clip(float(payload.get("evidence_density", 0.55)), 0.0, 1.0),
            emotional_intensity=clip(float(payload.get("emotional_intensity", 0.35)), 0.0, 1.0),
            headline_extremity=clip(float(payload.get("headline_extremity", 0.30)), 0.0, 1.0),
            narrative_recycling=clip(float(payload.get("narrative_recycling", 0.35)), 0.0, 1.0),
            virality_spike=clip(float(payload.get("virality_spike", 0.30)), 0.0, 1.0),
            curiosity_gap=clip(float(payload.get("curiosity_gap", 0.25)), 0.0, 1.0),
            primary_source_weight=clip(float(payload.get("primary_source_weight", 0.55)), 0.0, 1.0),
            confirmation_count_norm=clip(float(payload.get("confirmation_count_norm", 0.50)), 0.0, 1.0),
            recency_score=clip(float(payload.get("recency_score", 0.60)), 0.0, 1.0),
            cross_source_diversity=clip(float(payload.get("cross_source_diversity", 0.45)), 0.0, 1.0),
            contradiction_penalty=clip(float(payload.get("contradiction_penalty", 0.10)), 0.0, 1.0),
            persistence=clip(float(payload.get("persistence", 0.55)), 0.0, 1.0),
            stress_survival=clip(float(payload.get("stress_survival", 0.50)), 0.0, 1.0),
            cross_source_confirmation=clip(float(payload.get("cross_source_confirmation", 0.50)), 0.0, 1.0),
            time_stability=clip(float(payload.get("time_stability", 0.50)), 0.0, 1.0),
            contradiction_resistance=clip(float(payload.get("contradiction_resistance", 0.50)), 0.0, 1.0),
            volatility_penalty=clip(float(payload.get("volatility_penalty", 0.20)), 0.0, 1.0),
            timing_risk=clip(float(payload.get("timing_risk", 0.20)), 0.0, 1.0),
            api_uncertainty_penalty=clip(float(payload.get("api_uncertainty_penalty", 0.0)), 0.0, 1.0),
            narrative_type=str(payload.get("narrative_type", "headline")),
            entities=list(payload.get("entities", [])),
            source=str(payload.get("source", "polymarket_public")),
        )
        log_event(LOGGER, "market_normalized", module="polymarket_public_client", market_id=snapshot.market_id)
        return snapshot

    def health_check(self) -> dict[str, Any]:
        markets = self.fetch_markets()
        return {
            "ok": bool(markets),
            "read_only": True,
            "market_count": len(markets),
            "truth_origin": "public_or_mock",
        }

    def _mock_markets(self) -> list[MarketSnapshot]:
        base_rows = [
            {
                "id": "pm-001",
                "eventId": "ev-001",
                "question": "Will a major ceasefire deal be announced before quarter end?",
                "description": "Public prediction market on a high-attention geopolitical event.",
                "category": "geopolitics",
                "yes_price": 0.42,
                "volume": 52000,
                "liquidity": 64000,
                "source_credibility": 0.72,
                "evidence_density": 0.68,
                "emotional_intensity": 0.30,
                "headline_extremity": 0.25,
                "narrative_recycling": 0.35,
                "virality_spike": 0.40,
                "curiosity_gap": 0.20,
                "primary_source_weight": 0.70,
                "confirmation_count_norm": 0.65,
                "recency_score": 0.80,
                "cross_source_diversity": 0.65,
                "contradiction_penalty": 0.10,
                "persistence": 0.70,
                "stress_survival": 0.65,
                "cross_source_confirmation": 0.68,
                "time_stability": 0.60,
                "contradiction_resistance": 0.60,
                "entities": ["ceasefire", "diplomacy"],
            },
            {
                "id": "pm-002",
                "eventId": "ev-002",
                "question": "SHOCKING: Will emergency sanctions crash the region this week?",
                "description": "A hype-heavy market with thin evidence and extreme framing.",
                "category": "narrative",
                "yes_price": 0.58,
                "volume": 9000,
                "liquidity": 7000,
                "source_credibility": 0.28,
                "evidence_density": 0.20,
                "emotional_intensity": 0.85,
                "headline_extremity": 0.90,
                "narrative_recycling": 0.85,
                "virality_spike": 0.80,
                "curiosity_gap": 0.75,
                "primary_source_weight": 0.15,
                "confirmation_count_norm": 0.20,
                "recency_score": 0.60,
                "cross_source_diversity": 0.25,
                "contradiction_penalty": 0.40,
                "persistence": 0.35,
                "stress_survival": 0.30,
                "cross_source_confirmation": 0.20,
                "time_stability": 0.25,
                "contradiction_resistance": 0.20,
                "volatility_penalty": 0.60,
                "timing_risk": 0.65,
                "api_uncertainty_penalty": 0.20,
                "entities": ["sanctions", "region"],
            },
            {
                "id": "pm-003",
                "eventId": "ev-003",
                "question": "Will a central-bank emergency meeting happen this month?",
                "description": "Macro event with moderate evidence and improving confirmation.",
                "category": "macro",
                "yes_price": 0.33,
                "volume": 28000,
                "liquidity": 24000,
                "source_credibility": 0.66,
                "evidence_density": 0.60,
                "emotional_intensity": 0.25,
                "headline_extremity": 0.20,
                "narrative_recycling": 0.30,
                "virality_spike": 0.35,
                "curiosity_gap": 0.18,
                "primary_source_weight": 0.62,
                "confirmation_count_norm": 0.55,
                "recency_score": 0.75,
                "cross_source_diversity": 0.58,
                "contradiction_penalty": 0.12,
                "persistence": 0.58,
                "stress_survival": 0.56,
                "cross_source_confirmation": 0.57,
                "time_stability": 0.53,
                "contradiction_resistance": 0.55,
                "entities": ["central bank", "rates"],
            },
        ]
        return [self.normalize_market(row) for row in base_rows]
