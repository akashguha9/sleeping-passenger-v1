"""Ceiling / attribution / counterfactual layer — Fable 5 dual-score system.

The previous sprint made hype unable to *buy* a Buy: the multiplicative gates
cap a contaminated or perception-dependent signal no matter how loud it is.
But a single gated number cannot answer the three questions an operator
actually has:

  1. What is investable *now*?              -> investable_score (gated, strict)
  2. What could this *become*?              -> research_ceiling_score
  3. How hard did we suppress a false alarm? -> trap_suppression_score

This module adds all three, plus bottleneck attribution and deterministic
counterfactuals, WITHOUT weakening the spine:

  * The research ceiling improves only *evidence* levers (conversion arriving,
    fundamentals confirming, cross-platform migration). It NEVER relaxes the
    fraud gates (purity, contamination, blind result). So a bot-hype signal's
    ceiling stays pinned near zero even with every evidence lever maxed —
    surface metrics cannot inflate a trap into a Buy. The ceiling is itself
    fraud-gated. That is the eureka.

Score semantics fixed
---------------------
  legacy_baseline       — naive volume/social-proof model (the old hype-chaser)
  raw_merit             — additive narrative upside, pre-gate
  investable_score      — gated final (== gated_final), strict
  research_ceiling_score— best reachable gated final under achievable evidence
  upgrade_delta         = research_ceiling - legacy_baseline   (ceiling vs old)
  ceiling_delta         = research_ceiling - investable        (>= 0 headroom)
  risk_detection_delta  = legacy_baseline - investable         (>0 = trap caught)
  gate_haircut          = investable - raw_merit               (<=0 = risk removed)
"""
from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, Callable

from .util import clamp, r3
from .tokenizer import extract_tokens
from .opportunity import SignalDossier, score_opportunity, BUY, LONG_TERM_COMPOUNDER


# --------------------------------------------------------------------------
# A. Legacy baseline — reconstruct the naive pre-upgrade scalar model.
# --------------------------------------------------------------------------
def legacy_baseline_score(d: SignalDossier) -> dict[str, Any]:
    """Approximate the old additive/scalar model: it chases volume, social
    proof and crude positive sentiment, with NO fraud caps.  This is exactly
    the pathology the gated model corrects, so it (correctly) over-scores
    bot-hype and over-credits social proof on real signals.
    """
    raw = d.views + 10 * d.likes + 50 * d.saves
    volume = clamp(math.log10(1.0 + raw) / 6.0)
    social_proof = clamp(math.log10(1.0 + d.followers + 10 * d.likes) / 6.0)
    tok = extract_tokens(d.text)
    hype = tok.category_mass.get("hype", 0.0) + tok.category_mass.get("bot", 0.0)
    naive_sentiment = clamp(hype / 3.0)  # naive model thinks hype == good
    if d.reality_confirmation is not None:
        conf = clamp(d.reality_confirmation)
    else:
        conf = clamp(0.4 * d.business_confirmation + 0.6 * d.financial_confirmation)
    score = clamp(0.40 * volume + 0.35 * social_proof
                  + 0.15 * naive_sentiment + 0.10 * conf)
    return {
        "score": r3(score),
        "components": {
            "volume": r3(volume), "social_proof": r3(social_proof),
            "naive_sentiment": r3(naive_sentiment), "naive_confirmation": r3(conf),
        },
        "note": "naive volume/social-proof model; no fraud gates",
    }


# --------------------------------------------------------------------------
# B. Counterfactual levers.
#    achievable=True  -> legitimate future EVIDENCE; counts toward the ceiling.
#    achievable=False -> requires resolving FRAUD/recognition; diagnostic only.
# --------------------------------------------------------------------------
def _union_platforms(d: SignalDossier, extra: list[str]) -> list[str]:
    return list(dict.fromkeys([*d.platforms, *extra]))


def _max_conf(d: SignalDossier, floor: float) -> float | None:
    if d.reality_confirmation is None:
        return None
    return max(d.reality_confirmation, floor)


