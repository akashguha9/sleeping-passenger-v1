"""Strategist layer — Fable 5 becomes a decision-calibrated operator.

The dual-score sprint answered *what is it worth / what could it become / is it
a trap*.  This layer answers the operator's real questions:

  * Should I act now, wait, collect a specific evidence, or walk away?
  * What exactly would KILL this thesis (not just improve it)?
  * Is the model CONFIDENT in its verdict, or fragile?
  * WHICH layer is driving the score up, and which is capping it?
  * How does TIMING (decay, crowding, transfer velocity) reshape the ceiling?

Five blocks, all deterministic, all reason-coded, all fraud-gated:

  1. timing_quality      — decay/crowding-adjusted ceilings, velocity, urgency
  2. expected_value      — EV(act now) vs EV(wait) + recommended_action
  3. kill_switches       — disconfirmation / thesis-break conditions
  4. confidence          — evidence coverage, module agreement, fragility
  5. attribution         — leave-one-factor-out drivers (Shapley-lite)

The spine is untouched: every score still flows from score_opportunity, whose
fraud gates remain multiplicative caps.  Nothing here can turn a contaminated
or blind-failing signal into a Buy — the gates pin it in every block.
"""
from __future__ import annotations

import statistics
from typing import Any

from .util import clamp, r3, mean
from .opportunity import SignalDossier, score_opportunity, MERIT_WEIGHTS
from .ceiling import analyze_signal, legacy_baseline_score, expand_ceiling

_GATE_NAMES = ("reality_purity", "authenticity", "transfer", "recognition")

# Human aliases so driver/kill-switch labels read like an operator wrote them.
_GATE_ALIAS = {
    "reality_purity": "reality_purity(blind)",
    "authenticity": "authenticity(synthetic_contamination)",
    "transfer": "funnel_transfer",
    "recognition": "market_recognition",
}
_MERIT_ALIAS = {
    "narrative_emergence": "platform_ecology",
    "semantic_density": "semantic_density",
    "vitality": "vitality(funnel_transfer)",
    "timing_edge": "timing_edge",
    "reality_confirmation": "reality_confirmation(fundamentals)",
    "mispricing": "mispricing(interpretation_gap)",
}


