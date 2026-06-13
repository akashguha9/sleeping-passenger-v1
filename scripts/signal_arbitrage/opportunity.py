"""Layer 10 — Final Opportunity Synthesis & Stock Decision.

This is where the upstream layers converge.  The eureka is the *shape* of the
synthesis, not the list of inputs:

    raw_merit (ADDITIVE)  = w . [narrative, semantic_density, vitality,
                                 timing_edge, reality_confirmation, mispricing]

    final (MULTIPLICATIVE) = raw_merit
                           x reality_purity          (blind-test cap)
                           x (1 - contamination)     (synthetic-liquidity cap)
                           x transfer_gate           (funnel-transfer cap)
                           x recognition_gate        (priced-in cap)

A naive model is fooled *additively*: enough surface metrics in one dimension
buy a high score.  This model is fooled only *multiplicatively*: the fraud-
relevant dimensions (does it survive blind?  is the engagement real?  did the
funnel actually transfer?  is it already priced in?) are CAPS, not terms.  A
zero in any cap collapses the score no matter how loud the surface is.

``score_opportunity`` returns a fully structured, explainable report.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .util import clamp, mean, r3, safe_ratio, weighted
from .platform_ecology import classify_platform, platform_ecology_score
from .tokenizer import extract_tokens
from .synthetic_liquidity import detect_synthetic_liquidity
from .blind_validation import validate_blind
from .binary_truth import build_truth_ledger
from .vitality_funnel import compute_vitality
from .timing import classify_timing
from .interpretation_gap import interpret_beholders
from .provenance import freshness_score

# Decision labels (the reflection's required output set).
BUY = "BUY"
WATCH = "WATCH"
AVOID = "AVOID"
SHORT_CANDIDATE = "SHORT_CANDIDATE"
TOO_LATE = "TOO_LATE"
EVENT_DRIVEN = "EVENT_DRIVEN"
LONG_TERM_COMPOUNDER = "LONG_TERM_COMPOUNDER"
NARRATIVE_TRAP = "NARRATIVE_TRAP"
NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"

MERIT_WEIGHTS = {
    "narrative_emergence": 0.15,
    "semantic_density": 0.15,
    "vitality": 0.25,
    "timing_edge": 0.15,
    "reality_confirmation": 0.15,
    "mispricing": 0.15,
}

# Token categories that represent real behavior (substance) vs popularity cue.
_SUBSTANCE = ("demand", "trust", "adoption", "pricing_power", "margin",
              "sovereignty", "friction", "churn")
_PERCEPTION = ("hype", "bot")


@dataclass(frozen=True)
class SignalDossier:
    """All inputs needed to score one signal.  Most fields are optional."""
    signal_id: str
    text: str = ""
    platforms: list[str] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)
    # Engagement shape
    views: float = 0.0
    likes: float = 0.0
    saves: float = 0.0
    conversions: float = 0.0
    followers: float = 0.0
    velocity: float = 0.0
    baseline_velocity: float = 0.0
    # Funnel evidence (0..1)
    conversion_strength: float = 0.0
    retention_strength: float = 0.0
    reproduction_strength: float = 0.0
    business_confirmation: float = 0.0
    financial_confirmation: float = 0.0
    reality_confirmation: float | None = None   # override; else derived
    # Market / timing
    age_days: float = 0.0
    price_recognition: float = 0.0
    crowding: float = 0.0
    beholder_adoption: list[str] = field(default_factory=list)
    # Optional explicit double/triple-blind cohort result
    blind_score: float | None = None


def _attention_proxy(d: SignalDossier) -> float:
    raw = d.views + 10 * d.likes + 50 * d.saves + 100 * d.conversions
    return clamp(math.log10(1.0 + raw) / 6.0)


def score_opportunity(d: SignalDossier) -> dict[str, Any]:
    """Run the full upstream->downstream pipeline and return a decision."""
    # --- Layer 1: platform ecology ----------------------------------------
    ecologies = [classify_platform(p) for p in d.platforms]
    eco = platform_ecology_score(ecologies)
    distinct_roles = eco.get("distinct_roles", 0)
    mean_sovereignty = mean([e.sovereignty for e in ecologies]) if ecologies else 0.0
    # A signal lives as long as its most durable home: a narrative that has
    # reached YouTube/LinkedIn outlasts one that only lived on TikTok. Use the
    # most-durable reached ecology for overall decay; the fastest ecology is
    # surfaced separately as a fragility reason in platform_ecology_score.
    half_life = max((e.half_life_days for e in ecologies), default=30.0)

    # --- Layer 2: tokenization --------------------------------------------
    tok = extract_tokens(d.text, extra_texts=d.comments)
    cmass = tok.category_mass
    comment_tok = extract_tokens(" ".join(d.comments)) if d.comments else None
    comment_density = comment_tok.semantic_density if comment_tok else None

    substance_mass = sum(cmass.get(c, 0.0) for c in _SUBSTANCE)
    hype_mass = cmass.get("hype", 0.0)
    bot_mass = cmass.get("bot", 0.0)
    sovereignty_mass = cmass.get("sovereignty", 0.0)

    # --- Layer 3: synthetic liquidity -------------------------------------
    cont = detect_synthetic_liquidity(
        comments=d.comments, views=d.views, likes=d.likes, saves=d.saves,
        conversions=d.conversions, followers=d.followers, velocity=d.velocity,
        baseline_velocity=d.baseline_velocity, comment_semantic_density=comment_density,
    )

    # --- reality confirmation (derive if not overridden) ------------------
    if d.reality_confirmation is not None:
        reality_confirmation = clamp(d.reality_confirmation)
    else:
        reality_confirmation = clamp(0.4 * d.business_confirmation
                                     + 0.6 * d.financial_confirmation)

    # --- Layer 8: interpretation (needed for migration/gap) ---------------
    interp = interpret_beholders(cmass, beholder_adoption=d.beholder_adoption)

    # --- Layer 6: vitality funnel -----------------------------------------
    attention = _attention_proxy(d)
    trust_proxy = clamp(0.5 * clamp(cmass.get("trust", 0.0) / 3.0)
                        + 0.5 * clamp(safe_ratio(d.saves, d.likes + 1.0) * 5.0))
    stage_scores = {
        "narrative_birth": clamp(max(0.3, mean([e.confidence for e in ecologies]) if ecologies else 0.3)),
        "platform_attention": attention,
        "semantic_density": tok.semantic_density,
        "cross_platform_migration": clamp((distinct_roles - 1) / 3.0),
        "trust_formation": trust_proxy,
        "conversion": clamp(d.conversion_strength),
        "retention": clamp(d.retention_strength),
        "reproduction": clamp(d.reproduction_strength),
        "business_confirmation": clamp(d.business_confirmation),
        "financial_confirmation": clamp(d.financial_confirmation),
        "market_recognition": clamp(d.price_recognition),
    }
    vit = compute_vitality(stage_scores)

    # --- Layer 7: timing --------------------------------------------------
    strength = clamp(0.5 * tok.semantic_density + 0.5 * attention)
    timing = classify_timing(
        strength=strength, age_days=d.age_days, half_life_days=half_life,
        reality_confirmation=reality_confirmation,
        price_recognition=d.price_recognition, crowding=d.crowding,
    )

    # --- Layer 4: blind validation (the purity cap) -----------------------
    mispricing = clamp(interp.interpretation_gap * reality_confirmation)
    merit_components = {
        "narrative_emergence": eco["score"],
        "semantic_density": tok.semantic_density,
        "vitality": vit.vitality_score,
        "timing_edge": timing.timing_edge_score,
        "reality_confirmation": reality_confirmation,
        "mispricing": mispricing,
    }
    raw_merit = clamp(weighted(merit_components, MERIT_WEIGHTS))

    # Reality purity compares the blind reading to what the *crowd* sees — the
    # perception-driven surface score (attention + hype), not merit. A signal
    # whose surface is inflated by views/hype far above its blind substance is
    # fragile even if its merit already discounted the hype.
    surface_score = clamp(0.5 * attention + 0.5 * clamp((hype_mass + bot_mass) / 3.0))
    visible_for_blind = max(raw_merit, surface_score)
    blind = validate_blind(
        visible_score=visible_for_blind, blind_score=d.blind_score,
        hype_mass=hype_mass, bot_mass=bot_mass, contamination=cont.contamination,
        substance_mass=substance_mass,
    )

    # --- Layer 9: provenance freshness ------------------------------------
    fresh = freshness_score(
        age_days=d.age_days, half_life_days=half_life,
        interpretation_migration=interp.interpretation_migration,
        price_recognition=d.price_recognition, crowding=d.crowding,
    )

    sovereignty_score = clamp(0.7 * mean_sovereignty + 0.3 * clamp(sovereignty_mass / 2.0))

    # --- THE MULTIPLICATIVE GATES (eureka) --------------------------------
    gate_purity = blind.reality_purity
    gate_auth = clamp(1.0 - cont.contamination)
    gate_transfer = clamp(0.25 + 0.75 * vit.transfer_integrity)
    gate_recognition = clamp(1.0 - 0.8 * d.price_recognition)
    final = clamp(raw_merit * gate_purity * gate_auth * gate_transfer * gate_recognition)

    # --- Layer 5: binary truth ledger -------------------------------------
    evidence = {
        "authenticity": cont.authenticity,
        "semantic_density": tok.semantic_density,
        "distinct_roles": distinct_roles,
        "conversion_strength": d.conversion_strength,
        "retention_strength": d.retention_strength,
        "contamination": cont.contamination,
        "reality_purity": blind.reality_purity,
        "sovereignty": sovereignty_score,
        "reality_confirmation": reality_confirmation,
        "price_recognition": d.price_recognition,
        "interpretation_gap": interp.interpretation_gap,
        "within_transfer_window": timing.within_transfer_window,
    }
    truth = build_truth_ledger(evidence)

    decision, decision_reasons = _decide(
        final=final, contamination=cont.contamination,
        reality_purity=blind.reality_purity,
        interpretation_gap=interp.interpretation_gap,
        reality_confirmation=reality_confirmation, timing_state=timing.state,
        within_window=timing.within_transfer_window, freshness=fresh["score"],
        price_recognition=d.price_recognition, sovereignty=sovereignty_score,
        dominant_dir=interp.dominant.direction, minority_dir=interp.minority.direction,
        policy_mass=cmass.get("policy", 0.0),
    )

    segment_scores = {
        "platform_ecology": eco["score"],
        "semantic_density": r3(tok.semantic_density),
        "synthetic_contamination": r3(cont.contamination),
        "reality_purity": r3(blind.reality_purity),
        "binary_truth": r3(truth.truth_state),
        "vitality": r3(vit.vitality_score),
        "timing_edge": r3(timing.timing_edge_score),
        "interpretation_gap": r3(interp.interpretation_gap),
        "provenance_freshness": r3(fresh["score"]),
        "sovereignty": r3(sovereignty_score),
        "mispricing": r3(mispricing),
        "raw_merit_additive": r3(raw_merit),
        "final_opportunity": r3(final),
        "final_opportunity_100": round(final * 100, 1),
    }

    return {
        "signal_id": d.signal_id,
        "decision": decision,
        "decision_reason_codes": decision_reasons,
        "segment_scores": segment_scores,
        "gates": {
            "reality_purity": r3(gate_purity),
            "authenticity": r3(gate_auth),
            "transfer": r3(gate_transfer),
            "recognition": r3(gate_recognition),
        },
        "binary_genome": truth.genome,
        "binary_truth": truth.to_dict(),
        "platform_ecology": eco,
        "ecologies": [e.to_dict() for e in ecologies],
        "tokenization": tok.to_dict(),
        "synthetic_liquidity": cont.to_dict(),
        "blind_validation": blind.to_dict(),
        "vitality": vit.to_dict(),
        "timing": timing.to_dict(),
        "interpretation": interp.to_dict(),
        "provenance_freshness": fresh,
        "merit_components": {k: r3(v) for k, v in merit_components.items()},
        "advisory_status": "ADVISORY_ONLY",
        "real_money_execution": "PROHIBITED",
        "broker_api_called": False,
    }


def _decide(
    *,
    final: float, contamination: float, reality_purity: float,
    interpretation_gap: float, reality_confirmation: float, timing_state: str,
    within_window: bool, freshness: float, price_recognition: float,
    sovereignty: float, dominant_dir: str, minority_dir: str, policy_mass: float,
) -> tuple[str, list[str]]:
    """Route segmented scores to a decision label with reason codes."""
    r: list[str] = []

    # 1. Fraud / fragility gate — perception-dependent or contaminated.
    if contamination >= 0.5 or reality_purity < 0.4:
        if interpretation_gap >= 0.4 and reality_confirmation < 0.3:
            r.append("HYPE_GAP_NO_CONFIRMATION")
            return NARRATIVE_TRAP, r
        r.append("CONTAMINATED_OR_PERCEPTION_DEPENDENT")
        return AVOID, r

    # 2. Bearish setup — market bullish, reality absent.
    if (dominant_dir == "BULLISH" and minority_dir == "BEARISH"
            and reality_confirmation < 0.3 and final < 0.4):
        r.append("MARKET_BULLISH_REALITY_ABSENT")
        return SHORT_CANDIDATE, r

    # 3. Too late — recognized / crowded / decayed.
    if timing_state in ("MARKET_RECOGNITION", "CROWDED_EXHAUSTED",
                        "POST_HALF_LIFE_DECAY") or price_recognition >= 0.7:
        r.append(f"TIMING:{timing_state}")
        return TOO_LATE, r

    # 4. Event-driven — heavy policy/regulatory token mass.
    if policy_mass >= 1.5 and within_window:
        r.append("POLICY_EVENT_DRIVEN")
        return EVENT_DRIVEN, r

    # 5. Positive zone.
    if final >= 0.55:
        if reality_confirmation >= 0.5 and within_window and freshness >= 0.4:
            if sovereignty >= 0.6 and reality_confirmation >= 0.6 and interpretation_gap < 0.35:
                r.append("DURABLE_OWNED_DEMAND_CONFIRMED")
                return LONG_TERM_COMPOUNDER, r
            if interpretation_gap >= 0.3:
                r.append("GAP_PLUS_CONFIRMATION_IN_WINDOW")
                return BUY, r
            r.append("CONFIRMED_IN_WINDOW")
            return BUY, r
        if within_window and freshness >= 0.4:
            r.append("STRONG_BUT_AWAITING_CONFIRMATION")
            return WATCH, r
        r.append("STRONG_OUT_OF_WINDOW")
        return NEEDS_CONFIRMATION, r

    if final >= 0.33:
        if within_window and interpretation_gap >= 0.3 and freshness >= 0.4:
            r.append("EARLY_GAP_IN_WINDOW")
            return WATCH, r
        r.append("MODERATE_INCONCLUSIVE")
        return NEEDS_CONFIRMATION, r

    r.append("LOW_MERIT")
    return AVOID, r


__all__ = [
    "SignalDossier", "score_opportunity", "MERIT_WEIGHTS",
    "BUY", "WATCH", "AVOID", "SHORT_CANDIDATE", "TOO_LATE", "EVENT_DRIVEN",
    "LONG_TERM_COMPOUNDER", "NARRATIVE_TRAP", "NEEDS_CONFIRMATION",
]
