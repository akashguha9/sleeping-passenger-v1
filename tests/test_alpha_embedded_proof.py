"""Module D — embedded proof detector invariants."""

from __future__ import annotations

from src.alpha.embedded_proof import detect_embedded_proof


def test_no_claims_no_evidence_is_insufficient() -> None:
    result = detect_embedded_proof()
    assert result["classification"] == "insufficient_evidence"
    assert "theme_revenue_share" in result["missing_inputs"]


def test_claims_without_evidence_is_simulated() -> None:
    result = detect_embedded_proof(
        narrative_claims=["AI-first platform", "crypto rails", "sustainable ops"],
        verified_evidence=[],
        theme_revenue_share=0.0,
    )
    assert result["classification"] == "simulated"
    assert result["proof_density"] == 0.0


def test_real_evidence_is_embedded() -> None:
    result = detect_embedded_proof(
        narrative_claims=["AI revenue growth"],
        verified_evidence=["revenue_segment", "signed_contract"],
        theme_revenue_share=0.2,
    )
    assert result["classification"] == "embedded"
    assert result["embedded_proof_score"] > 0


def test_theme_native_majority_revenue_is_substrate() -> None:
    result = detect_embedded_proof(
        narrative_claims=["pure-play theme exposure"],
        verified_evidence=["revenue_segment", "audited_financials"],
        theme_revenue_share=0.9,
        structurally_theme_native=True,
    )
    assert result["classification"] == "substrate"
    assert result["substrate_score"] >= 60.0


def test_logo_collab_is_weaker_evidence_than_revenue_segment() -> None:
    logo = detect_embedded_proof(
        narrative_claims=["brand collab"], verified_evidence=["logo_or_collab"]
    )
    revenue = detect_embedded_proof(
        narrative_claims=["brand collab"], verified_evidence=["revenue_segment"]
    )
    assert revenue["embedded_proof_score"] > logo["embedded_proof_score"]


def test_proof_density_formula() -> None:
    result = detect_embedded_proof(
        narrative_claims=["a", "b"],
        verified_evidence=["revenue_segment", "patent", "shipped_product"],
    )
    assert result["proof_density"] == 1.5


def test_scores_bounded_even_with_huge_evidence_lists() -> None:
    result = detect_embedded_proof(
        narrative_claims=["one claim"],
        verified_evidence=["revenue_segment"] * 50,
        theme_revenue_share=5.0,  # out of range, must clamp
    )
    assert 0.0 <= result["embedded_proof_score"] <= 100.0
    assert 0.0 <= result["substrate_score"] <= 100.0


def test_explanation_states_proof_is_not_essence() -> None:
    result = detect_embedded_proof(narrative_claims=["x"], verified_evidence=["patent"])
    assert any("essence" in line for line in result["explanation"])