# --------------------------------------------------------------------------
# 1. Timing quality.
# --------------------------------------------------------------------------
def _timing_block(d: SignalDossier, base: dict[str, Any], research_ceiling: float) -> dict[str, Any]:
    timing = base["timing"]
    vit = base["vitality"]
    fresh = base["provenance_freshness"]
    ecos = base["ecologies"]
    half_life = max((e["half_life_days"] for e in ecos), default=30.0)

    age_hl = timing["age_half_lives"]
    transfer_integrity = vit["transfer_integrity"]
    reality_confirmation = base["segment_scores"]["mispricing"]  # placeholder; overwritten below
    reality_confirmation = base["merit_components"]["reality_confirmation"]

    decay_risk = clamp(1.0 - 0.5 ** age_hl)
    crowding_pressure = clamp(0.6 * d.price_recognition + 0.4 * d.crowding)
    crowding_risk = crowding_pressure

    # Velocity: stages cleared per unit of (relative) age — fast + young = high.
    transfer_velocity = clamp(transfer_integrity * (1.0 - clamp(age_hl / 2.0)))
    confirmation_proximity = clamp(0.5 * reality_confirmation + 0.5 * transfer_integrity)

    time_to_confirmation_days = round((1.0 - confirmation_proximity) * half_life_days_safe(half_life) * 0.5, 1)
    time_to_crowding_days = round((1.0 - crowding_pressure) * half_life, 1)

    decay_adjusted_ceiling = r3(clamp(research_ceiling * (1.0 - 0.5 * decay_risk)))
    crowding_adjusted_ceiling = r3(clamp(research_ceiling * (1.0 - 0.6 * crowding_risk)))

    ttc_norm = clamp(time_to_crowding_days / max(1.0, half_life))
    urgency_score = clamp(0.4 * (1.0 - ttc_norm) + 0.3 * transfer_velocity + 0.3 * crowding_risk)

    timing_edge_v2 = clamp(transfer_velocity * (0.5 + 0.5 * confirmation_proximity)
                           - 0.3 * decay_risk - 0.3 * crowding_risk)

    # Rich timing label.
    contaminated = (base["segment_scores"]["synthetic_contamination"] >= 0.5
                    or base["segment_scores"]["reality_purity"] < 0.4)
    state = timing["state"]
    if contaminated:
        label = "FAKE"
    elif state == "CROWDED_EXHAUSTED":
        label = "EXHAUSTED"
    elif state == "POST_HALF_LIFE_DECAY":
        label = "DECAYING"
    elif state == "MARKET_RECOGNITION" or crowding_pressure >= 0.7:
        label = "CONFIRMED_BUT_CROWDED" if reality_confirmation >= 0.45 else "CROWDED_BEFORE_CONFIRMATION"
    elif timing["within_transfer_window"]:
        if transfer_velocity >= 0.45 and base["merit_components"]["timing_edge"] >= 0.3:
            label = "EARLY_AND_ALIVE"
        elif transfer_velocity < 0.3:
            label = "EARLY_BUT_WEAK"
        else:
            label = "ACTIVE_TRANSFER_WINDOW"
    else:
        label = "EARLY_BUT_WEAK"

    reasons = [f"TIMING_QUALITY:{label}", f"URGENCY:{round(urgency_score,2)}"]
    if decay_risk >= 0.5:
        reasons.append("MATERIAL_DECAY_RISK")
    if crowding_risk >= 0.5:
        reasons.append("MATERIAL_CROWDING_RISK")

    return {
        "timing_quality_label": label,
        "transfer_velocity": r3(transfer_velocity),
        "confirmation_proximity": r3(confirmation_proximity),
        "time_to_confirmation_days": time_to_confirmation_days,
        "time_to_crowding_days": time_to_crowding_days,
        "decay_rate_per_half_life": r3(decay_risk),
        "decay_risk": r3(decay_risk),
        "crowding_risk": r3(crowding_risk),
        "decay_adjusted_ceiling": decay_adjusted_ceiling,
        "crowding_adjusted_ceiling": crowding_adjusted_ceiling,
        "urgency_score": r3(urgency_score),
        "timing_edge_v2": r3(timing_edge_v2),
        "reason_codes": reasons,
        "_half_life_days": half_life,
    }


def half_life_days_safe(x: float) -> float:
    return max(0.1, x)


