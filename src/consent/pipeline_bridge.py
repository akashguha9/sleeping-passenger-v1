"""Consent-to-candidate pipeline bridge: evidence becomes decision physics.

The bridge turns the consent layer from a parked forensic scorer into an
automatic decision modifier. Inside ``evaluate_candidate_payload``:

  1. evidence fields are detected (``consent_profile``, ``complaint_texts``,
     ``consumer_evidence``, ``complaint_evidence``, ``regulatory_evidence``,
     ``customer_reviews``),
  2. an evidence bundle is built (dedup, language, reliability),
  3. the consent profile, jurisdiction map, anti-gaming analysis, and
     dark-pattern chain are computed,
  4. consent risk factors flow into the crash wall (scaled by reliability),
  5. after the cherry-pick decision, multipliers/penalties/caps adjust the
     final score and ladder state,
  6. everything is recorded in a deterministic decision ledger:
     no hidden magic, no unexplained downgrade, no fake certainty.

Core rule: a financially attractive candidate with severe, reliable
consent/regulatory evidence must not receive a clean Buy. Clean evidence
must not be punished. Missing evidence stays neutral with a warning.
"""

from __future__ import annotations

from src.utils.validation_utils import section_dict as _section

from dataclasses import asdict, dataclass, field
from typing import Any

from src.consent.anti_gaming import (
    AntiGamingReport,
    analyze_positive_evidence,
    apply_refutations,
)
from src.consent.dark_pattern_chain import (
    DarkPatternChainReport,
    detect_dark_pattern_chain,
)
from src.consent.evidence_reliability import RELIABILITY_HIGH, RELIABILITY_LOW
from src.consent.ingestion import EvidenceBundle, build_evidence_bundle
from src.consent.jurisdiction import (
    JurisdictionRiskMap,
    VULNERABLE_SEGMENTS_FOR_JURISDICTION,
    build_jurisdiction_risk_map,
)
from src.consent.revenue_quality import (
    evaluate_consent_profile,
    to_simulator_risk_factors,
)
from src.utils.math_utils import clamp01, clip
from src.utils.validation_utils import coerce_float

EVIDENCE_FIELDS: tuple[str, ...] = (
    "complaint_texts",
    "consumer_evidence",
    "complaint_evidence",
    "regulatory_evidence",
    "customer_reviews",
)

# Severity thresholds for cap decisions (0–10 layer scores).
SEVERE_LAYER_THRESHOLD = 7.0
SEVERE_CHAIN_THRESHOLD = 6.0

# Ladder cap by reliability band when severe risk is present.
_SEVERE_CAPS = {
    "high": "watchlist",
    "medium": "active_watch",
    "low": "buy_candidate",
}

# Which evidence categories each cap-relevant layer rests on (refutation
# routing for the anti-gaming rules).
_LAYER_CATEGORY_MAP: dict[str, list[str]] = {
    "subscription_extraction": [
        "cannot_cancel", "charged_after_cancellation", "lock_in",
    ],
    "claims_non_payment": ["claims_non_payment"],
    "friction_tax": [
        "email_only_relief", "bot_only_support", "language_burden",
        "processing_delay",
    ],
    "regulatory_fragility": [
        "charged_after_cancellation", "cannot_cancel", "claims_non_payment",
        "hidden_fees",
    ],
}

ADVISORY_NOTICE = (
    "ADVISORY_ONLY — consent adjustment explains and caps research "
    "verdicts; it places no orders, asserts no legal guilt, and infers "
    "no intent."
)


