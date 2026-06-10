"""Module D — embedded proof detector.

Separates three layers of a theme claim:

- simulated:  the company *claims* AI/crypto/sustainability exposure but
              evidence is weak (yogurt *flavoured* ice cream).
- embedded:   filings/products/contracts show real exposure (fruit
              pieces in the yogurt — receipts, not essence).
- substrate:  the company is structurally built around the theme (the
              yogurt *is* the base, no chunks needed).

proof_density = verified_evidence / max(1, narrative_claims).  Embedded
proof validates a claim; it does not guarantee residual utility — strip
it and re-score with the residual utility engine.
"""

from __future__ import annotations

from src.utils.math_utils import clamp01, clip

CLASSIFICATIONS = ("simulated", "embedded", "substrate", "insufficient_evidence")

# Evidence kinds and how hard they are to fake.  Unknown kinds get the
# default weight.  TODO: extend with parsed-filing scoring when a filings
# ingestion adapter lands (offline stubs only for now).
EVIDENCE_KIND_WEIGHTS: dict[str, float] = {
    "revenue_segment": 1.0,
    "audited_financials": 1.0,
    "signed_contract": 0.9,
    "regulatory_filing": 0.9,
    "shipped_product": 0.8,
    "capex_commitment": 0.7,
    "patent": 0.6,
    "job_postings": 0.4,
    "press_release": 0.2,
    "logo_or_collab": 0.15,
}
_DEFAULT_EVIDENCE_WEIGHT = 0.4

_SUBSTRATE_THRESHOLD = 60.0
_SIMULATED_DENSITY_THRESHOLD = 0.25


def _evidence_weight(item: dict[str, object] | str) -> float:
    if isinstance(item, str):
        return EVIDENCE_KIND_WEIGHTS.get(item, _DEFAULT_EVIDENCE_WEIGHT)
    kind = str(item.get("kind", ""))
    return EVIDENCE_KIND_WEIGHTS.get(kind, _DEFAULT_EVIDENCE_WEIGHT)


def detect_embedded_proof(
    narrative_claims: list[str] | None = None,
    verified_evidence: list[dict[str, object] | str] | None = None,
    *,
    theme_revenue_share: float | None = None,
    structurally_theme_native: bool = False,
) -> dict[str, object]:
    """Classify theme exposure as simulated, embedded, or substrate.

    ``verified_evidence`` items are either evidence-kind strings or dicts
    with a ``kind`` key (see ``EVIDENCE_KIND_WEIGHTS``).
    ``theme_revenue_share`` is the fraction of revenue attributable to the
    theme, in [0, 1], if known.
    """
    claims = list(narrative_claims or [])
    evidence = list(verified_evidence or [])
    missing_inputs: list[str] = []

    proof_density = len(evidence) / max(1, len(claims))
    weighted_evidence = sum(_evidence_weight(item) for item in evidence)
    # Two strong pieces of evidence per claim saturate the score.
    embedded_proof_score = clip(
        100.0 * weighted_evidence / max(1.0, 2.0 * max(1, len(claims))),
        0.0,
        100.0,
    )

    if theme_revenue_share is None:
        missing_inputs.append("theme_revenue_share")
        revenue_component = 0.0
    else:
        revenue_component = 70.0 * clamp01(theme_revenue_share)
    substrate_score = clip(
        revenue_component + (30.0 if structurally_theme_native else 0.0),
        0.0,
        100.0,
    )

    if not claims and not evidence:
        classification = "insufficient_evidence"
    elif substrate_score >= _SUBSTRATE_THRESHOLD:
        classification = "substrate"
    elif proof_density < _SIMULATED_DENSITY_THRESHOLD and embedded_proof_score < 25.0:
        classification = "simulated"
    else:
        classification = "embedded"

    explanation = [
        f"{len(evidence)} verified evidence item(s) against {len(claims)} "
        f"narrative claim(s): proof density {proof_density:.2f}.",
        f"Embedded proof score {embedded_proof_score:.1f}/100 "
        "(evidence weighted by how hard it is to fake).",
        f"Substrate score {substrate_score:.1f}/100 "
        "(is the theme the base, or an inclusion?).",
        f"Classification: {classification}.",
        "Embedded proof is evidence, not essence — strip it and re-score "
        "residual utility before trusting the claim.",
    ]
    return {
        "embedded_proof_score": embedded_proof_score,
        "substrate_score": substrate_score,
        "proof_density": proof_density,
        "classification": classification,
        "evidence": evidence,
        "claims": claims,
        "missing_inputs": missing_inputs,
        "explanation": explanation,
    }
