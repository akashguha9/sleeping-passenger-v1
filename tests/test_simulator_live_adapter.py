"""Live adapter tests: ingestion shapes -> simulator inputs, fixtures only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.simulator.live_adapter import (
    assemble_payload_from_ingestion,
    market_snapshot_to_signal_input,
    prediction_pair_to_radar_input,
    source_cluster_to_narrative_input,
)
from src.simulator.pipeline import evaluate_candidate_payload

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Snapshot pair shaped like persistence.get_signal_events rows whose
# raw_payload follows the normalized Polymarket market shape.
EARLIER_EVENT = {
    "event_id": "pm_grid_t0",
    "source_name": "polymarket",
    "raw_payload": {
        "market_id": "ai-grid-bill-2026",
        "question": "Will the AI grid bill pass in 2026?",
        "implied_probability": 0.27,
        "liquidity": 60_000.0,
        "cross_source_confirmation": 0.7,
        "fetched_at": "2026-06-01T00:00:00+00:00",
    },
}
LATER_EVENT = {
    "event_id": "pm_grid_t1",
    "source_name": "polymarket",
    "raw_payload": {
        "market_id": "ai-grid-bill-2026",
        "question": "Will the AI grid bill pass in 2026?",
        "implied_probability": 0.54,
        "liquidity": 80_000.0,
        "cross_source_confirmation": 0.8,
        "fetched_at": "2026-06-03T00:00:00+00:00",
    },
}

MENTIONS = [
    {"source": "wire_a", "origin": "reuters", "source_credibility": 0.9},
    {"source": "blog_b", "origin": "reuters", "source_credibility": 0.4},
    {"source": "blog_c", "origin": "reuters", "source_credibility": 0.4},
    {"source": "paper_d", "origin": "ft", "source_credibility": 0.8,
     "contradicts": True},
]


def test_prediction_pair_becomes_radar_input() -> None:
    radar = prediction_pair_to_radar_input(
        EARLIER_EVENT, LATER_EVENT, market_importance=0.9,
        affected_themes=["ai_grid_buildout"],
    )
    assert radar["probability_before"] == pytest.approx(0.27)
    assert radar["probability_after"] == pytest.approx(0.54)
    # 0.27 move over 2 days -> 0.135/day velocity.
    assert radar["velocity"] == pytest.approx(0.135)
    assert radar["market_liquidity"] == pytest.approx(0.8)
    assert radar["market_name"].startswith("Will the AI grid bill")


def test_source_cluster_counts_origins_not_echoes() -> None:
    narrative = source_cluster_to_narrative_input(
        MENTIONS, narrative="ai grid strain"
    )
    assert narrative["mention_count"] == 4
    # Three reuters echoes collapse into one origin; ft is the second.
    assert narrative["independent_origin_count"] == 2
    assert narrative["contradiction_count"] == 1
    assert 0.0 < narrative["source_quality"] < 1.0


def test_market_snapshot_becomes_tyre_input() -> None:
    signal = market_snapshot_to_signal_input(
        {
            "raw_payload": {
                "narrative_type": "filing",
                "evidence_density": 0.8,
                "primary_source_weight": 0.7,
                "source_credibility": 0.9,
                "cross_source_confirmation": 0.5,
                "fetched_at": "2026-06-01T00:00:00+00:00",
            }
        },
        as_of="2026-06-02T00:00:00+00:00",
    )
    assert signal["signal_type"] == "backlog"  # filing -> hard compound
    assert signal["signal_age_hours"] == pytest.approx(24.0)
    assert signal["raw_strength"] == pytest.approx((0.6 * 0.8 + 0.4 * 0.7) * 100)
    # Virality without evidence earns nothing.
    hype = market_snapshot_to_signal_input(
        {"raw_payload": {"narrative_type": "viral", "virality_spike": 1.0,
                         "fetched_at": "2026-06-01T00:00:00+00:00"}},
        as_of="2026-06-01T01:00:00+00:00",
    )
    assert hype["signal_type"] == "viral_article"
    assert hype["raw_strength"] == 0.0


def test_assembled_payload_runs_through_pipeline() -> None:
    payload = assemble_payload_from_ingestion(
        ticker="GRIDCO",
        theme="ai_grid_buildout",
        market_events=[LATER_EVENT],
        mention_cluster=MENTIONS,
        security_metadata={"market_cap_usd": 5e9, "sector": "industrials"},
        prediction_pair=(EARLIER_EVENT, LATER_EVENT),
        as_of="2026-06-04T00:00:00+00:00",
    )
    assert payload["data_source"] == "ingestion_adapter"
    out = evaluate_candidate_payload(payload)
    decision = out["decision"]
    # No meal box, no driver process scores -> the simulator stays stingy.
    assert decision["final_state"] in ("reject", "archive", "watchlist")
    assert decision["meal_box_status"]["complete"] is False
    assert out["breakdown"]["narrative"]["mention_count"] == 4
    assert out["breakdown"]["circuit"]["circuit"] == "mid_cap"


def test_semantic_pairs_fixture_adapts_cleanly() -> None:
    """The repo's committed prediction-market fixture flows through the
    adapter without errors — proving the boundary fits real stored shapes."""
    fixture = json.loads(
        (FIXTURES / "prediction_markets" / "semantic_pairs.json").read_text()
    )
    markets = list(fixture.get("polymarket", [])) + list(fixture.get("kalshi", []))
    assert markets, "fixture should contain markets"
    first = markets[0]
    event = {"raw_payload": {
        "market_id": first.get("market_id", "m"),
        "question": first.get("title", first.get("question", "?")),
        "implied_probability": first.get("implied_probability", 0.5),
        "liquidity": first.get("liquidity", 0.0),
        "fetched_at": "2026-06-01T00:00:00+00:00",
    }}
    radar = prediction_pair_to_radar_input(event, event)
    assert radar["probability_before"] == radar["probability_after"]