# --------------------------------------------------------------------------
# 2. Expected value / ante.
# --------------------------------------------------------------------------
def _ev_block(d: SignalDossier, base: dict[str, Any], ceil: dict[str, Any],
              timing_block: dict[str, Any]) -> dict[str, Any]:
    ss = base["segment_scores"]
    investable = ss["final_opportunity"]
    research_ceiling = ceil["research_ceiling"]
    reality_confirmation = base["merit_components"]["reality_confirmation"]
    contamination = ss["synthetic_contamination"]
    reality_purity = ss["reality_purity"]
    authenticity = base["gates"]["authenticity"]
    transfer_integrity = base["vitality"]["transfer_integrity"]

    decay_risk = timing_block["decay_risk"]
    crowding_risk = timing_block["crowding_risk"]

    # Largest achievable evidence gain (the binding bottleneck's lift).
    achievable = [e for e in ceil["lever_effects"] if e["achievable"]]
    next_evidence_gain = max((e["marginal_gain"] for e in achievable), default=0.0)
    next_evidence_gain = max(0.0, next_evidence_gain)

    # P(evidence arrives): higher when the signal is already partly real.
    p_evidence = clamp(0.30 + 0.40 * reality_confirmation + 0.20 * authenticity
                       + 0.10 * transfer_integrity - 0.40 * contamination)
    p_evidence = clamp(p_evidence, 0.05, 0.90)

    # Ante: the cost/risk of committing capital NOW (low purity / low
    # confirmation / contamination all raise it).
    ante_cost = clamp(0.10 + 0.40 * (1.0 - reality_purity)
                      + 0.30 * (1.0 - reality_confirmation) + 0.20 * contamination)

    # EV of acting now: capture today's gated value, pay the ante.
    ev_act_now = r3(investable - ante_cost)

    # EV of waiting: chase the ceiling with probability p, eroded by decay +
    # crowding, minus a small cost for the chance evidence never comes.
    ev_wait = r3(p_evidence * research_ceiling * (1.0 - 0.5 * (decay_risk + crowding_risk))
                 - (1.0 - p_evidence) * 0.10)

    # Recommended action — fraud first, then timing, then EV comparison.
    reasons: list[str] = []
    if contamination >= 0.5:
        action = "AVOID_TRAP"
        reasons.append("SYNTHETIC_CONTAMINATION")
    elif reality_purity < 0.4:
        action = "REJECT_UNTIL_FRAUD_RESOLVED"
        reasons.append("FAILS_BLIND_VALIDATION")
    elif timing_block["timing_quality_label"] in ("EXHAUSTED", "DECAYING") and ev_wait <= 0:
        action = "EXIT_OR_IGNORE"
        reasons.append("EDGE_DECAYED")
    elif timing_block["timing_quality_label"] in ("CONFIRMED_BUT_CROWDED", "CROWDED_BEFORE_CONFIRMATION") and ev_wait <= 0:
        action = "EXIT_OR_IGNORE"
        reasons.append("CROWDED_NO_REMAINING_EDGE")
    elif ev_act_now > 0 and ev_act_now >= ev_wait and base["timing"]["within_transfer_window"]:
        action = "ACT_NOW"
        reasons.append("ACT_EV_DOMINATES")
    elif ev_wait > 0 and ev_wait > ev_act_now and next_evidence_gain >= 0.05:
        if ceil["binding_bottleneck"]:
            action = "COLLECT_SPECIFIC_EVIDENCE"
            reasons.append(f"COLLECT:{ceil['binding_bottleneck']}")
        else:
            action = "WAIT_FOR_CONFIRMATION"
            reasons.append("WAIT_GATE_BOUND")
    elif investable >= 0.2 or research_ceiling >= 0.4:
        action = "SHORTLIST_ONLY"
        reasons.append("WATCHLIST_NO_CLEAR_EDGE")
    else:
        action = "EXIT_OR_IGNORE"
        reasons.append("LOW_VALUE")

    return {
        "next_evidence_gain": r3(next_evidence_gain),
        "probability_evidence_arrives": r3(p_evidence),
        "ante_cost": r3(ante_cost),
        "decay_risk": r3(decay_risk),
        "crowding_risk": r3(crowding_risk),
        "expected_value_of_waiting": ev_wait,
        "expected_value_of_acting_now": ev_act_now,
        "recommended_action": action,
        "reason_codes": reasons,
    }


# --------------------------------------------------------------------------
# 3. Kill-switches / disconfirmation.
# --------------------------------------------------------------------------
_SEV_WEIGHT = {"LOW": 0.33, "MEDIUM": 0.66, "HIGH": 1.0, "CRITICAL": 1.2}