_Lever = tuple[str, bool, str, Callable[[SignalDossier], SignalDossier]]

LEVERS: list[_Lever] = [
    ("conversion_arrives", True,
     "convert trust into action (purchase/signup/adoption)",
     lambda d: replace(d, conversion_strength=max(d.conversion_strength, 0.8))),
    ("retention_arrives", True,
     "demonstrate repeat behavior / renewal",
     lambda d: replace(d, retention_strength=max(d.retention_strength, 0.8))),
    ("reproduction_arrives", True,
     "show referral / imitation / organic spread",
     lambda d: replace(d, reproduction_strength=max(d.reproduction_strength, 0.7))),
    ("fundamentals_confirm", True,
     "confirm in business + financial statements (rev/margin/FCF)",
     lambda d: replace(
         d, business_confirmation=max(d.business_confirmation, 0.8),
         financial_confirmation=max(d.financial_confirmation, 0.85),
         reality_confirmation=_max_conf(d, 0.8))),
    ("cross_platform_migration", True,
     "migrate to durable ecologies (Reddit + YouTube + LinkedIn)",
     lambda d: replace(d, platforms=_union_platforms(d, ["reddit", "youtube", "linkedin"]))),
    # --- diagnostic-only (not counted in the achievable ceiling) ----------
    ("if_engagement_authentic", False,
     "[diagnostic] resolve synthetic contamination / pass a blind cohort",
     lambda d: replace(
         d, comments=[], views=min(d.views, 5000.0), likes=min(d.likes, 200.0),
         saves=max(d.saves, 40.0), followers=min(d.followers, 8000.0),
         velocity=50.0, baseline_velocity=50.0, blind_score=None)),
    ("recognition_crowds", False,
     "[downside] what happens if you wait until the market crowds in",
     lambda d: replace(d, price_recognition=max(d.price_recognition, 0.85),
                       crowding=max(d.crowding, 0.8))),
]