@dataclass(slots=True)
class ConsentDecisionLedger:
    """Deterministic, machine-readable record of what consent did."""

    input_summary: dict[str, Any] = field(default_factory=dict)
    evidence_sources: list[str] = field(default_factory=list)
    deduplication_summary: dict[str, int] = field(default_factory=dict)
    detected_terms: list[str] = field(default_factory=list)
    layer_scores: dict[str, float] = field(default_factory=dict)
    evidence_reliability_score: float = 0.0
    reliability_band: str = "none"
    multipliers_applied: dict[str, float] = field(default_factory=dict)
    penalties_applied: dict[str, float] = field(default_factory=dict)
    risk_caps_applied: list[str] = field(default_factory=list)
    simulator_factors_added: dict[str, float] = field(default_factory=dict)
    jurisdiction_domains: dict[str, float] = field(default_factory=dict)
    dark_pattern_chain: dict[str, Any] = field(default_factory=dict)
    anti_gaming: dict[str, Any] = field(default_factory=dict)
    recommendation_before_consent: str = ""
    recommendation_after_consent: str = ""
    score_before_consent: float = 0.0
    score_after_consent: float = 0.0
    warnings: list[str] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    advisory_only_notice: str = ADVISORY_NOTICE

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ConsentBridgeContext:
    """Everything the bridge computed before the cherry-pick decision."""

    evidence_present: bool
    bundle: EvidenceBundle | None
    profile: dict[str, Any] | None
    jurisdiction_map: JurisdictionRiskMap | None
    chain: DarkPatternChainReport | None
    anti_gaming: AntiGamingReport | None
    reliability_factor: float
    risk_factors: dict[str, float] = field(default_factory=dict)
    adjusted_layer_scores: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _collect_evidence(payload: dict[str, Any]) -> list[Any]:
    """Gather all evidence items; regulatory items default to a
    regulator-action source type when unattributed."""
    items: list[Any] = []
    for fieldname in EVIDENCE_FIELDS:
        value = payload.get(fieldname)
        if not isinstance(value, list):
            continue
        for item in value:
            if fieldname == "regulatory_evidence":
                if isinstance(item, str):
                    item = {"text": item, "source_type": "regulator_action"}
                elif isinstance(item, dict) and not item.get("source_type"):
                    item = {**item, "source_type": "regulator_action"}
            items.append(item)
    return items


def prepare_consent_context(payload: dict[str, Any]) -> ConsentBridgeContext:
    """Run evidence → bundle → profile → reliability → chain, pre-decision."""
    evidence_items = _collect_evidence(payload)
    precomputed = payload.get("consent_profile")
    has_precomputed = isinstance(precomputed, dict) and bool(precomputed)

    if not evidence_items and not has_precomputed:
        return ConsentBridgeContext(
            evidence_present=False,
            bundle=None,
            profile=None,
            jurisdiction_map=None,
            chain=None,
            anti_gaming=None,
            reliability_factor=0.0,
            warnings=[
                "insufficient_data: no consumer evidence supplied — consent "
                "layer neutral, candidate unadjusted"
            ],
        )

    bundle = build_evidence_bundle(evidence_items) if evidence_items else None
    texts = bundle.texts if bundle else []
    segment = str(
        payload.get("customer_segment")
        or _section(payload.get("consent_inputs")).get("segment")
        or "general"
    )

    if has_precomputed:
        profile = dict(precomputed)
    else:
        consent_inputs = dict(_section(payload.get("consent_inputs")))
        consent_inputs["complaint_texts"] = texts
        consent_inputs.setdefault("company", str(payload.get("ticker", "UNKNOWN")))
        consent_inputs.setdefault("segment", segment)
        profile = evaluate_consent_profile(consent_inputs)

    reliability = bundle.reliability if bundle else None
    reliability_score = reliability.score if reliability else (
        5.0 if has_precomputed else 0.0
    )
    reliability_factor = clamp01(reliability_score / 10.0)
    warnings: list[str] = list(bundle.warnings) if bundle else []
    if has_precomputed and not evidence_items:
        warnings.append(
            "precomputed consent_profile accepted without raw evidence — "
            "reliability assumed mid-band (5.0)"
        )

    anti_gaming = analyze_positive_evidence(texts) if texts else None

    # Anti-gaming: category-specific refutations and resolution evidence
    # reduce the cap-relevant layer scores before severity is judged.
    layer_scores = {
        layer: coerce_float((profile.get(layer) or {}).get("score"))
        for layer in _LAYER_CATEGORY_MAP
    }
    if anti_gaming and (
        anti_gaming.refutations_by_category or anti_gaming.resolution_relief
    ):
        adjusted_layers = apply_refutations(
            layer_scores, _LAYER_CATEGORY_MAP, anti_gaming
        )
    else:
        adjusted_layers = dict(layer_scores)

    jurisdiction_map = build_jurisdiction_risk_map(
        complaint_texts=texts,
        jurisdiction=str(payload.get("jurisdiction", "")),
        segment=segment,
    ) if texts else None

    chain = detect_dark_pattern_chain(
        complaint_texts=texts,
        reliability_factor=reliability_factor,
        vulnerable_segment=segment.lower()
        in VULNERABLE_SEGMENTS_FOR_JURISDICTION,
        collection_capabilities=(
            _section(_section(payload.get("consent_inputs")).get("capabilities"))
        ).get("collection"),
    ) if texts else None

    # Crash-wall factors, scaled by reliability so an unreliable anecdote
    # cannot detonate the crash gate.
    raw_factors = to_simulator_risk_factors(profile)
    if chain and chain.score > 0:
        raw_factors["dark_pattern_chain"] = chain.score / 10.0
    factors = {
        name: clamp01(value * max(reliability_factor, 0.25))
        for name, value in raw_factors.items()
        if value > 0
    }

    return ConsentBridgeContext(
        evidence_present=True,
        bundle=bundle,
        profile=profile,
        jurisdiction_map=jurisdiction_map,
        chain=chain,
        anti_gaming=anti_gaming,
        reliability_factor=reliability_factor,
        risk_factors=factors,
        adjusted_layer_scores=adjusted_layers,
        warnings=warnings,
    )