def _kill_switch_block(d: SignalDossier, base: dict[str, Any]) -> dict[str, Any]:
    ss = base["segment_scores"]
    mc = base["merit_components"]
    interp = base["interpretation"]
    distinct_roles = base["platform_ecology"].get("distinct_roles", 0)
    migration_clearance = clamp((distinct_roles - 1) / 3.0)
    crowding_pressure = clamp(0.6 * d.price_recognition + 0.4 * d.crowding)

    catalog = [
        ("synthetic_contamination_rises", "HIGH",
         "comment authenticity / engagement-to-conversion ratio / velocity",
         ss["synthetic_contamination"]),
        ("blind_score_stays_weak", "HIGH",
         "blind/double-blind cohort vs branded score (reality purity)",
         clamp(1.0 - ss["reality_purity"])),
        ("fundamentals_fail_after_maturation", "HIGH",
         "revenue / gross margin / FCF after the narrative matures",
         clamp(1.0 - mc["reality_confirmation"])),
        ("conversion_never_arrives", "MEDIUM",
         "purchase / signup / adoption conversion rate",
         clamp(1.0 - d.conversion_strength)),
        ("retention_stays_zero", "MEDIUM",
         "repeat purchase / renewal / cohort retention",
         clamp(1.0 - d.retention_strength)),
        ("market_crowds_before_confirmation", "MEDIUM",
         "price recognition + crowding vs confirmation",
         clamp(crowding_pressure - mc["reality_confirmation"])),
        ("signal_does_not_migrate", "MEDIUM",
         "appearance across distinct platform ecologies",
         clamp(1.0 - migration_clearance)),
        ("customer_ownership_fails", "MEDIUM",
         "off-platform / first-party / owned-audience share (sovereignty)",
         clamp(1.0 - ss["sovereignty"])),
        ("interpretation_gap_closes_wrong_way", "MEDIUM",
         "minority vs market interpretation drift",
         clamp(interp["interpretation_gap"] * (1.0 - mc["reality_confirmation"]))),
    ]

    scored = []
    for name, sev, monitor, risk in catalog:
        risk = clamp(risk)
        scored.append({
            "condition": name,
            "severity": sev,
            "monitoring_signal": monitor,
            "current_risk": r3(risk),
            "priority": r3(_SEV_WEIGHT[sev] * risk),
            "red_line": risk >= 0.7,
        })
    scored.sort(key=lambda k: k["priority"], reverse=True)
    top3 = scored[:3]

    return {
        "kill_switches": top3,
        "thesis_break_conditions": [k["condition"] for k in top3],
        "disconfirmation_tokens": [k["monitoring_signal"] for k in top3],
        "red_line_events": [k["condition"] for k in scored if k["red_line"]],
        "all_conditions": scored,
    }


