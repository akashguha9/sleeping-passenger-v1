"""Triangulation engine: classifications and opportunity integration."""

from __future__ import annotations

from src.alpha.opportunity import (
    POSITIVE_COMPONENTS,
    RISK_COMPONENTS,
    aggregate_opportunity_score_v2,
)
from src.alpha.triangulation import TRIANGULATION_CLASSES, triangulate

_STRONG_FILING = {"embedded_proof_score": 80.0, "filing_risk_disclosure_score": 15.0}
_WEAK_FILING = {"embedded_proof_score": 15.0, "filing_risk_disclosure_score": 20.0}
_RISKY_FILING = {"embedded_proof_score": 20.0, "filing_risk_disclosure_score": 80.0}
_HOT_NARRATIVE = {"narrative_velocity_score": 85.0, "confidence": 60.0}
_QUIET_NARRATIVE = {"narrative_velocity_score": 25.0, "confidence": 50.0}


def test_single_source_hype() -> None:
    result = triangulate(narrative=_HOT_NARRATIVE)
    assert result["triangulation_class"] == "single_source_hype"
    assert result["independent_source_count"] == 1


def test_quiet_food_chain_candidate() -> None:
    result = triangulate(
        narrative=_QUIET_NARRATIVE,
        filing=_STRONG_FILING,
        value_chain={"node_attractiveness": 65.0},
    )
    assert result["triangulation_class"] == "quiet_food_chain_candidate"


def test_strongly_triangulated() -> None:
    result = triangulate(
        narrative={"narrative_velocity_score": 60.0, "confidence": 70.0},
        prediction_market={"probability_edge": 0.15, "confidence": 80.0},
        filing=_STRONG_FILING,
        value_chain={"node_attractiveness": 70.0},
        replay={"calibration_support": 50.0},
    )
    assert result["triangulation_class"] == "strongly_triangulated"
    assert result["independent_source_count"] == 4


def test_contradicted_when_narrative_fights_filings() -> None:
    result = triangulate(
        narrative=_HOT_NARRATIVE,
        filing=_RISKY_FILING,
        prediction_market={"probability_edge": -0.25, "confidence": 80.0},
    )
    assert result["triangulation_class"] == "contradicted"
    assert result["contradiction_score"] >= 50.0
    assert result["contradiction_notes"]


def test_weakest_and_dominant_links_identified() -> None:
    result = triangulate(
        narrative=_HOT_NARRATIVE,
        filing=_WEAK_FILING,
    )
    assert result["dominant_evidence_type"] == "narrative"
    assert result["weakest_link"] == "filing"


def test_all_classes_are_registered_and_outputs_bounded() -> None:
    cases = [
        {},
        {"narrative": _HOT_NARRATIVE},
        {"narrative": _QUIET_NARRATIVE, "filing": _STRONG_FILING,
         "value_chain": {"node_attractiveness": 65.0}},
        {"narrative": _HOT_NARRATIVE, "filing": _RISKY_FILING},
    ]
    for kwargs in cases:
        result = triangulate(**kwargs)
        assert result["triangulation_class"] in TRIANGULATION_CLASSES
        assert 0.0 <= result["triangulation_score"] <= 100.0
        assert 0.0 <= result["contradiction_score"] <= 100.0


def test_missing_layers_reported() -> None:
    result = triangulate(narrative=_HOT_NARRATIVE)
    for layer in ("prediction_market", "filing", "value_chain", "replay"):
        assert layer in result["missing_inputs"]


# ----- integration into opportunity v2 -----

_BASE = {key: 70.0 for key in POSITIVE_COMPONENTS} | {
    key: 20.0 for key in RISK_COMPONENTS
}


def test_contradiction_reduces_opportunity_score() -> None:
    clean = aggregate_opportunity_score_v2(_BASE)
    contradicted = aggregate_opportunity_score_v2(
        _BASE,
        triangulation={
            "triangulation_score": 40.0,
            "contradiction_score": 80.0,
            "independent_source_count": 3,
            "weakest_link": "filing",
        },
    )
    assert contradicted["opportunity_score"] < clean["opportunity_score"]
    assert any(
        "weakest triangulation link" in reason
        for reason in contradicted["why_not_higher"]
    )


def test_triangulation_boosts_confidence_only_when_independent() -> None:
    base = aggregate_opportunity_score_v2(_BASE)
    independent = aggregate_opportunity_score_v2(
        _BASE,
        triangulation={
            "triangulation_score": 85.0,
            "contradiction_score": 0.0,
            "independent_source_count": 3,
            "weakest_link": None,
        },
    )
    single = aggregate_opportunity_score_v2(
        _BASE,
        triangulation={
            "triangulation_score": 85.0,
            "contradiction_score": 0.0,
            "independent_source_count": 1,
            "weakest_link": None,
        },
    )
    assert independent["confidence"] > base["confidence"]
    assert single["confidence"] == base["confidence"]