def _harm_evidenced(context: ConsentBridgeContext) -> bool:
    """True only when actual harm-category evidence exists.

    Absence of structured consent inputs makes the profile conservative,
    but conservatism from ignorance must never be treated as evidence of
    harm when judging severity or applying multipliers.
    """
    if context.bundle is not None:
        return bool(context.bundle.categories_detected)
    return any(v >= 2.0 for v in context.adjusted_layer_scores.values())


def _severe_risk(context: ConsentBridgeContext) -> tuple[bool, list[str]]:
    if not _harm_evidenced(context):
        return False, []
    reasons: list[str] = []
    layers = context.adjusted_layer_scores
    if layers.get("subscription_extraction", 0.0) >= SEVERE_LAYER_THRESHOLD:
        reasons.append("subscription_extraction")
    if layers.get("claims_non_payment", 0.0) >= SEVERE_LAYER_THRESHOLD:
        reasons.append("claims_non_payment")
    if layers.get("regulatory_fragility", 0.0) >= SEVERE_LAYER_THRESHOLD:
        reasons.append("regulatory_fragility")
    if context.chain and context.chain.score >= SEVERE_CHAIN_THRESHOLD:
        reasons.append("dark_pattern_chain")
    profile = context.profile or {}
    if profile.get("revenue_quality_label") == "extractive_risk":
        reasons.append("extractive_revenue_label")
    return bool(reasons), reasons


def _reliability_band(context: ConsentBridgeContext) -> str:
    score = context.reliability_factor * 10.0
    if score >= RELIABILITY_HIGH:
        return "high"
    if score >= RELIABILITY_LOW:
        return "medium"
    return "low"


