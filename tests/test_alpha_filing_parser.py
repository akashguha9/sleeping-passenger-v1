"""Filing parser invariants: hardness weights, lineage, determinism."""

from __future__ import annotations

import pytest

from src.alpha.filing_parser import (
    EVIDENCE_HARDNESS_WEIGHTS,
    SOURCE_TYPE_MULTIPLIER,
    parse_filing_text,
    to_filing_signal,
)

_TEN_K_EXCERPT = """Segment revenue from leak-detection hardware grew 18% year over year.
We entered into a contract with a national homebuilder for sensor deployments.
Free cash flow was $120 million, with cash provided by operating activities of $150 million.
Capital expenditure commitments for the new sensor plant total $40 million.
We are a world-class, market-leading provider of smart water solutions.
Our largest customer represented 22% of consolidated revenue.
We are involved in litigation in two jurisdictions.
There is substantial doubt about our ability to continue as a going concern."""


def test_revenue_segment_outweighs_marketing_claim() -> None:
    parsed = parse_filing_text(_TEN_K_EXCERPT, source_type="10-K")
    by_category = {str(item["category"]): item for item in parsed["evidence"]}
    assert "revenue_segment" in by_category
    revenue_weight = float(by_category["revenue_segment"]["hardness_weight"])
    # Marketing lines are claims, not evidence.
    assert "we are a world-class" not in {
        str(item["evidence_text"]).lower() for item in parsed["evidence"]
    }
    assert parsed["marketing_claims"]
    assert revenue_weight == pytest.approx(
        EVIDENCE_HARDNESS_WEIGHTS["audited_revenue_segment"]
        * SOURCE_TYPE_MULTIPLIER["10-K"]
    )


def test_risk_disclosures_detected_and_scored() -> None:
    parsed = parse_filing_text(_TEN_K_EXCERPT, source_type="10-K")
    risk_categories = {str(item["category"]) for item in parsed["risk_disclosures"]}
    assert "customer_concentration" in risk_categories
    assert "litigation_or_regulatory_risk" in risk_categories
    assert "going_concern_or_liquidity_risk" in risk_categories
    assert parsed["filing_risk_disclosure_score"] > 50.0


def test_claims_without_evidence_classify_simulated() -> None:
    parsed = parse_filing_text(
        "We are a revolutionary, market-leading platform.",
        source_type="investor_presentation",
        narrative_claims=["AI growth story"],
    )
    assert parsed["classification"] == "simulated"
    assert parsed["embedded_proof_score"] == 0.0


def test_multiple_hard_evidence_items_classify_embedded_or_substrate() -> None:
    parsed = parse_filing_text(
        _TEN_K_EXCERPT, source_type="10-K", narrative_claims=["smart water growth"]
    )
    assert parsed["classification"] in ("embedded", "substrate")
    assert parsed["embedded_proof_score"] > 50.0
    assert parsed["substrate_score"] > 0.0


def test_lineage_preserved_with_line_numbers_and_source() -> None:
    parsed = parse_filing_text(
        _TEN_K_EXCERPT, source_type="10-K", source_date="2026-02-01"
    )
    for item in parsed["evidence"] + parsed["risk_disclosures"]:
        assert item["source_type"] == "10-K"
        assert item["source_date"] == "2026-02-01"
        assert isinstance(item["line_number"], int) and item["line_number"] >= 1
        assert item["evidence_text"]
    segment_items = [
        item for item in parsed["evidence"] if item["category"] == "revenue_segment"
    ]
    assert segment_items[0]["line_number"] == 1


def test_earnings_call_discounts_same_text_versus_ten_k() -> None:
    text = "Segment revenue from sensors grew 18%."
    ten_k = parse_filing_text(text, source_type="10-K", narrative_claims=["sensors"])
    call = parse_filing_text(
        text, source_type="earnings_call", narrative_claims=["sensors"]
    )
    assert call["embedded_proof_score"] < ten_k["embedded_proof_score"]


def test_empty_text_is_safe() -> None:
    parsed = parse_filing_text("", source_type="10-K")
    assert parsed["classification"] == "insufficient_evidence"
    assert parsed["evidence"] == []
    assert "filing_text" in parsed["missing_inputs"]


def test_unknown_source_type_is_safe_and_reported() -> None:
    parsed = parse_filing_text(
        "Order backlog increased to $2 billion.", source_type="carrier_pigeon"
    )
    assert any("carrier_pigeon" in note for note in parsed["missing_inputs"])
    assert parsed["evidence"]  # still parsed, just discounted


def test_outputs_deterministic_and_bounded() -> None:
    first = parse_filing_text(_TEN_K_EXCERPT, source_type="10-K")
    second = parse_filing_text(_TEN_K_EXCERPT, source_type="10-K")
    assert first == second
    for key in ("embedded_proof_score", "substrate_score", "filing_risk_disclosure_score"):
        assert 0.0 <= float(first[key]) <= 100.0


def test_to_filing_signal_carries_lineage_and_bounded_confidence() -> None:
    parsed = parse_filing_text(_TEN_K_EXCERPT, source_type="10-K")
    signal = to_filing_signal(parsed, company="Example Co", ticker="EXMPL")
    assert signal.company == "Example Co"
    assert signal.filing_type == "10-K"
    assert 0.0 <= signal.confidence <= 100.0
    assert any("line " in entry for entry in signal.verified_evidence)


def test_hardness_table_ordering_matches_fakability() -> None:
    weights = EVIDENCE_HARDNESS_WEIGHTS
    assert (
        weights["audited_revenue_segment"]
        > weights["contract_or_backlog"]
        >= weights["cash_flow_statement"]
        > weights["regulatory_approval"]
        > weights["capex_commitment"]
        > weights["risk_disclosure"]
        > weights["earnings_call_claim"]
        > weights["investor_presentation_claim"]
        > weights["marketing_claim"]
        > weights["logo_or_collaboration_claim"]
    )