def expand_ceiling(d: SignalDossier, base_report: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run every counterfactual lever and attribute the binding bottleneck."""
    base = base_report if base_report is not None else score_opportunity(d)
    current = base["segment_scores"]["final_opportunity"]

    lever_effects: list[dict[str, Any]] = []
    achievable_chain = d
    for name, achievable, confirmation, fn in LEVERS:
        rep = score_opportunity(fn(d))
        gain = r3(rep["segment_scores"]["final_opportunity"] - current)
        lever_effects.append({
            "lever": name, "achievable": achievable, "confirmation": confirmation,
            "final_if_applied": rep["segment_scores"]["final_opportunity"],
            "marginal_gain": gain,
            "decision_if_applied": rep["decision"],
        })
        if achievable:
            achievable_chain = fn(achievable_chain)

    # Research ceiling = all achievable evidence levers applied together,
    # with fraud gates held constant (the mutators never touch comments/blind).
    ceiling_rep = score_opportunity(achievable_chain)
    ceiling = ceiling_rep["segment_scores"]["final_opportunity"]

    # Binding bottleneck = the single achievable lever with the largest gain.
    achievable_effects = [e for e in lever_effects if e["achievable"]]
    achievable_effects.sort(key=lambda e: e["marginal_gain"], reverse=True)
    top = achievable_effects[0] if achievable_effects else None
    if top and top["marginal_gain"] >= 0.005:
        binding_bottleneck = top["lever"]
        next_required = top["confirmation"]
    else:
        binding_bottleneck = None  # gate-bound, not evidence-bound
        next_required = base["vitality"]["next_required_confirmation"]

    # Binding gate = the lowest multiplicative cap currently in force.
    gates = base["gates"]
    binding_gate = min(gates, key=lambda k: gates[k])

    return {
        "current_final": current,
        "research_ceiling": ceiling,
        "ceiling_decision": ceiling_rep["decision"],
        "ceiling_delta": r3(ceiling - current),
        "binding_bottleneck": binding_bottleneck,
        "binding_gate": binding_gate,
        "binding_gate_value": gates[binding_gate],
        "next_required_confirmation": next_required,
        "lever_effects": lever_effects,
        # fraud-resolution diagnostic, explicitly NOT part of the ceiling
        "fraud_resolved_diagnostic": next(
            (e["final_if_applied"] for e in lever_effects
             if e["lever"] == "if_engagement_authentic"), None),
        "decay_if_you_wait": next(
            (e["final_if_applied"] for e in lever_effects
             if e["lever"] == "recognition_crowds"), None),
    }


# --------------------------------------------------------------------------
# C. Full dual-score analysis — the operator-facing object.
# --------------------------------------------------------------------------
def analyze_signal(d: SignalDossier) -> dict[str, Any]:
    """Score a signal AND tell the operator what it could become, what is
    blocking it, and how hard a false positive was suppressed."""
    base = score_opportunity(d)
    legacy = legacy_baseline_score(d)
    ceil = expand_ceiling(d, base_report=base)

    raw_merit = base["segment_scores"]["raw_merit_additive"]
    investable = base["segment_scores"]["final_opportunity"]
    research_ceiling = ceil["research_ceiling"]

    upgrade_delta = r3(research_ceiling - legacy["score"])
    ceiling_delta = r3(research_ceiling - investable)
    risk_detection_delta = r3(legacy["score"] - investable)
    gate_haircut = r3(investable - raw_merit)
    trap_suppression_score = clamp(risk_detection_delta)

    reasons: list[str] = list(base["decision_reason_codes"])
    if ceiling_delta >= 0.1 and ceil["binding_bottleneck"]:
        reasons.append(f"HEADROOM_VIA:{ceil['binding_bottleneck']}")
    if trap_suppression_score >= 0.4 and investable <= 0.15:
        reasons.append("STRONG_TRAP_SUPPRESSION")
    if upgrade_delta > 0:
        reasons.append("CEILING_EXCEEDS_LEGACY")

    return {
        "signal_id": d.signal_id,
        "decision": base["decision"],
        # --- the three operator scores ---
        "investable_score": investable,
        "research_ceiling_score": research_ceiling,
        "trap_suppression_score": r3(trap_suppression_score),
        # --- supporting scores / deltas ---
        "legacy_baseline": legacy["score"],
        "raw_merit": raw_merit,
        "upgrade_delta": upgrade_delta,
        "ceiling_delta": ceiling_delta,
        "risk_detection_delta": risk_detection_delta,
        "gate_haircut": gate_haircut,
        # --- attribution ---
        "binding_bottleneck": ceil["binding_bottleneck"],
        "binding_gate": ceil["binding_gate"],
        "binding_gate_value": ceil["binding_gate_value"],
        "next_required_confirmation": ceil["next_required_confirmation"],
        "ceiling_decision": ceil["ceiling_decision"],
        "fraud_resolved_diagnostic": ceil["fraud_resolved_diagnostic"],
        "decay_if_you_wait": ceil["decay_if_you_wait"],
        "lever_effects": ceil["lever_effects"],
        "reason_codes": reasons,
        "score_semantics": {
            "legacy_baseline": "naive volume/social-proof model (no fraud gates)",
            "raw_merit": "additive narrative upside before gates",
            "investable_score": "gated fraud-resistant final (invest now)",
            "research_ceiling_score": "best reachable final if evidence arrives (fraud held)",
            "upgrade_delta": "research_ceiling - legacy_baseline (new ceiling vs old)",
            "ceiling_delta": "research_ceiling - investable (>=0 headroom)",
            "risk_detection_delta": "legacy_baseline - investable (>0 trap caught)",
            "gate_haircut": "investable - raw_merit (<=0 risk removed, NOT a failure)",
            "trap_suppression_score": "how strongly a false positive was suppressed",
        },
        "advisory_status": "ADVISORY_ONLY",
        "real_money_execution": "PROHIBITED",
    }


__all__ = ["legacy_baseline_score", "expand_ceiling", "analyze_signal", "LEVERS"]
