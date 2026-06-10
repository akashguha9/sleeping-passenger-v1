"""Alpha autopsy: the system explaining itself to a hostile auditor.

Takes the outputs of the framework modules for one signal and produces a
read-only diagnostic: what survives blind testing (measured, not
asserted, via the blind-test differential), what was only casino energy,
what proof exists, what proof is missing, and exactly which evidence to
collect next.  Advisory-only; an autopsy never recommends action.
"""

from __future__ import annotations

from src.alpha import ADVISORY_DISCLAIMER
from src.alpha.blind_test import blind_test_differential
from src.utils.math_utils import clip


def _calibration_state(calibration_support: float) -> str:
    support = clip(calibration_support, 0.0, 100.0)
    if support < 10.0:
        return (
            f"uncalibrated ({support:.0f}/100): no outcome-backed history; "
            "verdicts are capped at deep_research"
        )
    if support < 30.0:
        return f"early calibration ({support:.0f}/100): conservative unlocks only"
    if support < 60.0:
        return f"partial calibration ({support:.0f}/100): thin outcome history"
    return f"calibrated ({support:.0f}/100): replay-backed advisory confidence"


def build_alpha_autopsy(
    *,
    signal_name: str,
    components: dict[str, float] | None = None,
    opportunity: dict[str, object] | None = None,
    filing_parse: dict[str, object] | None = None,
    triangulation: dict[str, object] | None = None,
    residual_utility: dict[str, object] | None = None,
    half_life: dict[str, object] | None = None,
    value_chain_node: str | None = None,
    calibration_support: float = 0.0,
    **v2_kwargs: object,
) -> dict[str, object]:
    """Build the auditor-facing autopsy for one signal.

    ``components``/``v2_kwargs`` are the scoring inputs (used for the
    blind-test differential); the remaining arguments are the already-
    computed module outputs.  Everything is optional and degrades to an
    explicit gap in the report rather than a crash.
    """
    provided = dict(components or {})
    blind = blind_test_differential(provided, **v2_kwargs)
    opportunity = opportunity or {}
    trap_flags = list(opportunity.get("trap_flags") or [])

    survives: list[str] = []
    casino_only: list[str] = []
    if blind["survives_blind_test"]:
        survives.append(
            f"blind score {blind['blind_score']:.1f}/100 with narrative and "
            "casino inputs neutralized"
        )
    for key, label in (
        ("embedded_proof", "embedded proof"),
        ("food_chain", "food-chain economics"),
        ("residual_utility", "residual utility"),
        ("node_strength", "value-chain node strength"),
    ):
        if float(provided.get(key, 0.0)) >= 60.0:
            survives.append(f"{label} ({provided[key]:.0f}/100)")
    if blind["blind_class"] == "story_carried":
        casino_only.append(
            f"the story contributes {blind['narrative_contribution']:+.1f} "
            "points and the signal fails blind testing without it"
        )
    if float(provided.get("casino_distortion", 0.0)) >= 60.0:
        casino_only.append(
            f"casino distortion {provided['casino_distortion']:.0f}/100"
        )
    if float(provided.get("narrative_velocity", 0.0)) >= 70.0 and float(
        provided.get("embedded_proof", 100.0)
    ) < 40.0:
        casino_only.append("attention is running far ahead of proof")

    embedded_proof: list[str] = []
    missing_proof: list[str] = []
    if filing_parse is not None:
        for item in list(filing_parse.get("evidence") or [])[:10]:
            embedded_proof.append(
                f"{item.get('category')} (line {item.get('line_number')}): "
                f"{item.get('evidence_text')}"
            )
        for item in list(filing_parse.get("negated_statements") or []):
            missing_proof.append(
                f"explicitly negated in source: {item.get('text')}"
            )
        if not filing_parse.get("evidence"):
            missing_proof.append("no hard evidence found in supplied filings")
    else:
        missing_proof.append("no filing parse supplied")
    for key in list(opportunity.get("missing_inputs") or []):
        missing_proof.append(f"scoring input missing: {key}")

    next_evidence: list[str] = []
    if calibration_support < 10.0:
        next_evidence.append(
            "resolve more advisory outcomes through the journal-to-replay "
            "bridge (calibration_support gates every position verdict)"
        )
    if float(provided.get("embedded_proof", 0.0)) < 60.0:
        next_evidence.append(
            "segment-revenue or contract/backlog disclosure tying the theme "
            "to audited numbers"
        )
    if triangulation is not None:
        weakest = triangulation.get("weakest_link")
        if weakest:
            next_evidence.append(f"strengthen weakest triangulation layer: {weakest}")
        if "prediction_market" in list(triangulation.get("missing_inputs") or []):
            next_evidence.append(
                "a priced event probability (prediction-market quote) for the "
                "nearest catalyst"
            )
        if "narrative" in list(triangulation.get("missing_inputs") or []):
            next_evidence.append("narrative snapshots to measure attention velocity")
    if not next_evidence:
        next_evidence.append(
            "re-run after the next filing cycle to refresh proof lineage"
        )

    verdict = str(opportunity.get("advisory_verdict", "unscored"))
    summary = (
        f"{signal_name}: verdict '{verdict}'. "
        f"Blind test: {blind['blind_class']} "
        f"(labelled {blind['labelled_score']:.1f} vs blind "
        f"{blind['blind_score']:.1f}). "
        f"{_calibration_state(calibration_support)}."
    )
    return {
        "summary": summary,
        "signal_name": signal_name,
        "what_survives_blind_test": survives,
        "what_was_only_casino": casino_only,
        "blind_test": blind,
        "embedded_proof": embedded_proof,
        "missing_proof": missing_proof,
        "value_chain_node": value_chain_node or "unmapped",
        "residual_utility": (
            f"{residual_utility.get('residual_utility_class', 'unclassified')} "
            f"({float(residual_utility.get('residual_utility_score', 0.0)):.1f}/100)"
            if residual_utility is not None
            else "not assessed"
        ),
        "half_life": (
            f"{half_life.get('signal_type', 'unknown')} "
            f"(t1/2 ~ {float(half_life.get('half_life_days', 0.0)):.0f} days)"
            if half_life is not None
            else "not assessed"
        ),
        "trap_flags": trap_flags,
        "triangulation_class": (
            triangulation.get("triangulation_class") if triangulation else "not assessed"
        ),
        "calibration_state": _calibration_state(calibration_support),
        "verdict_explanation": (
            f"Verdict '{verdict}' is bounded by evidence: "
            + "; ".join(
                str(reason) for reason in list(opportunity.get("why_not_higher") or [])[:4]
            )
            if opportunity.get("why_not_higher")
            else f"Verdict '{verdict}' from supplied component scores."
        ),
        "next_evidence_to_collect": next_evidence,
        "disclaimer": ADVISORY_DISCLAIMER,
    }