def apply_consent_adjustment(
    *,
    context: ConsentBridgeContext,
    score_before: float,
    state_before: str,
    ladder_states: tuple[str, ...],
) -> ConsentDecisionLedger:
    """Compute multipliers, penalties, and caps; emit the ledger.

    ``ladder_states`` is the ordered promotion ladder so caps demote
    deterministically. Interrupt states (pit_stop/black_flag) pass through
    untouched — the driver layer outranks consent.
    """
    ledger = ConsentDecisionLedger(
        recommendation_before_consent=state_before,
        recommendation_after_consent=state_before,
        score_before_consent=score_before,
        score_after_consent=score_before,
        warnings=list(context.warnings),
    )

    if not context.evidence_present:
        ledger.rationale.append(
            "no consumer evidence — neutral pass-through with "
            "insufficient_data warning"
        )
        return ledger

    profile = context.profile or {}
    bundle = context.bundle
    ledger.input_summary = {
        "evidence_records": bundle.record_count if bundle else 0,
        "unique_records": bundle.unique_count if bundle else 0,
        "languages": bundle.languages_detected if bundle else [],
        "categories": bundle.categories_detected if bundle else [],
        "precomputed_profile": bundle is None,
    }
    ledger.evidence_sources = bundle.sources if bundle else []
    ledger.deduplication_summary = {
        "records": bundle.record_count if bundle else 0,
        "unique": bundle.unique_count if bundle else 0,
        "duplicates_collapsed": bundle.duplicate_count if bundle else 0,
    }
    ledger.detected_terms = sorted(profile.get("evidence_terms", []))[:40]
    ledger.layer_scores = {
        name: round(coerce_float((profile.get(name) or {}).get("score")), 3)
        for name in (
            "consent_quality", "subscription_extraction", "claims_non_payment",
            "friction_tax", "regulatory_fragility", "narrative_experience_gap",
            "premium_promise_failure", "delay_revenue",
        )
        if isinstance(profile.get(name), dict)
    }
    if context.adjusted_layer_scores != {
        k: ledger.layer_scores.get(k, 0.0) for k in context.adjusted_layer_scores
    }:
        ledger.layer_scores.update(
            {
                f"{name}_after_refutation": round(value, 3)
                for name, value in context.adjusted_layer_scores.items()
                if abs(value - ledger.layer_scores.get(name, value)) > 1e-9
            }
        )
    reliability_score = context.reliability_factor * 10.0
    ledger.evidence_reliability_score = round(reliability_score, 3)
    ledger.reliability_band = _reliability_band(context)
    ledger.simulator_factors_added = {
        k: round(v, 4) for k, v in sorted(context.risk_factors.items())
    }
    if context.jurisdiction_map:
        ledger.jurisdiction_domains = {
            k: round(v, 3)
            for k, v in context.jurisdiction_map.domains.items()
            if v > 0
        }
        ledger.rationale.extend(context.jurisdiction_map.rationale[:2])
    if context.chain:
        ledger.dark_pattern_chain = {
            "score": round(context.chain.score, 3),
            "label": context.chain.label,
            "longest_consecutive_run": context.chain.longest_consecutive_run,
            "stages_present": context.chain.stages_present,
        }
    if context.anti_gaming:
        ledger.anti_gaming = {
            "refutations": {
                k: round(v, 3)
                for k, v in context.anti_gaming.refutations_by_category.items()
            },
            "resolution_relief": round(context.anti_gaming.resolution_relief, 3),
            "marketing_flagged": context.anti_gaming.marketing_flagged,
            "generic_praise_ignored": context.anti_gaming.generic_praise_ignored,
        }
        ledger.rationale.extend(context.anti_gaming.rationale[:2])

    # Multipliers per the bridge contract, with two fairness corrections:
    # (a) clean/mostly_clean revenue with no severe layer floors at 0.95 so
    #     clean evidence never meaningfully punishes a candidate,
    # (b) every multiplier's EFFECT is scaled by reliability — an
    #     unreliable severe finding is a warning, not a verdict.
    adjusted_rq = coerce_float(
        (profile.get("adjusted_revenue_quality") or {}).get("score")
    )
    consent_q = coerce_float((profile.get("consent_quality") or {}).get("score"))
    fragility = context.adjusted_layer_scores.get("regulatory_fragility", 0.0)

    rq_mult = clip(adjusted_rq / 10.0, 0.25, 1.05)
    consent_mult = clip(consent_q / 10.0, 0.35, 1.05)
    regulatory_mult = clip(1.0 - fragility / 10.0, 0.30, 1.00)

    severe, severe_reasons = _severe_risk(context)
    label = profile.get("revenue_quality_label", "")
    harm = _harm_evidenced(context)
    if not harm:
        # Zero harm-category evidence: positive/neutral evidence must not
        # punish a candidate just because structured consent inputs are
        # absent. Specific operational proof (refutations) earns full
        # neutrality; otherwise near-neutral with the conservatism noted.
        has_proof = bool(
            context.anti_gaming
            and context.anti_gaming.refutations_by_category
        )
        floor = 1.0 if has_proof else 0.97
        rq_mult = max(rq_mult, floor)
        consent_mult = max(consent_mult, floor)
        regulatory_mult = max(regulatory_mult, floor)
        ledger.rationale.append(
            "no harm-category evidence detected — "
            + (
                "specific operational proof present; multipliers neutral"
                if has_proof
                else "multipliers floored at 0.97 (ignorance is not harm)"
            )
        )
    elif not severe and label in ("clean", "mostly_clean"):
        rq_mult = max(rq_mult, 0.95)
        consent_mult = max(consent_mult, 0.95)
        regulatory_mult = max(regulatory_mult, 0.95)
        ledger.rationale.append(
            f"revenue quality '{label}' with no severe layer — clean "
            "evidence floors multipliers at 0.95 (no unfair penalty)"
        )

    factor = context.reliability_factor

    def _gate(mult: float) -> float:
        return 1.0 - (1.0 - mult) * factor

    effective = {
        "revenue_quality_multiplier": _gate(rq_mult),
        "consent_safety_multiplier": _gate(consent_mult),
        "regulatory_safety_multiplier": _gate(regulatory_mult),
    }
    ledger.multipliers_applied = {
        **{k: round(v, 4) for k, v in effective.items()},
        "reliability_factor": round(factor, 4),
    }

    friction = context.adjusted_layer_scores.get("friction_tax", 0.0)
    claims = context.adjusted_layer_scores.get("claims_non_payment", 0.0)
    gap = coerce_float(
        (profile.get("narrative_experience_gap") or {}).get("score")
    )
    penalties = {
        "friction_revenue_penalty": friction / 10.0 * 5.0 * factor,
        "claims_failure_penalty": claims / 10.0 * 6.0 * factor,
        "narrative_gap_penalty": gap / 10.0 * 4.0 * factor,
    }
    ledger.penalties_applied = {k: round(v, 4) for k, v in penalties.items()}

    score_after = clip(
        score_before
        * effective["revenue_quality_multiplier"]
        * effective["consent_safety_multiplier"]
        * effective["regulatory_safety_multiplier"]
        - sum(penalties.values()),
        0.0,
        100.0,
    )
    ledger.score_after_consent = round(score_after, 4)

    # Ladder cap: severe risk caps promotion by reliability band. The
    # driver-layer interrupt states outrank consent and pass through.
    state_after = state_before
    if state_before in ladder_states:
        # Score-driven demotion first: the adjusted score may no longer
        # support the original rung, but never demote below watchlist on
        # score alone (visibility is preserved; promotion is what's gated).
        if severe:
            band = ledger.reliability_band
            cap_state = _SEVERE_CAPS.get(band, "buy_candidate")
            cap_index = ladder_states.index(cap_state)
            if ladder_states.index(state_before) > cap_index:
                state_after = cap_state
                ledger.risk_caps_applied.append(
                    f"severe[{','.join(severe_reasons)}] × reliability["
                    f"{band}] caps state at {cap_state}"
                )
            if band == "low":
                ledger.warnings.append(
                    "severe risk indicated but evidence reliability is low — "
                    "mild cap only; gather corroboration before acting on this"
                )
    ledger.recommendation_after_consent = state_after

    if state_after != state_before or score_after < score_before - 1e-9:
        ledger.rationale.append(
            f"consent adjustment: score {score_before:.1f} -> "
            f"{score_after:.1f}; state {state_before} -> {state_after}"
        )
    else:
        ledger.rationale.append("consent adjustment: no material change")
    if severe:
        ledger.rationale.append(
            "severe consent/regulatory evidence present: "
            + ", ".join(severe_reasons)
        )

    return ledger
