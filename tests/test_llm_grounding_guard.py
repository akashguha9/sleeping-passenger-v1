"""LLM grounding guard proofs (Pass 4, Phase 8)."""
from __future__ import annotations

import pytest

from scripts import llm_grounding_guard as gg


def _evidence(symbol="ACME", confidence=0.9, freshness_days=1.0,
              contradicts=False, eid="EV-1"):
    return {"evidence_id": eid, "symbol": symbol, "confidence": confidence,
            "freshness_days": freshness_days, "contradicts": contradicts}


def test_unsourced_claim_gets_zero_weight():
    claim = gg.ground_claim(
        claim="ACME revenue grew 40%", symbol="ACME", base_weight=0.5,
        evidence_items=[],
    )
    assert claim.classification == gg.UNSOURCED
    assert claim.weight == 0.0
    assert not claim.scoring_eligible


def test_sourced_claim_can_receive_weight():
    claim = gg.ground_claim(
        claim="ACME revenue grew 40%", symbol="ACME", base_weight=0.5,
        evidence_items=[_evidence()],
    )
    assert claim.classification == gg.SOURCED
    assert claim.weight > 0.0
    assert claim.supporting_evidence_ids == ("EV-1",)
    # weight = base × conf × freshness × penalty, all in [0,1]
    expected = 0.5 * 0.9 * gg.freshness_factor(1.0) * 1.0
    assert claim.weight == pytest.approx(expected)


def test_contradictory_sources_lower_confidence():
    clean = gg.ground_claim(
        claim="ACME wins contract", symbol="ACME", base_weight=0.5,
        evidence_items=[_evidence(), _evidence(eid="EV-2")],
    )
    contradicted = gg.ground_claim(
        claim="ACME wins contract", symbol="ACME", base_weight=0.5,
        evidence_items=[_evidence(), _evidence(eid="EV-2"),
                        _evidence(eid="EV-3", contradicts=True)],
    )
    assert contradicted.weight < clean.weight
    assert contradicted.contradiction_penalty == pytest.approx(2 / 4)
    assert "EV-3" in contradicted.contradicting_evidence_ids


def test_stale_source_lowers_confidence():
    fresh = gg.ground_claim(claim="c", symbol="ACME", base_weight=0.5,
                            evidence_items=[_evidence(freshness_days=0.0)])
    stale = gg.ground_claim(claim="c", symbol="ACME", base_weight=0.5,
                            evidence_items=[_evidence(freshness_days=60.0)])
    assert stale.weight < fresh.weight / 10
    assert gg.freshness_factor(14.0) == pytest.approx(0.5)  # half-life pinned
    assert gg.freshness_factor(None) == 0.5
    assert gg.freshness_factor(-1.0) == 0.0  # published-in-future is wrong, not fresh


def test_hallucinated_ticker_rejected():
    claim = gg.ground_claim(
        claim="ZZZQ is acquiring a unicorn", symbol="ZZZQ", base_weight=0.9,
        evidence_items=[_evidence(symbol="ZZZQ")],  # even "evidence" can't save it
        known_symbols={"ACME", "TSLA"},
    )
    assert claim.classification == gg.REJECTED
    assert claim.weight == 0.0
    assert "hallucination" in claim.note


def test_speculation_is_note_only_even_when_sourced():
    claim = gg.ground_claim(
        claim="ACME might be acquired, rumor has it", symbol="ACME",
        base_weight=0.5, evidence_items=[_evidence()],
    )
    assert claim.classification == gg.SPECULATION
    assert claim.weight == 0.0
    assert "note" in claim.note


def test_inference_without_source_is_zero_weight():
    claim = gg.ground_claim(
        claim="margin will expand given input costs", symbol="ACME",
        base_weight=0.5, evidence_items=[], is_inference=True,
    )
    assert claim.classification == gg.INFERENCE
    assert claim.weight == 0.0


def test_weight_factors_bounded():
    with pytest.raises(ValueError):
        gg.ground_claim(claim="c", symbol="A", base_weight=1.5, evidence_items=[])
    claim = gg.ground_claim(
        claim="c", symbol="ACME", base_weight=1.0,
        evidence_items=[_evidence(confidence=1.0, freshness_days=0.0)],
    )
    assert 0.0 <= claim.source_confidence <= 1.0
    assert 0.0 <= claim.freshness_factor <= 1.0
    assert 0.0 <= claim.contradiction_penalty <= 1.0
    assert claim.weight <= 1.0


def test_recommendation_states_its_evidence():
    claims = [
        gg.ground_claim(claim="sourced fact", symbol="ACME", base_weight=0.4,
                        evidence_items=[_evidence()]),
        gg.ground_claim(claim="unsourced vibe", symbol="ACME", base_weight=0.4,
                        evidence_items=[]),
    ]
    contribution = gg.grounded_score_contribution(claims)
    assert contribution["eligible_claims"] == 1
    assert contribution["excluded_claims"] == 1
    assert contribution["evidence_trail"] == ["EV-1"]
    assert contribution["exclusions"][0]["classification"] == gg.UNSOURCED
    assert contribution["advisory_only"] is True