def _negative_counterfactuals(d: SignalDossier, base: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic downside scenarios: what a thesis-break does to the score."""
    from dataclasses import replace
    current = base["segment_scores"]["final_opportunity"]
    scenarios = {
        "fundamentals_fail": replace(d, business_confirmation=0.0,
                                     financial_confirmation=0.0,
                                     reality_confirmation=0.0),
        "market_crowds": replace(d, price_recognition=max(d.price_recognition, 0.85),
                                 crowding=max(d.crowding, 0.8)),
        "retention_collapses": replace(d, retention_strength=0.0,
                                       reproduction_strength=0.0),
    }
    out = []
    for name, dd in scenarios.items():
        rep = score_opportunity(dd)
        f = rep["segment_scores"]["final_opportunity"]
        out.append({"scenario": name, "final_if_happens": f,
                    "score_drop": r3(current - f),
                    "decision_if_happens": rep["decision"]})
    return out


# --------------------------------------------------------------------------
# 4. Confidence / fragility.
# --------------------------------------------------------------------------
def _confidence_block(d: SignalDossier, base: dict[str, Any],
                      attribution: dict[str, Any]) -> dict[str, Any]:
    ss = base["segment_scores"]
    mc = base["merit_components"]
    investable = ss["final_opportunity"]
    contamination = ss["synthetic_contamination"]
    reality_purity = ss["reality_purity"]
    freshness = ss["provenance_freshness"]

    # Evidence coverage: how many evidence dimensions are actually present.
    flags = [
        len(d.comments) > 0,
        d.conversions > 0 or d.conversion_strength > 0,
        d.retention_strength > 0,
        d.business_confirmation > 0,
        d.financial_confirmation > 0,
        len(d.platforms) >= 2,
        len(d.beholder_adoption) > 0,
        d.views > 0,
    ]
    evidence_coverage = clamp(sum(1 for f in flags if f) / len(flags))

    # Module agreement: do the goodness signals point the same way?
    signals = [mc["vitality"], mc["timing_edge"], mc["reality_confirmation"],
               ss["semantic_density"], clamp(1.0 - contamination), reality_purity,
               ss["platform_ecology"]]
    spread = statistics.pstdev(signals) if len(signals) > 1 else 0.0
    module_agreement = clamp(1.0 - 1.8 * spread)

    # Score fragility: largest single-factor swing near the decision boundary.
    score_fragility = clamp(2.0 * attribution["max_single_factor_swing"])
    # Boundary proximity adds fragility (near 0.33 / 0.55 thresholds).
    for thr in (0.33, 0.55):
        if abs(investable - thr) <= 0.05:
            score_fragility = clamp(score_fragility + 0.15)

    contamination_uncertainty = clamp(0.30 * (1.0 - min(1.0, len(d.comments) / 5.0)))

    is_rejection = investable < 0.15
    # A trap verdict needs *observable fraud* (contamination / failed blind),
    # not merely absent fundamentals — otherwise a thin signal would masquerade
    # as a confident trap.
    has_fraud_evidence = contamination >= 0.4 or reality_purity < 0.45
    if is_rejection and has_fraud_evidence:
        verdict_strength = clamp(max(contamination, 1.0 - reality_purity))
        confidence_raw = clamp(0.6 * verdict_strength + 0.4 * module_agreement)
    elif is_rejection:
        # Rejection without fraud evidence — confidence needs real coverage.
        confidence_raw = clamp(evidence_coverage * module_agreement)
    else:
        confidence_raw = clamp(evidence_coverage * module_agreement
                               * (0.5 + 0.5 * freshness))
    confidence_score = clamp(confidence_raw - 0.4 * score_fragility
                             - 0.3 * contamination_uncertainty)

    # Label.
    fundamentals_missing = mc["reality_confirmation"] < 0.5
    if is_rejection and has_fraud_evidence and confidence_score >= 0.55:
        label = "HIGH_CONFIDENCE_TRAP"
    elif evidence_coverage < 0.35:
        label = "INSUFFICIENT_EVIDENCE"
    elif is_rejection:
        label = "INSUFFICIENT_EVIDENCE"
    elif confidence_score >= 0.6 and score_fragility < 0.4 and not fundamentals_missing:
        label = "HIGH_CONFIDENCE_OPPORTUNITY"
    elif investable >= 0.33 and (fundamentals_missing or score_fragility >= 0.4):
        label = "FRAGILE_OPPORTUNITY"
    else:
        label = "LOW_CONFIDENCE_WATCH"

    reasons = [f"CONFIDENCE:{label}", f"COVERAGE:{round(evidence_coverage,2)}",
               f"AGREEMENT:{round(module_agreement,2)}"]
    if score_fragility >= 0.4:
        reasons.append("FRAGILE_TO_SINGLE_FACTOR")
    if fundamentals_missing and not is_rejection:
        reasons.append("FRAGILE_FUNDAMENTALS_MISSING")

    return {
        "evidence_coverage": r3(evidence_coverage),
        "module_agreement": r3(module_agreement),
        "score_fragility": r3(score_fragility),
        "synthetic_contamination_uncertainty": r3(contamination_uncertainty),
        "confidence_score": r3(confidence_score),
        "confidence_label": label,
        "reason_codes": reasons,
    }


# --------------------------------------------------------------------------
# 5. Attribution — leave-one-factor-out (Shapley-lite).
# --------------------------------------------------------------------------
def _gate_product(gates: dict[str, float]) -> float:
    p = 1.0
    for g in _GATE_NAMES:
        p *= gates[g]
    return p


def _attribution_block(base: dict[str, Any], ceil: dict[str, Any],
                       research_ceiling: float) -> dict[str, Any]:
    gates = base["gates"]
    mc = base["merit_components"]
    raw_merit = base["segment_scores"]["raw_merit_additive"]
    investable = base["segment_scores"]["final_opportunity"]
    gate_prod = _gate_product(gates)
    ss = base["segment_scores"]

    # Merit components: exact after-gate additive contribution.
    pos: list[dict[str, Any]] = []
    swings: list[tuple[str, float]] = []
    for c, w in MERIT_WEIGHTS.items():
        contrib = r3(w * mc[c] * gate_prod)       # leave-one-out to 0 == this
        if contrib > 0.0:
            pos.append({"factor": _MERIT_ALIAS[c], "contribution": contrib,
                        "kind": "merit"})
        swings.append((_MERIT_ALIAS[c], contrib))

    # Durability factors lift the *ceiling* (owned, fresh, mispriced demand is
    # more defensible). Fraud-gated: research_ceiling is ~0 for fakes, so these
    # contribute ~0 there.
    durability_terms = {
        "sovereignty": 0.40 * ss["sovereignty"],
        "provenance_freshness": 0.35 * ss["provenance_freshness"],
        "interpretation_gap": 0.25 * min(1.0, ss["interpretation_gap"]),
    }
    durability_bonus = clamp(sum(durability_terms.values()))
    ceiling_drivers: list[dict[str, Any]] = []
    durability_pos: list[dict[str, Any]] = []
    for f, term in durability_terms.items():
        gain = r3(research_ceiling * 0.35 * term)
        if gain > 0.0:
            ceiling_drivers.append({"factor": f, "ceiling_contribution": gain,
                                    "kind": "durability"})
        if ss.get(f, 0.0) >= 0.55:
            durability_pos.append({"factor": f, "contribution": gain,
                                   "kind": "durability", "_value": ss.get(f, 0.0)})

    # Achievable evidence levers are the other ceiling drivers.
    for e in ceil["lever_effects"]:
        if e["achievable"] and e["marginal_gain"] > 0.0:
            ceiling_drivers.append({"factor": e["lever"],
                                    "ceiling_contribution": e["marginal_gain"],
                                    "kind": "evidence_lever"})
    ceiling_drivers.sort(key=lambda k: k["ceiling_contribution"], reverse=True)

    # Gate suppressions: how much each cap removes (leave-one-out to 1.0).
    neg: list[dict[str, Any]] = []
    trap_drivers: list[dict[str, Any]] = []
    for g in _GATE_NAMES:
        gv = gates[g]
        others = 1.0
        for h in _GATE_NAMES:
            if h != g:
                others *= gates[h]
        invest_if_neutral = raw_merit * others       # g set to 1.0
        suppression = r3(max(0.0, invest_if_neutral - investable))
        swings.append((_GATE_ALIAS[g], suppression))
        if suppression > 0.0:
            entry = {"factor": _GATE_ALIAS[g], "suppression": suppression, "kind": "gate"}
            neg.append(entry)
            trap_drivers.append(entry)

    # Missing-upside negatives (weak qualitative factors).
    if ss["sovereignty"] < 0.5:
        neg.append({"factor": "platform_dependence(weak_sovereignty)",
                    "suppression": r3(0.5 * (1.0 - ss["sovereignty"])), "kind": "weakness"})
    if mc["reality_confirmation"] < 0.4:
        neg.append({"factor": "missing_fundamentals",
                    "suppression": r3(0.5 * (1.0 - mc["reality_confirmation"])), "kind": "weakness"})
    if ss["provenance_freshness"] < 0.4:
        neg.append({"factor": "staleness", "suppression": r3(0.4 * (1.0 - ss["provenance_freshness"])),
                    "kind": "weakness"})

    # Blend merit + durability drivers; force-surface strongly-present
    # durability factors (e.g. high sovereignty / freshness / interpretation
    # gap) even when raw merit terms have larger absolute contributions, so the
    # *distinctive* reason a signal is special is never hidden.
    pos = pos + durability_pos
    pos.sort(key=lambda k: k["contribution"], reverse=True)
    top_pos = pos[:4]
    in_top = {p["factor"] for p in top_pos}
    forced = [p for p in durability_pos
              if p.get("_value", 0.0) >= 0.6 and p["factor"] not in in_top]
    pos = top_pos + forced
    for p in pos:
        p.pop("_value", None)

    neg.sort(key=lambda k: k["suppression"], reverse=True)
    trap_drivers.sort(key=lambda k: k["suppression"], reverse=True)

    swings.sort(key=lambda kv: kv[1], reverse=True)
    max_swing = swings[0][1] if swings else 0.0
    fragility_drivers = [{"factor": f, "swing": v} for f, v in swings[:3]]

    return {
        "top_positive_drivers": pos[:6],
        "top_negative_drivers": neg[:4],
        "top_ceiling_drivers": ceiling_drivers[:4],
        "top_trap_suppression_drivers": trap_drivers[:3],
        "top_fragility_drivers": fragility_drivers,
        "durability_bonus": r3(durability_bonus),
        "max_single_factor_swing": max_swing,
    }


# --------------------------------------------------------------------------
# Public orchestrator.
# --------------------------------------------------------------------------
def strategize_signal(d: SignalDossier) -> dict[str, Any]:
    """Full operator object: dual scores + timing + EV + kill-switches +
    confidence + attribution.  Deterministic, advisory-only, fraud-gated."""
    base = score_opportunity(d)
    analysis = analyze_signal(d)
    ceil = expand_ceiling(d, base_report=base)
    research_ceiling = analysis["research_ceiling_score"]

    timing_block = _timing_block(d, base, research_ceiling)
    ev = _ev_block(d, base, ceil, timing_block)
    kills = _kill_switch_block(d, base)
    attribution = _attribution_block(base, ceil, research_ceiling)
    confidence = _confidence_block(d, base, attribution)
    neg_cf = _negative_counterfactuals(d, base)

    durability_bonus = attribution["durability_bonus"]
    durability_adjusted_ceiling = r3(clamp(research_ceiling * (1.0 + 0.35 * durability_bonus)))

    out = dict(analysis)  # carry all dual-score fields forward
    out.update({
        # timing
        "timing_quality_label": timing_block["timing_quality_label"],
        "transfer_velocity": timing_block["transfer_velocity"],
        "time_to_confirmation_days": timing_block["time_to_confirmation_days"],
        "time_to_crowding_days": timing_block["time_to_crowding_days"],
        "decay_adjusted_ceiling": timing_block["decay_adjusted_ceiling"],
        "crowding_adjusted_ceiling": timing_block["crowding_adjusted_ceiling"],
        "durability_adjusted_ceiling": durability_adjusted_ceiling,
        "urgency_score": timing_block["urgency_score"],
        "timing": timing_block,
        # expected value
        "expected_value_of_waiting": ev["expected_value_of_waiting"],
        "expected_value_of_acting_now": ev["expected_value_of_acting_now"],
        "recommended_action": ev["recommended_action"],
        "next_evidence_gain": ev["next_evidence_gain"],
        "ante_cost": ev["ante_cost"],
        "expected_value": ev,
        # kill switches
        "kill_switches": kills["kill_switches"],
        "thesis_break_conditions": kills["thesis_break_conditions"],
        "disconfirmation_tokens": kills["disconfirmation_tokens"],
        "red_line_events": kills["red_line_events"],
        "negative_counterfactuals": neg_cf,
        # confidence
        "confidence_score": confidence["confidence_score"],
        "confidence_label": confidence["confidence_label"],
        "evidence_coverage": confidence["evidence_coverage"],
        "module_agreement": confidence["module_agreement"],
        "score_fragility": confidence["score_fragility"],
        "confidence": confidence,
        # attribution
        "top_positive_drivers": attribution["top_positive_drivers"],
        "top_negative_drivers": attribution["top_negative_drivers"],
        "top_ceiling_drivers": attribution["top_ceiling_drivers"],
        "top_trap_suppression_drivers": attribution["top_trap_suppression_drivers"],
        "top_fragility_drivers": attribution["top_fragility_drivers"],
        "attribution": attribution,
    })
    # Strategist-level reason codes layered on top.
    out["reason_codes"] = list(out.get("reason_codes", [])) + [
        f"ACTION:{ev['recommended_action']}",
        f"TIMING:{timing_block['timing_quality_label']}",
        f"CONFIDENCE:{confidence['confidence_label']}",
    ]
    return out


__all__ = ["strategize_signal"]
