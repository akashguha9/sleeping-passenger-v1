"""Offline signal stubs — determinism and shape invariants."""

from __future__ import annotations

from src.alpha.signals import (
    FilingSignal,
    NarrativeSignal,
    PredictionMarketSignal,
    ValueChainSignal,
    stub_filing_signal,
    stub_narrative_signal,
    stub_prediction_market_signal,
)


def test_prediction_market_signal_edge_and_shape() -> None:
    signal = PredictionMarketSignal(
        event_name="event",
        market_probability=0.30,
        model_probability=0.45,
        resolution_date="2026-12-31",
    )
    data = signal.to_dict()
    assert abs(data["probability_edge"] - 0.15) < 1e-9
    assert data["source"] == "manual_stub"
    for key in (
        "event_name",
        "market_probability",
        "model_probability",
        "probability_edge",
        "resolution_date",
        "source",
        "confidence",
    ):
        assert key in data


def test_filing_signal_shape_and_clamping() -> None:
    signal = FilingSignal(
        company="Co", ticker="CO", embedded_proof_score=150.0, confidence=-5.0
    )
    data = signal.to_dict()
    assert data["embedded_proof_score"] == 100.0
    assert data["confidence"] == 0.0
    for key in ("filing_type", "claims", "verified_evidence", "source_date"):
        assert key in data


def test_narrative_signal_shape() -> None:
    data = NarrativeSignal(theme="water").to_dict()
    for key in (
        "theme",
        "source",
        "mention_velocity",
        "sentiment_intensity",
        "source_quality",
        "half_life_estimate_days",
    ):
        assert key in data


def test_value_chain_signal_shape() -> None:
    data = ValueChainSignal(theme="water", node_name="valves").to_dict()
    assert data["node_name"] == "valves"
    assert data["source"] == "manual_stub"


def test_stub_factories_are_deterministic_and_offline() -> None:
    assert stub_prediction_market_signal().to_dict() == stub_prediction_market_signal().to_dict()
    assert stub_filing_signal().to_dict() == stub_filing_signal().to_dict()
    assert stub_narrative_signal().to_dict() == stub_narrative_signal().to_dict()
    # Offline stubs must self-identify so they can never masquerade as live data.
    assert stub_prediction_market_signal().source == "manual_stub"
    assert stub_filing_signal().filing_type == "manual_stub"
    assert stub_narrative_signal().source == "manual_stub"
