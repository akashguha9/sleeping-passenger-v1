"""Exposure graph v0 tests: conservative resolution, provenance, bridge."""

from __future__ import annotations

import pytest

from src.simulator.exposure_graph import (
    EVIDENCE_DIRECT_REVENUE,
    EVIDENCE_SECOND_ORDER,
    LAG_HALF_LIFE_DAYS,
    ExposureEdge,
    ExposureGraph,
    build_seed_graph,
)
from src.simulator.pipeline import evaluate_candidate_payload


def _edge(**overrides) -> ExposureEdge:
    base = dict(
        ticker="ACME",
        value_chain_node="widgets",
        evidence_type=EVIDENCE_DIRECT_REVENUE,
        source="test",
        confidence=0.5,
        lag_days=0,
        fragility=0.0,
        explanation="test edge",
    )
    base.update(overrides)
    return ExposureEdge(**base)


def test_unknown_evidence_type_rejected() -> None:
    graph = ExposureGraph()
    with pytest.raises(ValueError):
        graph.add_edge("theme", _edge(evidence_type="vibes"))


def test_exposure_confidence_is_noisy_or_of_edges() -> None:
    graph = ExposureGraph()
    graph.add_edge("t", _edge(confidence=0.5))
    graph.add_edge("t", _edge(confidence=0.5, evidence_type=EVIDENCE_SECOND_ORDER))
    resolved = graph.resolve("t", "ACME")
    assert resolved.exposure_confidence == pytest.approx(1 - 0.5 * 0.5)


def test_lag_decay_halves_at_half_life() -> None:
    graph = ExposureGraph()
    graph.add_edge("t", _edge(confidence=1.0, lag_days=LAG_HALF_LIFE_DAYS))
    resolved = graph.resolve("t", "ACME")
    assert resolved.lag_decay == pytest.approx(0.5)
    assert resolved.fragility_adjusted_exposure == pytest.approx(0.5)


def test_fragility_reduces_adjusted_exposure() -> None:
    graph = ExposureGraph()
    graph.add_edge("t", _edge(confidence=0.8, fragility=0.0))
    solid = graph.resolve("t", "ACME").fragility_adjusted_exposure
    graph2 = ExposureGraph()
    graph2.add_edge("t", _edge(confidence=0.8, fragility=0.7))
    fragile = graph2.resolve("t", "ACME").fragility_adjusted_exposure
    assert fragile < solid
    assert "FRAGILE_EXPOSURE_CHAIN" in graph2.resolve("t", "ACME").reason_codes


def test_unknown_ticker_resolves_to_zero_with_reason() -> None:
    resolved = build_seed_graph().resolve("ai_grid_buildout", "NOSUCH")
    assert resolved.exposure_confidence == 0.0
    assert resolved.edge_count == 0
    assert "NO_GRAPH_EDGES" in resolved.reason_codes


def test_seed_graph_distinguishes_direct_from_passenger() -> None:
    graph = build_seed_graph()
    gridco = graph.resolve("ai_grid_buildout", "GRIDCO")
    hype = graph.resolve("ai_grid_buildout", "HYPENAME")
    assert gridco.fragility_adjusted_exposure > hype.fragility_adjusted_exposure
    assert "SECOND_ORDER_ONLY" in hype.reason_codes
    assert "DIRECT_REVENUE_EDGE" in gridco.reason_codes
    # Every edge carries provenance.
    for edge in gridco.edges + hype.edges:
        assert edge.source
        assert edge.explanation


def test_resolver_bridge_maps_evidence_types_to_components() -> None:
    inputs = build_seed_graph().to_resolver_inputs("ai_grid_buildout", "GRIDCO")
    assert inputs["revenue_exposure"] > 0.0
    assert inputs["backlog_linkage"] > 0.0
    assert inputs["customer_linkage"] == 0.0  # no such edge for GRIDCO
    assert 0.0 <= inputs["weak_evidence_penalty"] <= 1.0


def test_pipeline_falls_back_to_graph_when_exposure_absent() -> None:
    out = evaluate_candidate_payload(
        {"ticker": "GRIDCO", "theme": "ai_grid_buildout"}
    )
    assert out["breakdown"]["exposure_graph_resolution"] is not None
    assert out["breakdown"]["exposure"]["exposure_score"] > 0.0

    # Caller-supplied exposure still wins over the graph.
    explicit = evaluate_candidate_payload(
        {
            "ticker": "GRIDCO",
            "theme": "ai_grid_buildout",
            "exposure": {"revenue_exposure": 0.9, "margin_sensitivity": 0.1,
                         "backlog_linkage": 0.1, "customer_linkage": 0.1,
                         "geographic_fit": 0.1, "policy_fit": 0.1,
                         "supply_chain_position": 0.1},
        }
    )
    assert explicit["breakdown"]["exposure_graph_resolution"] is None

    # Unknown tickers stay conservative — no graph, low exposure.
    unknown = evaluate_candidate_payload(
        {"ticker": "NOSUCH", "theme": "ai_grid_buildout"}
    )
    assert unknown["breakdown"]["exposure_graph_resolution"] is None
