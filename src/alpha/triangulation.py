"""Cross-source triangulation engine.

Decides whether a signal is supported by multiple INDEPENDENT evidence
layers — narrative attention, prediction-market pricing, filing proof,
value-chain position, replay calibration — or is one loud source
agreeing with itself.

    Triangulation =
      100 × weighted_mean(source_independence, cross_source_agreement,
                          evidence_hardness, value_chain_alignment,
                          replay_support)
      − contradiction_penalty

Classes:
    single_source_hype          one source, and it is the narrative
    weakly_supported            thin or low-agreement evidence
    mixed_evidence              several sources, partial agreement
    quiet_food_chain_candidate  weak narrative, strong filings/value chain
    strongly_triangulated       3+ independent sources in agreement
    contradicted                evidence layers actively disagree
"""

from __future__ import annotations

from src.utils.math_utils import clip

TRIANGULATION_CLASSES = (
    "single_source_hype",
    "weakly_supported",
    "mixed_evidence",
    "quiet_food_chain_candidate",
    "strongly_triangulated",
    "contradicted",
)

# Independent evidence layers (replay is meta-support, not a source).
_SOURCE_KEYS = ("narrative", "prediction_market", "filing", "value_chain")

_WEIGHTS = {
    "source_independence": 0.20,
    "cross_source_agreement": 0.25,
    "evidence_hardness": 0.25,
    "value_chain_alignment": 0.15,
    "replay_support": 0.15,
}


def triangulate(
    *,
    narrative: dict[str, object] | None = None,
    prediction_market: dict[str, object] | None = None,
    filing: dict[str, object] | None = None,
    value_chain: dict[str, object] | None = None,
    replay: dict[str, object] | None = None,
) -> dict[str, object]:
    """Triangulate a signal across independent evidence layers.

    Expected (all optional, all degrade safely):
      narrative:         {"narrative_velocity_score", "confidence"}
      prediction_market: {"probability_edge", "confidence"}
      filing:            {"embedded_proof_score", "filing_risk_disclosure_score"}
      value_chain:       {"node_attractiveness"}
      replay:            {"calibration_support"}
    """
    missing_inputs: list[str] = []
    support: dict[str, float] = {}

    if narrative is not None:
        support["narrative"] = clip(
            float(narrative.get("narrative_velocity_score", 50.0)), 0.0, 100.0
        )
    else:
        missing_inputs.append("narrative")
    if prediction_market is not None:
        edge = float(prediction_market.get("probability_edge", 0.0))
        pm_confidence = clip(
            float(prediction_market.get("confidence", 0.0)), 0.0, 100.0
        )
        support["prediction_market"] = clip(
            50.0 + 100.0 * edge * (pm_confidence / 100.0), 0.0, 100.0
        )
    else:
        missing_inputs.append("prediction_market")
    if filing is not None:
        support["filing"] = clip(
            float(filing.get("embedded_proof_score", 0.0)), 0.0, 100.0
        )
    else:
        missing_inputs.append("filing")
    if value_chain is not None:
        support["value_chain"] = clip(
            float(value_chain.get("node_attractiveness", 50.0)), 0.0, 100.0
        )
    else:
        missing_inputs.append("value_chain")

    replay_support = (
        clip(float(replay.get("calibration_support", 0.0)), 0.0, 100.0)
        if replay is not None
        else 0.0
    )
    if replay is None:
        missing_inputs.append("replay")

    independent_source_count = len(support)
    source_independence = clip(
        100.0 * independent_source_count / len(_SOURCE_KEYS), 0.0, 100.0
    )

    values = list(support.values())
    if len(values) >= 2:
        diffs = [
            abs(a - b) for i, a in enumerate(values) for b in values[i + 1 :]
        ]
        agreement = clip(100.0 - sum(diffs) / len(diffs), 0.0, 100.0)
    else:
        agreement = 0.0  # one source cannot agree with anything

    evidence_hardness = support.get("filing", 0.0)
    value_chain_alignment = support.get("value_chain", 0.0)

    # ----- contradictions: layers that actively disagree -----
    contradiction = 0.0
    contradiction_notes: list[str] = []
    narrative_level = support.get("narrative")
    filing_level = support.get("filing")
    pm_level = support.get("prediction_market")
    filing_risk = (
        clip(float(filing.get("filing_risk_disclosure_score", 0.0)), 0.0, 100.0)
        if filing is not None
        else 0.0
    )
    if narrative_level is not None and filing_level is not None:
        if narrative_level >= 70.0 and filing_level < 35.0:
            contradiction += 40.0
            contradiction_notes.append("loud narrative contradicted by weak filings")
        if narrative_level >= 70.0 and filing_risk >= 60.0:
            contradiction += 30.0
            contradiction_notes.append(
                "loud narrative against heavy risk disclosures"
            )
    if pm_level is not None and narrative_level is not None:
        if narrative_level >= 70.0 and pm_level < 35.0:
            contradiction += 20.0
            contradiction_notes.append(
                "prediction market prices against the narrative"
            )
    if filing_level is not None and filing_level >= 60.0 and filing_risk >= 70.0:
        contradiction += 20.0
        contradiction_notes.append("hard proof shadowed by severe risk disclosures")
    contradiction = clip(contradiction, 0.0, 100.0)

    base = (
        _WEIGHTS["source_independence"] * source_independence
        + _WEIGHTS["cross_source_agreement"] * agreement
        + _WEIGHTS["evidence_hardness"] * evidence_hardness
        + _WEIGHTS["value_chain_alignment"] * value_chain_alignment
        + _WEIGHTS["replay_support"] * replay_support
    )
    triangulation_score = clip(base - 0.5 * contradiction, 0.0, 100.0)

    dominant = max(support, key=support.get) if support else None
    weakest = min(support, key=support.get) if support else None

    # ----- classification -----
    if contradiction >= 50.0:
        triangulation_class = "contradicted"
    elif independent_source_count <= 1 and dominant == "narrative":
        triangulation_class = "single_source_hype"
    elif (
        narrative_level is not None
        and narrative_level < 40.0
        and filing_level is not None
        and filing_level >= 60.0
        and value_chain_alignment >= 55.0
    ):
        triangulation_class = "quiet_food_chain_candidate"
    elif (
        independent_source_count >= 3
        and agreement >= 60.0
        and triangulation_score >= 60.0
    ):
        triangulation_class = "strongly_triangulated"
    elif independent_source_count >= 2 and triangulation_score >= 40.0:
        triangulation_class = "mixed_evidence"
    else:
        triangulation_class = "weakly_supported"

    return {
        "triangulation_score": triangulation_score,
        "independent_source_count": independent_source_count,
        "agreement_score": agreement,
        "contradiction_score": contradiction,
        "dominant_evidence_type": dominant,
        "weakest_link": weakest,
        "triangulation_class": triangulation_class,
        "support_levels": support,
        "replay_support": replay_support,
        "contradiction_notes": contradiction_notes,
        "missing_inputs": missing_inputs,
        "explanation": [
            f"{independent_source_count} independent evidence layer(s); "
            f"agreement {agreement:.0f}/100.",
            f"Hardness (filings) {evidence_hardness:.0f}, value-chain "
            f"alignment {value_chain_alignment:.0f}, replay support "
            f"{replay_support:.0f}.",
            f"Contradiction {contradiction:.0f}/100"
            + (f" ({'; '.join(contradiction_notes)})" if contradiction_notes else "")
            + f" -> {triangulation_class} ({triangulation_score:.1f}/100).",
        ],
    }
