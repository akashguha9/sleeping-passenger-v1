"""Filing parser negation/risk guard."""

from __future__ import annotations

from src.alpha.filing_parser import parse_filing_text


def test_negated_revenue_claim_is_not_proof() -> None:
    parsed = parse_filing_text(
        "We do not currently generate segment revenue from AI products.",
        source_type="10-K",
        narrative_claims=["AI revenue"],
    )
    assert parsed["evidence"] == []
    assert parsed["negated_statements"]
    assert parsed["embedded_proof_score"] == 0.0
    assert parsed["classification"] == "simulated"


def test_no_material_concentration_reduces_risk_not_raises_it() -> None:
    with_risk = parse_filing_text(
        "Our largest customer represented 30% of revenue.\n"
        "We are involved in litigation in two jurisdictions.",
        source_type="10-K",
    )
    mitigated = parse_filing_text(
        "There is no material customer concentration.\n"
        "We are involved in litigation in two jurisdictions.",
        source_type="10-K",
    )
    assert mitigated["risk_mitigations"]
    assert (
        mitigated["filing_risk_disclosure_score"]
        < with_risk["filing_risk_disclosure_score"]
    )


def test_modal_statement_is_forward_looking_not_evidence() -> None:
    parsed = parse_filing_text(
        "We may enter into a contract with a national homebuilder next year.",
        source_type="10-K",
        narrative_claims=["builder demand"],
    )
    assert parsed["evidence"] == []
    assert parsed["forward_looking_claims"]


def test_modal_risk_is_still_a_risk_disclosure() -> None:
    parsed = parse_filing_text(
        "We may face supplier dependency on a limited number of suppliers.",
        source_type="10-K",
    )
    categories = {item["category"] for item in parsed["risk_disclosures"]}
    assert "supplier_dependency" in categories
    assert parsed["evidence"] == []


def test_hard_evidence_still_counts() -> None:
    parsed = parse_filing_text(
        "Order backlog increased to $500 million at year end.",
        source_type="10-K",
        narrative_claims=["demand"],
    )
    assert len(parsed["evidence"]) == 1
    assert parsed["evidence"][0]["category"] == "order_backlog"
    assert parsed["embedded_proof_score"] > 0.0


def test_lineage_preserved_for_negated_and_mitigated_lines() -> None:
    parsed = parse_filing_text(
        "We do not generate segment revenue from crypto.\n"
        "There is no material customer concentration.",
        source_type="10-Q",
    )
    assert parsed["negated_statements"][0]["line_number"] == 1
    assert parsed["risk_mitigations"][0]["line_number"] == 2


def test_negation_window_does_not_overreach() -> None:
    # The negation is far outside the token window; evidence still counts.
    parsed = parse_filing_text(
        "It is not unusual for industry peers to struggle; in contrast this "
        "year our audited results were strong and segment revenue from "
        "water products grew 12%.",
        source_type="10-K",
        narrative_claims=["water growth"],
    )
    assert len(parsed["evidence"]) == 1


def test_guarded_parser_remains_deterministic_and_bounded() -> None:
    text = (
        "We do not generate segment revenue from AI.\n"
        "Order backlog increased to $500m.\n"
        "There is no material customer concentration.\n"
        "We may face supplier dependency risks."
    )
    first = parse_filing_text(text, source_type="10-K")
    second = parse_filing_text(text, source_type="10-K")
    assert first == second
    for key in (
        "embedded_proof_score",
        "substrate_score",
        "filing_risk_disclosure_score",
    ):
        assert 0.0 <= float(first[key]) <= 100.0
