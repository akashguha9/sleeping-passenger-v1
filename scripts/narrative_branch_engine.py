"""Narrative Branch Engine (NBI) — claim -> layer -> branch -> exposure pipeline.

Consolidation facade in the chicken-gate tradition: wires the existing
scattered narrative intelligence into ONE coherent demote-only scoring path
so the system stops treating events as binary on/off headlines.

    Claim -> Source Cluster -> Narrative Layer -> Rumor / Causal-Leap Score
          -> Event Branch Probabilities -> Surviving Narrative Layer
          -> Value-Chain Exposure Rotation -> Price-Dislocation Validation
          -> Demote-Only Gates -> Advisory Event Card -> Operator

Existing layers wired in (reuse, not duplication):

* ``narrative_drift_monitor``       — NDM epistemic drift over the claim corpus
  (is this event being scored on narrative or on evidence?)
* ``consensus_formation_detector``  — CS/CFD state as amplification context
* ``hedge_ratio_engine``            — hedge-ratio classification for the
  rotate-basket suggestion
* ``advisory_contract``             — the one true safety stamp
* ``chicken_gate``                  — demote-only min() composition overlay
  (:func:`integrate_with_chicken_gate`) so NBI can only lower, never raise,
  an existing gate decision.

The Guwahati -> Delhi doctrine encoded here:

1.  A narrative is DEAD only when the CORE branch collapses.  A collapsed
    venue/sub-branch with a surviving core is TRANSFORMED -> ROTATE, not FOLD.
2.  ``Truth(Event) != Truth(CausalClaim)``: a verified micro-event (traffic
    jam) never confirms the attached macro claim (visit cancelled).  The best
    rumors are built on a true kernel — that makes RumorRisk HIGHER, not lower.
3.  Social media contributes velocity, never truth: SOCIAL/LLM claims are
    excluded from branch-probability updates and feed only RumorRisk.
4.  Source repetition is not independence: branch updates take the single
    best claim per source *cluster*, so N articles from one root source move
    a branch exactly as much as one article.
5.  Hard invariant: every sub-branch probability <= P(core_event).
6.  Fail closed: claims without evidence refs are UNVERIFIED and excluded
    from truth scoring; exposures without verified refs score 0; exposures
    without price/volume validation are capped WATCH_ONLY, never actionable.

Demote-only by construction: every multiplier is clamped to [0, 1], so
FINAL_TICKER_SCORE <= VALIDATED_RELEVANCE <= BASE_RELEVANCE, and rumor
claims can only lower a score or raise a watch flag (DISLOCATION_WATCH),
never upgrade anything.

Advisory-only.  No broker calls, no order surface, no execution language,
no real-money sizing.  A human makes every final decision.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from typing import Any

from scripts.advisory_contract import advisory_safety_stamps, human_only_stamp
from scripts.consensus_formation_detector import classify_cfd_state, compute_cs
from scripts.hedge_ratio_engine import classify_hedge_ratio
from scripts.narrative_drift_monitor import (
    NDMEntry,
    classify_ndm_state,
    compute_ndm_drift,
)

NBI_PROFILE_VERSION = "nbi-v1.1"

# ---------------------------------------------------------------------------
# Vocabulary — deterministic enums, no free-text categories
# ---------------------------------------------------------------------------

NARRATIVE_LAYERS: tuple[str, ...] = (
    "CORE_FACT", "TRIGGER", "RUMOR", "AMPLIFICATION", "CONTRADICTION",
    "CORRECTION", "OFFICIAL_RESOLUTION", "PARTIAL_RESOLUTION",
    "NARRATIVE_DEATH", "NARRATIVE_SURVIVAL",
)

SOURCE_CLASSES: tuple[str, ...] = (
    "OFFICIAL_GOVERNMENT", "EXCHANGE_FILING", "COMPANY_FILING",
    "PREDICTION_MARKET", "CREDIBLE_MEDIA", "LOCAL_MEDIA",
    "SOCIAL_MEDIA", "LLM_SUMMARY",
)

# Authority prior per source class (0-1).  Official > filing > market >
# media > social.  Social/LLM never carry truth (see TRUTH_BEARING_CLASSES).
SOURCE_CLASS_AUTHORITY: dict[str, float] = {
    "OFFICIAL_GOVERNMENT": 1.00,
    "EXCHANGE_FILING": 0.95,
    "COMPANY_FILING": 0.90,
    "PREDICTION_MARKET": 0.70,
    "CREDIBLE_MEDIA": 0.55,
    "LOCAL_MEDIA": 0.35,
    "SOCIAL_MEDIA": 0.10,
    "LLM_SUMMARY": 0.15,
}

# Per-class log-likelihood-ratio budget for branch updates.  A single claim
# contributes  sign * CLASS_LLR * quality_weight * strength  to the branch
# log-odds; classes absent here (SOCIAL/LLM) contribute exactly zero.
TRUTH_BEARING_CLASSES: frozenset[str] = frozenset({
    "OFFICIAL_GOVERNMENT", "EXCHANGE_FILING", "COMPANY_FILING",
    "PREDICTION_MARKET", "CREDIBLE_MEDIA", "LOCAL_MEDIA",
})
CLASS_LLR: dict[str, float] = {
    "OFFICIAL_GOVERNMENT": 3.0,
    "EXCHANGE_FILING": 2.2,
    "COMPANY_FILING": 2.0,
    "PREDICTION_MARKET": 1.5,
    "CREDIBLE_MEDIA": 0.8,
    "LOCAL_MEDIA": 0.4,
}

BRANCHES: tuple[str, ...] = (
    "core_event", "venue_specific", "delegation_intact",
    "deals_or_mous", "sector_impact", "already_priced_in",
)
# Sub-branches structurally bounded by the core event: no venue, delegation,
# or deal can be more likely than the event itself.
CORE_BOUNDED_BRANCHES: tuple[str, ...] = (
    "venue_specific", "delegation_intact", "deals_or_mous", "sector_impact",
)

EVENT_STATES: tuple[str, ...] = (
    "EMERGING", "ACTIVE", "RUMOR_CONTESTED", "TRANSFORMED",
    "PARTIAL_RESOLUTION", "RESOLVED", "DEAD", "WATCH_ONLY",
)

ACTION_ACT = "ACT"
ACTION_ROTATE = "ROTATE"
ACTION_WATCH = "WATCH"
ACTION_FOLD = "FOLD"
ACTION_NO_EXPOSURE = "NO_ACTIONABLE_EXPOSURE"
ACTIONS: tuple[str, ...] = (
    ACTION_ACT, ACTION_ROTATE, ACTION_WATCH, ACTION_FOLD, ACTION_NO_EXPOSURE,
)

# Catalyst channels and the branch that governs each (symbolic vs substantive
# split).  A venue collapse zeroes SYMBOLIC_LOCAL / VENUE_SPECIFIC exposure
# while BROAD_THEMATIC / SUBSTANTIVE_ECONOMIC ride the core branch.
CATALYST_CHANNELS: tuple[str, ...] = (
    "SYMBOLIC_LOCAL", "VENUE_SPECIFIC", "BROAD_THEMATIC",
    "SUBSTANTIVE_ECONOMIC", "DIRECT_COMPANY", "INDIRECT_VALUE_CHAIN",
)
CHANNEL_GOVERNING_BRANCH: dict[str, str] = {
    "SYMBOLIC_LOCAL": "venue_specific",
    "VENUE_SPECIFIC": "venue_specific",
    "BROAD_THEMATIC": "core_event",
    "SUBSTANTIVE_ECONOMIC": "core_event",
    "DIRECT_COMPANY": "deals_or_mous",
    "INDIRECT_VALUE_CHAIN": "sector_impact",
}

VERIFIED = "VERIFIED"
UNVERIFIED = "UNVERIFIED"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

DIRECTION_SUPPORTS = "SUPPORTS"
DIRECTION_REFUTES = "REFUTES"
DIRECTION_NEUTRAL = "NEUTRAL"

# Thresholds (heuristic until N_closed backtest cases >= 30; see
# BACKTEST_CASE_FIELDS below — the calibration seed schema ships with this
# module precisely so these constants can eventually be fitted).
BRANCH_COLLAPSE_THRESHOLD = 0.35
BRANCH_SURVIVE_THRESHOLD = 0.50
CORE_DEAD_THRESHOLD = 0.20
CORE_STRONG_THRESHOLD = 0.60
RUMOR_CAP_THRESHOLD = 7.0
DISLOCATION_WATCH_THRESHOLD = 0.10
DISLOCATION_RUMOR_MIN = 4.0
ACT_MIN_SCORE = 6.5
EMERGING_MIN_VERIFIED_CLAIMS = 3
PRIOR_DEFAULT = 0.5
PRIOR_CLAMP_LO, PRIOR_CLAMP_HI = 0.02, 0.98
RECENCY_HALF_LIFE_HOURS = 72.0
RECENCY_MISSING = 0.70          # unknown claim age -> haircut, never fresh
ACCURACY_MISSING = 0.50         # unknown source track record -> half trust
PROXIMITY_IN_JURISDICTION = 1.0
PROXIMITY_OUT_OF_JURISDICTION = 0.50
PROXIMITY_MISSING = 0.40        # unknown jurisdiction -> worse than known-far
FILING_UNCONFIRMED_MULTIPLIER = 0.60
LIQUIDITY_UNKNOWN_MULTIPLIER = 0.50
STALENESS_LAMBDA_PER_DAY = 0.10
STALENESS_MISSING_MULTIPLIER = 0.85
AMPLIFICATION_SATURATION_MPH = 30.0
# v1.1: event-level confidence decay while official confirmation is absent.
CONFIDENCE_DECAY_LAMBDA_PER_DAY = 0.05
CONFIDENCE_DECAY_MISSING = 0.85     # no official signal at all -> haircut
# v1.1: capped price-dislocation bonus.  The bonus can never push a score
# above validated merit (min() guard in score_exposure keeps FINAL <= VALIDATED).
PRICE_BONUS_KAPPA = 0.5
PRICE_BONUS_CAP = 1.25
# v1.1: ACT gate per spec — OAS >= 7.5 AND rumor risk < 5 AND price-valid.
ACT_MIN_OAS = 7.5
ACT_MAX_RUMOR = 5.0

EMOTIONAL_PACKAGING_WORDS: tuple[str, ...] = (
    "breaking", "shocking", "chaos", "panic", "urgent", "crisis", "disaster",
    "explosive", "bombshell", "unbelievable", "huge", "massive", "insane",
    "must see", "must watch", "share this", "!!",
)


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


def _num(value: Any, default: float | None = None) -> float | None:
    if value is None or isinstance(value, bool):
        return default
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default
    if x != x or x in (float("inf"), float("-inf")):
        return default
    return x


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _logit(p: float) -> float:
    p = _clamp(p, 1e-6, 1.0 - 1e-6)
    return math.log(p / (1.0 - p))


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def cosine_drift(v_old: list[float] | None, v_new: list[float] | None) -> float | None:
    """NarrativeDrift = 1 - cos(V_old, V_new).  None when not computable."""
    if not v_old or not v_new or len(v_old) != len(v_new):
        return None
    dot = sum(a * b for a, b in zip(v_old, v_new))
    na = math.sqrt(sum(a * a for a in v_old))
    nb = math.sqrt(sum(b * b for b in v_new))
    if na <= 0 or nb <= 0:
        return None
    return round(_clamp(1.0 - dot / (na * nb), 0.0, 2.0), 4)


# ---------------------------------------------------------------------------
# Claim normalization — cite-or-drop provenance
# ---------------------------------------------------------------------------


def normalize_claim(raw: Any, index: int = 0) -> dict[str, Any]:
    """Validate one claim dict into the canonical NBI claim record.

    Fail-closed rules:
    * no non-empty ``evidence_refs``  -> verification = UNVERIFIED
    * unknown ``layer``               -> UNVERIFIED (never guessed)
    * unknown ``source_class``        -> UNVERIFIED
    * missing ``source_cluster``      -> the shared "UNATTRIBUTED" bucket, so
      unattributed repetition can never manufacture independence.
    UNVERIFIED claims are excluded from branch updates and narrative
    confidence; they still count toward rumor velocity (velocity is a risk
    input, not a truth input).
    """
    data = raw if isinstance(raw, dict) else {}
    notes: list[str] = []

    layer = _text(data.get("layer")).upper()
    if layer not in NARRATIVE_LAYERS:
        notes.append(f"unknown layer {layer or '<missing>'!r}")
        layer = "RUMOR" if not layer else layer  # kept for audit, not trusted

    source_class = _text(data.get("source_class")).upper()
    if source_class not in SOURCE_CLASSES:
        notes.append(f"unknown source_class {source_class or '<missing>'!r}")
        source_class = "SOCIAL_MEDIA"  # least-trust bucket, never upgraded

    refs_raw = data.get("evidence_refs")
    refs = [
        _text(r) for r in (refs_raw if isinstance(refs_raw, list) else [])
        if _text(r)
    ]

    cluster = _text(data.get("source_cluster")) or _text(data.get("source_id"))
    if not cluster:
        cluster = "UNATTRIBUTED"
        notes.append("missing source_cluster -> shared UNATTRIBUTED bucket")

    direction = _text(data.get("direction")).upper() or DIRECTION_SUPPORTS
    if direction not in (DIRECTION_SUPPORTS, DIRECTION_REFUTES, DIRECTION_NEUTRAL):
        notes.append(f"unknown direction {direction!r} -> NEUTRAL")
        direction = DIRECTION_NEUTRAL

    branch = _text(data.get("branch")).lower()
    if branch not in BRANCHES:
        if branch:
            notes.append(f"unknown branch {branch!r} -> no branch impact")
        branch = ""

    verification = VERIFIED
    reasons: list[str] = []
    if not refs:
        reasons.append("no evidence_refs")
    if _text(data.get("layer")).upper() not in NARRATIVE_LAYERS:
        reasons.append("unknown layer")
    if _text(data.get("source_class")).upper() not in SOURCE_CLASSES:
        reasons.append("unknown source_class")
    if reasons:
        verification = UNVERIFIED
        notes.append("UNVERIFIED: " + "; ".join(reasons))

    return {
        "claim_id": _text(data.get("claim_id")) or f"claim_{index}",
        "event_id": _text(data.get("event_id")),
        "claim_text": _text(data.get("claim_text")),
        "source_cluster": cluster,
        "source_class": source_class,
        "jurisdiction": _text(data.get("jurisdiction")).upper(),
        "layer": layer,
        "timestamp": _text(data.get("timestamp")) or None,
        "age_hours": _num(data.get("age_hours")),
        "direction": direction,
        "branch": branch,
        "strength": _clamp(
            0.5 if (s := _num(data.get("strength"))) is None else s, 0.0, 1.0
        ),
        "claim_magnitude": _clamp(_num(data.get("claim_magnitude"), 0.0), 0.0, 10.0),
        "evidence_strength": _clamp(_num(data.get("evidence_strength"), 0.0), 0.0, 10.0),
        "historical_accuracy": _num(data.get("historical_accuracy")),
        "mentions_per_hour": _num(data.get("mentions_per_hour")),
        "evidence_refs": refs,
        "verification": verification,
        "notes": notes,
    }


def normalize_claims(raws: Any) -> list[dict[str, Any]]:
    items = raws if isinstance(raws, list) else []
    return [normalize_claim(c, i) for i, c in enumerate(items)]


# ---------------------------------------------------------------------------
# Source quality + cluster weighting
# ---------------------------------------------------------------------------


def source_quality_score(
    claim: dict[str, Any], decision_jurisdictions: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """SourceQualityScore (0-10) = 10 * gm(Authority, Accuracy, Proximity, Recency).

    Geometric mean is the normalized product form: strictly demoting in every
    factor, without the quadruple-penalty a raw product of four <=1 terms
    would apply.  Independence is enforced at the *cluster* level (one best
    claim per cluster per branch), not inside this per-claim score.
    """
    authority = SOURCE_CLASS_AUTHORITY.get(claim["source_class"], 0.10)
    accuracy = claim.get("historical_accuracy")
    accuracy = ACCURACY_MISSING if accuracy is None else _clamp(accuracy, 0.0, 1.0)

    jur = claim.get("jurisdiction") or ""
    wanted = {j.upper() for j in decision_jurisdictions if _text(j)}
    if not jur:
        proximity = PROXIMITY_MISSING
    elif not wanted or jur in wanted:
        proximity = PROXIMITY_IN_JURISDICTION
    else:
        proximity = PROXIMITY_OUT_OF_JURISDICTION

    age = claim.get("age_hours")
    if age is None:
        recency = RECENCY_MISSING
    else:
        recency = 2.0 ** (-max(age, 0.0) / RECENCY_HALF_LIFE_HOURS)

    gm = (authority * accuracy * proximity * recency) ** 0.25
    return {
        "sqs": round(10.0 * gm, 4),
        "quality_weight": round(gm, 6),
        "authority": authority,
        "accuracy": accuracy,
        "proximity": proximity,
        "recency": round(recency, 6),
    }


def independent_clusters(claims: list[dict[str, Any]]) -> dict[str, int]:
    """Distinct VERIFIED truth-bearing source clusters, total and per branch."""
    out: dict[str, set[str]] = {"__all__": set()}
    for c in claims:
        if c["verification"] != VERIFIED:
            continue
        if c["source_class"] not in TRUTH_BEARING_CLASSES:
            continue
        out["__all__"].add(c["source_cluster"])
        if c["branch"]:
            out.setdefault(c["branch"], set()).add(c["source_cluster"])
    return {k: len(v) for k, v in out.items()}


# ---------------------------------------------------------------------------
# Rumor / causal-leap detector — Truth(Event) != Truth(CausalClaim)
# ---------------------------------------------------------------------------

VERDICT_NO_RUMOR = "NO_RUMOR"
VERDICT_KERNEL_TRUE_LEAP = "TRUE_MICRO_EVENT_UNSUPPORTED_MACRO_CLAIM"
VERDICT_FABRICATION = "FABRICATION_SUSPECTED"
VERDICT_PARTIAL_TRUTH = "PARTIAL_TRUTH"
VERDICT_ENGAGEMENT_BAIT = "ENGAGEMENT_BAIT"


def _emotional_packaging(texts: list[str]) -> float:
    """Deterministic emotional-packaging score (0-1), v1.1.

    0.6 x lexicon hits (saturates at 3) + 0.2 x exclamation density
    (saturates at 3 '!') + 0.2 x ALL-CAPS word ratio (saturates at 25% of
    tokens).  Still deterministic and auditable — richer than a bare word
    list, no model in the loop.
    """
    joined = " ".join(texts)
    lowered = joined.lower()
    hits = sum(1 for w in EMOTIONAL_PACKAGING_WORDS if w in lowered)
    word_component = _clamp(hits / 3.0, 0.0, 1.0)
    exclam_component = _clamp(joined.count("!") / 3.0, 0.0, 1.0)
    tokens = re.findall(r"[A-Za-z']+", joined)
    caps = [t for t in tokens if len(t) >= 3 and t.isupper()]
    caps_ratio = len(caps) / max(1, len(tokens))
    caps_component = _clamp(caps_ratio / 0.25, 0.0, 1.0)
    return round(
        _clamp(0.6 * word_component + 0.2 * exclam_component
               + 0.2 * caps_component, 0.0, 1.0), 4,
    )


def evaluate_rumor_risk(claims: list[dict[str, Any]]) -> dict[str, Any]:
    """RumorRisk (0-10) = 10 * KernelTruth * CausalLeap * f(Emotion) * f(Velocity).

    KernelTruth comes from VERIFIED TRIGGER/CORE_FACT claims (the true seed);
    CausalLeap = max over rumor claims of (claim_magnitude - evidence_strength)/10.
    A true kernel makes the rumor MORE dangerous — the reflection's central
    lesson.  Emotion and velocity are floored at 0.5 so a verified kernel plus
    a large leap scores high even before packaging data arrives (fail closed
    toward caution, not toward comfort).
    """
    rumor_claims = [c for c in claims if c["layer"] == "RUMOR"]
    if not rumor_claims:
        return {
            "RUMOR_RISK": 0.0, "verdict": VERDICT_NO_RUMOR,
            "kernel_truth": 0.0, "causal_leap": 0.0,
            "emotional_packaging": 0.0, "amplification_speed": 0.0,
            "velocity_source": "NONE",
            "rumor_claim_ids": [], "notes": [],
        }

    kernel_claims = [
        c for c in claims
        if c["layer"] in ("TRIGGER", "CORE_FACT")
        and c["verification"] == VERIFIED
        and c["source_class"] in TRUTH_BEARING_CLASSES
    ]
    kernel_truth = max((c["strength"] for c in kernel_claims), default=0.2)

    causal_leap = max(
        (max(0.0, c["claim_magnitude"] - c["evidence_strength"]) / 10.0
         for c in rumor_claims),
        default=0.0,
    )

    emotional = _emotional_packaging([c["claim_text"] for c in rumor_claims])

    mph_values = [
        c["mentions_per_hour"] for c in claims
        if c["layer"] in ("RUMOR", "AMPLIFICATION") and c["mentions_per_hour"] is not None
    ]
    amp_claims = [c for c in claims if c["layer"] == "AMPLIFICATION"]
    if mph_values:
        amplification = _clamp(max(mph_values) / AMPLIFICATION_SATURATION_MPH, 0.0, 1.0)
        velocity_source = "mentions_per_hour"
    elif amp_claims:
        amplification = _clamp(len(amp_claims) / 3.0, 0.0, 1.0)
        velocity_source = "amplification_claim_count"
    else:
        amplification = 0.0
        velocity_source = "NONE"

    risk = 10.0 * kernel_truth * causal_leap \
        * (0.5 + 0.5 * emotional) * (0.5 + 0.5 * amplification)

    max_magnitude = max(c["claim_magnitude"] for c in rumor_claims)
    max_evidence = max(c["evidence_strength"] for c in rumor_claims)
    if kernel_truth >= 0.5 and causal_leap >= 0.5:
        verdict = VERDICT_KERNEL_TRUE_LEAP
    elif kernel_truth < 0.3:
        verdict = VERDICT_FABRICATION
    elif emotional >= 0.7 and max_evidence <= 2.0:
        verdict = VERDICT_ENGAGEMENT_BAIT
    elif causal_leap < 0.3:
        verdict = VERDICT_PARTIAL_TRUTH
    else:
        verdict = VERDICT_KERNEL_TRUE_LEAP

    return {
        "RUMOR_RISK": round(_clamp(risk, 0.0, 10.0), 4),
        "verdict": verdict,
        "kernel_truth": round(kernel_truth, 4),
        "causal_leap": round(causal_leap, 4),
        "emotional_packaging": round(emotional, 4),
        "amplification_speed": round(amplification, 4),
        "velocity_source": velocity_source,
        "max_claim_magnitude": max_magnitude,
        "max_evidence_strength": max_evidence,
        "rumor_claim_ids": [c["claim_id"] for c in rumor_claims],
        "notes": [
            "kernel truth verified from non-social sources"
            if kernel_claims else "no verified kernel: fabrication suspected",
        ],
    }


# ---------------------------------------------------------------------------
# Event branch engine — log-odds updates, one best claim per cluster
# ---------------------------------------------------------------------------


def evaluate_event_branches(
    claims: list[dict[str, Any]],
    priors: dict[str, Any] | None = None,
    decision_jurisdictions: list[str] | tuple[str, ...] = (),
) -> dict[str, dict[str, Any]]:
    """Per-branch posterior from VERIFIED truth-bearing claims only.

    Update rule per branch::

        logit(P) = logit(prior) + sum over clusters of
                   sign * CLASS_LLR[class] * quality_weight * strength

    with exactly ONE claim per source cluster per branch (the highest-quality
    one), so repetition inside a cluster cannot compound.  SOCIAL/LLM claims
    and UNVERIFIED claims contribute zero.  Hard invariant applied at the
    end:  every core-bounded sub-branch <= P(core_event).
    """
    priors = priors if isinstance(priors, dict) else {}
    results: dict[str, dict[str, Any]] = {}

    for branch in BRANCHES:
        prior_raw = _num(priors.get(branch))
        prior = _clamp(
            PRIOR_DEFAULT if prior_raw is None else prior_raw,
            PRIOR_CLAMP_LO, PRIOR_CLAMP_HI,
        )
        eligible = [
            c for c in claims
            if c["branch"] == branch
            and c["verification"] == VERIFIED
            and c["source_class"] in TRUTH_BEARING_CLASSES
            and c["direction"] in (DIRECTION_SUPPORTS, DIRECTION_REFUTES)
        ]
        # One best claim per cluster: independence discipline.
        best_by_cluster: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        for c in eligible:
            q = source_quality_score(c, decision_jurisdictions)
            held = best_by_cluster.get(c["source_cluster"])
            if held is None or q["quality_weight"] > held[1]["quality_weight"]:
                best_by_cluster[c["source_cluster"]] = (c, q)

        llr_sum = 0.0
        evidence: list[dict[str, Any]] = []
        for cluster, (c, q) in sorted(best_by_cluster.items()):
            sign = 1.0 if c["direction"] == DIRECTION_SUPPORTS else -1.0
            contribution = sign * CLASS_LLR[c["source_class"]] \
                * q["quality_weight"] * c["strength"]
            llr_sum += contribution
            evidence.append({
                "cluster": cluster,
                "claim_id": c["claim_id"],
                "source_class": c["source_class"],
                "direction": c["direction"],
                "sqs": q["sqs"],
                "llr_contribution": round(contribution, 4),
                "evidence_refs": c["evidence_refs"],
            })

        posterior = _sigmoid(_logit(prior) + llr_sum)
        # Independent confirmation: IC = 1 - prod(1 - qw*strength) over the
        # SUPPORTING clusters only (noisy-or of independent confirmations).
        ic = 1.0
        for cluster, (c, q) in best_by_cluster.items():
            if c["direction"] == DIRECTION_SUPPORTS:
                ic *= 1.0 - _clamp(q["quality_weight"] * c["strength"], 0.0, 1.0)
        results[branch] = {
            "p": round(posterior, 4),
            "prior": prior,
            "llr_sum": round(llr_sum, 4),
            "n_clusters": len(best_by_cluster),
            "independent_confirmation": round(1.0 - ic, 4),
            "status": "UPDATED" if best_by_cluster else INSUFFICIENT_EVIDENCE,
            "evidence": evidence,
        }

    # Hard invariant 1: sub-branches bounded by the core event.
    core_p = results["core_event"]["p"]
    for branch in CORE_BOUNDED_BRANCHES:
        if results[branch]["p"] > core_p:
            results[branch]["p"] = core_p
            results[branch]["status"] += "; CAPPED_BY_CORE"
    # Hard invariant 2 (v1.1): deals <= delegation <= core, UNLESS deals has
    # its own direct evidence clusters (evidence can support deals signed
    # around a reduced delegation, but silence cannot).
    deals, delegation = results["deals_or_mous"], results["delegation_intact"]
    if deals["n_clusters"] == 0 and deals["p"] > delegation["p"]:
        deals["p"] = delegation["p"]
        deals["status"] += "; CAPPED_BY_DELEGATION"
    return results


def source_disagreement_score(
    claims: list[dict[str, Any]],
    decision_jurisdictions: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """SourceDisagreement (0-10) = 10 * 4 * p * (1-p), the normalized Bernoulli
    variance of quality-weighted SUPPORT share across independent clusters."""
    support = 0.0
    refute = 0.0
    for c in claims:
        if c["verification"] != VERIFIED or c["source_class"] not in TRUTH_BEARING_CLASSES:
            continue
        if c["direction"] == DIRECTION_NEUTRAL or not c["branch"]:
            continue
        w = source_quality_score(c, decision_jurisdictions)["quality_weight"]
        if c["direction"] == DIRECTION_SUPPORTS:
            support += w
        else:
            refute += w
    total = support + refute
    if total <= 0:
        return {"SOURCE_DISAGREEMENT": 0.0, "status": INSUFFICIENT_EVIDENCE}
    p = support / total
    return {
        "SOURCE_DISAGREEMENT": round(10.0 * 4.0 * p * (1.0 - p), 4),
        "support_weight": round(support, 4),
        "refute_weight": round(refute, 4),
        "status": "COMPUTED",
    }


# ---------------------------------------------------------------------------
# Event state machine
# ---------------------------------------------------------------------------


def derive_event_state(
    branches: dict[str, dict[str, Any]],
    rumor: dict[str, Any],
    claims: list[dict[str, Any]],
) -> dict[str, Any]:
    """Deterministic event state from the branch vector + rumor risk.

    Precedence (first match wins):
      DEAD < only when the core branch collapses — a collapsed sub-branch can
      never kill the event (test #10's doctrine);
      RESOLVED / PARTIAL_RESOLUTION on verified official-layer claims;
      TRANSFORMED when core survives but a sub-branch collapsed;
      RUMOR_CONTESTED when rumor risk is capped-high and core still stands;
      WATCH_ONLY when nothing verified moved any branch;
      EMERGING when the verified corpus is still tiny;  else ACTIVE.
    """
    core_p = branches["core_event"]["p"]
    verified = [c for c in claims if c["verification"] == VERIFIED]
    verified_official = [
        c for c in verified
        if c["layer"] in ("OFFICIAL_RESOLUTION", "PARTIAL_RESOLUTION")
        and c["source_class"] in TRUTH_BEARING_CLASSES
    ]
    collapsed = [
        b for b in CORE_BOUNDED_BRANCHES
        if branches[b]["status"] != INSUFFICIENT_EVIDENCE
        and branches[b]["p"] < BRANCH_COLLAPSE_THRESHOLD
    ]

    if core_p < CORE_DEAD_THRESHOLD:
        state, reason = "DEAD", f"core branch collapsed (p={core_p})"
    elif any(c["layer"] == "OFFICIAL_RESOLUTION" for c in verified_official):
        state, reason = "RESOLVED", "verified official resolution claim"
    elif any(c["layer"] == "PARTIAL_RESOLUTION" for c in verified_official):
        state, reason = "PARTIAL_RESOLUTION", "verified partial-resolution claim"
    elif core_p >= CORE_STRONG_THRESHOLD and collapsed:
        state = "TRANSFORMED"
        reason = f"core survives (p={core_p}) while {', '.join(collapsed)} collapsed"
    elif rumor["RUMOR_RISK"] >= RUMOR_CAP_THRESHOLD and core_p >= BRANCH_SURVIVE_THRESHOLD:
        state, reason = "RUMOR_CONTESTED", (
            f"rumor risk {rumor['RUMOR_RISK']} vs surviving core (p={core_p})"
        )
    elif all(branches[b]["status"] == INSUFFICIENT_EVIDENCE for b in BRANCHES):
        state, reason = "WATCH_ONLY", "no verified truth-bearing claim on any branch"
    elif len(verified) < EMERGING_MIN_VERIFIED_CLAIMS:
        state, reason = "EMERGING", f"only {len(verified)} verified claims"
    else:
        state, reason = "ACTIVE", "core intact, no collapse, rumor below cap"

    return {"state": state, "reason": reason, "collapsed_branches": collapsed}


# ---------------------------------------------------------------------------
# Event-level confidence decay (v1.1) — official silence erodes confidence
# ---------------------------------------------------------------------------


def evaluate_confidence_decay(
    event: dict[str, Any], claims: list[dict[str, Any]],
) -> dict[str, Any]:
    """C_t = e^(-lambda_c * days_unconfirmed).  Demote-only, fail-closed.

    Resolution order: freshest VERIFIED OFFICIAL_GOVERNMENT claim age ->
    explicit ``days_since_official_confirmation`` on the event -> no official
    signal at all -> flat CONFIDENCE_DECAY_MISSING haircut with a note.
    """
    official_ages = [
        c["age_hours"] / 24.0 for c in claims
        if c["verification"] == VERIFIED
        and c["source_class"] == "OFFICIAL_GOVERNMENT"
        and c["age_hours"] is not None
    ]
    notes: list[str] = []
    if official_ages:
        days = min(official_ages)
        source = "official_claim_age"
    else:
        days = _num(event.get("days_since_official_confirmation"))
        if days is not None:
            days = max(days, 0.0)
            source = "event_input"
        else:
            notes.append(
                "no official confirmation signal -> flat "
                f"x{CONFIDENCE_DECAY_MISSING} confidence haircut"
            )
            return {
                "C_t": CONFIDENCE_DECAY_MISSING,
                "days_unconfirmed": None,
                "source": INSUFFICIENT_EVIDENCE,
                "notes": notes,
            }
    c_t = _clamp(math.exp(-CONFIDENCE_DECAY_LAMBDA_PER_DAY * days), 0.0, 1.0)
    return {
        "C_t": round(c_t, 4),
        "days_unconfirmed": round(days, 3),
        "source": source,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Exposure rotation + per-ticker demote-only scoring
# ---------------------------------------------------------------------------


def evaluate_price_validation(exposure: dict[str, Any]) -> dict[str, Any]:
    """PriceDislocation = |P_model - P_market_implied| * |RealizedMoveZScore|.

    All three inputs required.  Missing any -> INSUFFICIENT_EVIDENCE and the
    exposure is capped WATCH_ONLY: narrative scores never float in the air.
    """
    model_p = _num(exposure.get("model_probability"))
    implied_p = _num(exposure.get("market_implied_probability"))
    zscore = _num(exposure.get("realized_move_zscore"))
    if model_p is None or implied_p is None or zscore is None:
        missing = [
            name for name, v in (
                ("model_probability", model_p),
                ("market_implied_probability", implied_p),
                ("realized_move_zscore", zscore),
            ) if v is None
        ]
        return {
            "status": INSUFFICIENT_EVIDENCE,
            "dislocation": None,
            "notes": [f"price validation missing: {', '.join(missing)} -> WATCH_ONLY"],
        }
    dislocation = abs(model_p - implied_p) * abs(zscore)
    return {
        "status": "COMPUTED",
        "dislocation": round(dislocation, 4),
        "model_probability": model_p,
        "market_implied_probability": implied_p,
        "realized_move_zscore": zscore,
        "notes": [],
    }


def score_exposure(
    exposure: dict[str, Any],
    branches: dict[str, dict[str, Any]],
    rumor: dict[str, Any],
    confidence_decay: float = 1.0,
) -> dict[str, Any]:
    """One ticker exposure -> demote-only FINAL_TICKER_SCORE (0-10) + status.

    FINAL = VALIDATED_RELEVANCE x m_branch x m_filing x m_liquidity
            x m_staleness x m_rumor         (every multiplier in [0, 1])

    Fail-closed:
    * no verified evidence refs -> score 0, NO_VERIFIED_EVIDENCE;
    * no price validation       -> ticker capped WATCH_ONLY;
    * rumor >= cap threshold    -> ticker can never be ACTIONABLE.
    Rumor can trigger DISLOCATION_WATCH (an advisory flag) but never raises
    the score — the flag is the only "upside" a rumor is allowed to produce.
    """
    notes: list[str] = []
    ticker = _text(exposure.get("ticker")).upper() or "UNKNOWN"
    channel = _text(exposure.get("channel")).upper()
    if channel not in CATALYST_CHANNELS:
        notes.append(f"unknown channel {channel or '<missing>'!r} -> BROAD_THEMATIC")
        channel = "BROAD_THEMATIC"
    governing = CHANNEL_GOVERNING_BRANCH[channel]
    branch_p = branches[governing]["p"]

    refs_raw = exposure.get("evidence_refs")
    refs = [
        _text(r) for r in (refs_raw if isinstance(refs_raw, list) else [])
        if _text(r)
    ]

    base = _clamp(_num(exposure.get("base_relevance"), 0.0), 0.0, 10.0)
    evidence_confidence = _num(exposure.get("evidence_confidence"))
    if evidence_confidence is None:
        evidence_confidence = 0.5
        notes.append("evidence_confidence missing -> 0.5")
    evidence_confidence = _clamp(evidence_confidence, 0.0, 1.0)
    validated = base * (0.5 + 0.5 * evidence_confidence)

    if not refs:
        return {
            "ticker": ticker, "channel": channel, "governing_branch": governing,
            "branch_p": branch_p,
            "BASE_RELEVANCE": base, "VALIDATED_RELEVANCE": round(validated, 4),
            "FINAL_TICKER_SCORE": 0.0,
            "status": "NO_VERIFIED_EVIDENCE",
            "actionable": False, "downgraded": False,
            "multipliers": {}, "price_validation": {"status": INSUFFICIENT_EVIDENCE},
            "flags": [], "notes": notes + ["no evidence refs -> score 0 (fail closed)"],
        }

    m_branch = _clamp(branch_p, 0.0, 1.0)

    filing_confirmed = exposure.get("filing_confirmed") is True
    m_filing = 1.0 if filing_confirmed else FILING_UNCONFIRMED_MULTIPLIER
    if not filing_confirmed:
        notes.append("filing unconfirmed -> x0.60")

    liquidity_ok = exposure.get("liquidity_ok")
    if liquidity_ok is True:
        m_liquidity = 1.0
    elif liquidity_ok is False:
        m_liquidity = 0.0
        notes.append("liquidity below floor -> score 0")
    else:
        m_liquidity = LIQUIDITY_UNKNOWN_MULTIPLIER
        notes.append("liquidity unknown -> x0.50")

    staleness_days = _num(exposure.get("days_since_last_verified"))
    if staleness_days is None:
        m_staleness = STALENESS_MISSING_MULTIPLIER
        notes.append("staleness unknown -> x0.85")
    else:
        m_staleness = math.exp(-STALENESS_LAMBDA_PER_DAY * max(staleness_days, 0.0))

    m_rumor = _clamp(1.0 - 0.05 * rumor["RUMOR_RISK"], 0.0, 1.0)
    m_confidence = _clamp(confidence_decay, 0.0, 1.0)

    final = (
        validated * m_branch * m_filing * m_liquidity
        * m_staleness * m_rumor * m_confidence
    )

    price = evaluate_price_validation(exposure)
    notes.extend(price["notes"])

    # v1.1 capped dislocation bonus: min(1 + kappa*PD, 1.25), and the result
    # is min()-guarded against validated merit so FINAL <= VALIDATED always.
    price_bonus = 1.0
    if price["status"] == "COMPUTED" and price["dislocation"]:
        price_bonus = min(
            1.0 + PRICE_BONUS_KAPPA * price["dislocation"], PRICE_BONUS_CAP
        )
        final = min(final * price_bonus, validated)

    flags: list[str] = []
    downgraded = branch_p < BRANCH_COLLAPSE_THRESHOLD
    if downgraded:
        flags.append(f"BRANCH_COLLAPSED:{governing}")
    if (
        price["status"] == "COMPUTED"
        and price["dislocation"] is not None
        and price["dislocation"] >= DISLOCATION_WATCH_THRESHOLD
        and rumor["RUMOR_RISK"] >= DISLOCATION_RUMOR_MIN
        and branches["core_event"]["p"] >= CORE_STRONG_THRESHOLD
    ):
        flags.append("DISLOCATION_WATCH")

    actionable = (
        price["status"] == "COMPUTED"
        and rumor["RUMOR_RISK"] < RUMOR_CAP_THRESHOLD
        and not downgraded
        and final > 0.0
    )
    if downgraded:
        status = "DOWNGRADED"
    elif price["status"] != "COMPUTED":
        status = "WATCH_ONLY"
    elif rumor["RUMOR_RISK"] >= RUMOR_CAP_THRESHOLD:
        status = "RUMOR_CAPPED"
    elif final <= 0.0:
        status = "SCORED_OUT"
    else:
        status = "SURVIVING"

    return {
        "ticker": ticker, "channel": channel, "governing_branch": governing,
        "branch_p": branch_p,
        "BASE_RELEVANCE": base,
        "VALIDATED_RELEVANCE": round(validated, 4),
        "FINAL_TICKER_SCORE": round(final, 4),
        "status": status,
        "actionable": actionable,
        "downgraded": downgraded,
        "multipliers": {
            "m_branch": round(m_branch, 4),
            "m_filing": m_filing,
            "m_liquidity": m_liquidity,
            "m_staleness": round(m_staleness, 4),
            "m_rumor": round(m_rumor, 4),
            "m_confidence_decay": round(m_confidence, 4),
        },
        # Reported outside `multipliers` because it is the one term allowed
        # above 1.0 — capped at PRICE_BONUS_CAP and min()-guarded by merit.
        "price_bonus_capped": round(price_bonus, 4),
        "price_validation": price,
        "evidence_refs": refs,
        "flags": flags,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Hedge suggestion — long surviving basket / underweight collapsed basket
# ---------------------------------------------------------------------------


def build_hedge_suggestion(scored: list[dict[str, Any]]) -> dict[str, Any]:
    surviving = [
        t for t in scored
        if not t["downgraded"] and t["FINAL_TICKER_SCORE"] > 0.0
        and t["status"] != "NO_VERIFIED_EVIDENCE"
    ]
    collapsed = [t for t in scored if t["downgraded"]]
    # Both sides weighted by pre-demotion validated relevance so the ratio
    # compares like-for-like exposure, not post-haircut score vs raw merit.
    long_weight = sum(t["VALIDATED_RELEVANCE"] for t in surviving)
    stranded_weight = sum(t["VALIDATED_RELEVANCE"] for t in collapsed)
    if long_weight <= 0:
        return {
            "status": INSUFFICIENT_EVIDENCE,
            "hedge_ratio": None, "hedge_class": None,
            "long_basket": [], "underweight_basket": [t["ticker"] for t in collapsed],
            "notes": ["no surviving long basket -> no hedge ratio computable"],
        }
    ratio = round(min(stranded_weight / long_weight, 2.0), 4)
    return {
        "status": "COMPUTED",
        "hedge_ratio": ratio,
        "hedge_class": classify_hedge_ratio(ratio).value,
        "long_basket": [t["ticker"] for t in surviving],
        "underweight_basket": [t["ticker"] for t in collapsed],
        "notes": [],
    }


def hedge_need_score(
    branches: dict[str, dict[str, Any]], scored: list[dict[str, Any]]
) -> float:
    """HedgeNeed (0-10): mean branch uncertainty (4p(1-p)) over exposure-
    relevant branches, weighted up by the stranded-exposure fraction."""
    used = {t["governing_branch"] for t in scored} | {"core_event"}
    uncertainties = [
        4.0 * branches[b]["p"] * (1.0 - branches[b]["p"]) for b in sorted(used)
    ]
    base = sum(uncertainties) / len(uncertainties) if uncertainties else 0.0
    total = sum(t["VALIDATED_RELEVANCE"] for t in scored)
    stranded = sum(t["VALIDATED_RELEVANCE"] for t in scored if t["downgraded"])
    stranded_fraction = (stranded / total) if total > 0 else 0.0
    return round(_clamp(10.0 * (0.6 * base + 0.4 * stranded_fraction), 0.0, 10.0), 4)


# ---------------------------------------------------------------------------
# NDM (epistemic drift) + CFD (consensus) wiring — reuse, not duplication
# ---------------------------------------------------------------------------


def build_ndm_view(
    claims: list[dict[str, Any]],
    decision_jurisdictions: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """Feed the claim corpus through narrative_drift_monitor.

    Per claim: narrative_confidence = the claim's own asserted strength;
    signal_strength = that strength discounted by evidence quality (zero for
    non-truth-bearing/unverified claims).  A corpus of loud claims with weak
    evidence therefore drifts NARRATIVE_FIRST — the tarot-reader alarm,
    applied to a single event's information diet.
    """
    entries: list[NDMEntry] = []
    for c in claims:
        if c["verification"] == VERIFIED and c["source_class"] in TRUTH_BEARING_CLASSES:
            q = source_quality_score(c, decision_jurisdictions)["quality_weight"]
            signal = c["strength"] * q
        else:
            signal = 0.0
        nii = 1.0
        if c["layer"] == "RUMOR":
            nii = (c["claim_magnitude"] + 1.0) / (c["evidence_strength"] + 1.0)
        entries.append(NDMEntry(
            narrative_confidence=c["strength"],
            signal_strength=signal,
            is_falsifiable=bool(c["evidence_refs"]),
            nii_score=nii,
        ))
    metrics = compute_ndm_drift(entries)
    return {"ndm_state": classify_ndm_state(metrics), "metrics": metrics}


def build_consensus_view(consensus: Any) -> dict[str, Any]:
    """Optional CFD wiring: pc/rs/cc/ms (+ cs_previous) -> CS + state + slope."""
    if not isinstance(consensus, dict):
        return {"status": INSUFFICIENT_EVIDENCE, "notes": ["no consensus inputs"]}
    parts = [_num(consensus.get(k)) for k in ("pc", "rs", "cc", "ms")]
    if any(p is None for p in parts):
        return {"status": INSUFFICIENT_EVIDENCE, "notes": ["pc/rs/cc/ms incomplete"]}
    cs = compute_cs(*[_clamp(p, 0.0, 1.0) for p in parts])  # type: ignore[misc]
    prev = _num(consensus.get("cs_previous"))
    return {
        "status": "COMPUTED",
        "cs": round(cs, 4),
        "cfd_state": classify_cfd_state(cs),
        "dcdt": None if prev is None else round(cs - prev, 4),
        "notes": [],
    }


# ---------------------------------------------------------------------------
# The unified report
# ---------------------------------------------------------------------------


def _narrative_confidence(
    claims: list[dict[str, Any]],
    clusters: dict[str, int],
    decision_jurisdictions: list[str] | tuple[str, ...],
) -> float:
    """NarrativeConfidence (0-10): evidence-quality-weighted claim strength,
    one best claim per cluster, scaled by confirmation breadth (>=3 clusters
    for full credit).  Zero when nothing verified exists."""
    best: dict[str, float] = {}
    for c in claims:
        if c["verification"] != VERIFIED or c["source_class"] not in TRUTH_BEARING_CLASSES:
            continue
        q = source_quality_score(c, decision_jurisdictions)["quality_weight"]
        value = c["strength"] * q
        if value > best.get(c["source_cluster"], 0.0):
            best[c["source_cluster"]] = value
    if not best:
        return 0.0
    mean = sum(best.values()) / len(best)
    breadth = min(1.0, clusters.get("__all__", 0) / 3.0)
    return round(_clamp(10.0 * mean * breadth, 0.0, 10.0), 4)


def _decide_action(
    state: dict[str, Any],
    rumor: dict[str, Any],
    scored: list[dict[str, Any]],
    operator_action_score: float = 0.0,
) -> dict[str, Any]:
    scoreable = [t for t in scored if t["status"] != "NO_VERIFIED_EVIDENCE"]
    actionable = [t for t in scored if t["actionable"]]
    top = max((t["FINAL_TICKER_SCORE"] for t in actionable), default=0.0)

    if state["state"] == "DEAD":
        action, why = ACTION_FOLD, "core branch collapsed: fold the whole thesis"
    elif not scoreable or all(
        t["FINAL_TICKER_SCORE"] <= 0.0 for t in scoreable
    ):
        action = ACTION_NO_EXPOSURE
        why = "no exposure with verified evidence survives scoring (fail closed)"
    elif state["state"] in ("TRANSFORMED", "PARTIAL_RESOLUTION") and any(
        t["downgraded"] for t in scored
    ):
        action = ACTION_ROTATE
        why = (
            f"{state['reason']}; rotate out of collapsed-channel names, "
            "keep surviving-layer basket"
        )
    elif (
        top >= ACT_MIN_SCORE
        and operator_action_score >= ACT_MIN_OAS
        and rumor["RUMOR_RISK"] < ACT_MAX_RUMOR
    ):
        action = ACTION_ACT
        why = (
            f"top surviving score {top}, operator action score "
            f"{operator_action_score} >= {ACT_MIN_OAS}, rumor below {ACT_MAX_RUMOR}"
        )
    else:
        action = ACTION_WATCH
        why = "no actionable exposure clears the ACT bar yet"

    # Rumor cap is absolute: high rumor risk can reduce/redirect but never ACT.
    if rumor["RUMOR_RISK"] >= RUMOR_CAP_THRESHOLD and action == ACTION_ACT:
        action = ACTION_ROTATE if any(t["downgraded"] for t in scored) else ACTION_WATCH
        why = (
            f"rumor risk {rumor['RUMOR_RISK']} >= {RUMOR_CAP_THRESHOLD} caps action; "
            "thesis survives at reduced confidence — verify before acting"
        )
    return {"action": action, "why": why}


def _verify_next(
    branches: dict[str, dict[str, Any]],
    rumor: dict[str, Any],
    scored: list[dict[str, Any]],
) -> list[str]:
    items: list[str] = []
    for b in BRANCHES:
        if branches[b]["status"] == INSUFFICIENT_EVIDENCE:
            items.append(f"no verified evidence on branch '{b}' - find a truth-bearing source")
    if rumor["RUMOR_RISK"] > 0 and rumor["verdict"] == VERDICT_KERNEL_TRUE_LEAP:
        items.append(
            "rumor rests on an unsupported causal bridge - seek official "
            "confirmation/denial before treating it as branch evidence"
        )
    for t in scored:
        if t["price_validation"]["status"] != "COMPUTED":
            items.append(f"{t['ticker']}: supply price/volume validation to leave WATCH_ONLY")
        if not t.get("multipliers", {}).get("m_filing", 1.0) == 1.0:
            items.append(f"{t['ticker']}: filing confirmation would lift x0.60 haircut")
    return items[:10]


def explain_surviving_layer(
    branches: dict[str, dict[str, Any]],
    state: dict[str, Any],
    scored: list[dict[str, Any]],
) -> dict[str, Any]:
    """The 'trade the surviving layer' explanation engine."""
    surviving = sorted(
        b for b in BRANCHES
        if b != "already_priced_in" and branches[b]["p"] >= BRANCH_SURVIVE_THRESHOLD
    )
    killed = sorted(state.get("collapsed_branches", []))
    kept = [t["ticker"] for t in scored if t["status"] in ("SURVIVING", "RUMOR_CAPPED")]
    dropped = [t["ticker"] for t in scored if t["downgraded"]]
    sentence = (
        "Surviving layer: "
        + (", ".join(surviving) if surviving else "none")
        + ". Killed layer: "
        + (", ".join(killed) if killed else "none")
        + "."
    )
    if kept or dropped:
        sentence += (
            f" Basket rotation: keep {', '.join(kept) or 'nothing'};"
            f" downgrade {', '.join(dropped) or 'nothing'}."
        )
    return {
        "surviving_branches": surviving,
        "killed_branches": killed,
        "kept_tickers": kept,
        "downgraded_tickers": dropped,
        "sentence": sentence,
    }


def build_event_report(event: dict[str, Any]) -> dict[str, Any]:
    """Run the full NBI pipeline over one event dict -> operator report."""
    data = event if isinstance(event, dict) else {}
    jurisdictions = [
        _text(j).upper() for j in (data.get("decision_jurisdictions") or [])
        if _text(j)
    ]
    claims = normalize_claims(data.get("claims"))
    excluded = [c for c in claims if c["verification"] == UNVERIFIED]

    clusters = independent_clusters(claims)
    rumor = evaluate_rumor_risk(claims)
    branches = evaluate_event_branches(claims, data.get("priors"), jurisdictions)
    disagreement = source_disagreement_score(claims, jurisdictions)
    state = derive_event_state(branches, rumor, claims)

    decay = evaluate_confidence_decay(data, claims)

    exposures_raw = data.get("exposures")
    scored = [
        score_exposure(e, branches, rumor, confidence_decay=decay["C_t"])
        for e in (exposures_raw if isinstance(exposures_raw, list) else [])
        if isinstance(e, dict)
    ]
    scored.sort(key=lambda t: t["FINAL_TICKER_SCORE"], reverse=True)

    hedge = build_hedge_suggestion(scored)
    ndm = build_ndm_view(claims, jurisdictions)
    consensus = build_consensus_view(data.get("consensus"))
    surviving = explain_surviving_layer(branches, state, scored)

    narrative_confidence = _narrative_confidence(claims, clusters, jurisdictions)
    event_branch_score = round(branches["core_event"]["p"] * 10.0, 4)
    hedge_need = hedge_need_score(branches, scored)
    # OAS (v1.1 spec): top *evidence-valid* final score x (1 - RR/10) x C_t.
    # Evidence validity is structural — only actionable-eligible rows (verified
    # refs, price-validated, un-downgraded) can supply the top score.
    top_valid = max(
        (t["FINAL_TICKER_SCORE"] for t in scored if t["actionable"]), default=0.0
    )
    operator_action_score = round(
        _clamp(
            top_valid * (1.0 - rumor["RUMOR_RISK"] / 10.0) * decay["C_t"],
            0.0, 10.0,
        ), 4,
    )
    decision = _decide_action(state, rumor, scored, operator_action_score)

    drift = cosine_drift(
        data.get("narrative_vector_prev"), data.get("narrative_vector_now")
    )
    explicit_drift = _num(data.get("narrative_drift"))
    if drift is None and explicit_drift is not None:
        drift = round(_clamp(explicit_drift, 0.0, 2.0), 4)

    report: dict[str, Any] = {
        "report": "narrative_branch_intelligence",
        "NBI_PROFILE_VERSION": NBI_PROFILE_VERSION,
        "event_id": _text(data.get("event_id")) or "UNKNOWN_EVENT",
        "event_name": _text(data.get("event_name")) or _text(data.get("event_id")),
        "decision_jurisdictions": jurisdictions,
        "EVENT_STATE": state["state"],
        "event_state_reason": state["reason"],
        "branches": branches,
        "rumor": rumor,
        "scores": {
            "RUMOR_RISK": rumor["RUMOR_RISK"],
            "NARRATIVE_CONFIDENCE": narrative_confidence,
            "EVENT_BRANCH": event_branch_score,
            "SOURCE_DISAGREEMENT": disagreement.get("SOURCE_DISAGREEMENT", 0.0),
            "HEDGE_NEED": hedge_need,
            "OPERATOR_ACTION": operator_action_score,
        },
        "source_disagreement": disagreement,
        "independent_clusters": clusters,
        "confidence_decay": decay,
        "claims": claims,
        "narrative_drift": drift,
        "ndm": ndm,
        "consensus": consensus,
        "surviving_layer": surviving,
        "tickers": scored,
        "downgraded_tickers": [t["ticker"] for t in scored if t["downgraded"]],
        "hedge": hedge,
        "ACTION": decision["action"],
        "action_why": decision["why"],
        "verify_next": _verify_next(branches, rumor, scored),
        "claims_total": len(claims),
        "claims_verified": len(claims) - len(excluded),
        "claims_excluded_unverified": [
            {"claim_id": c["claim_id"], "notes": c["notes"]} for c in excluded
        ],
        "invariants": {
            "sub_branches_leq_core": all(
                branches[b]["p"] <= branches["core_event"]["p"] + 1e-9
                for b in CORE_BOUNDED_BRANCHES
            ),
            "final_leq_validated_all_tickers": all(
                t["FINAL_TICKER_SCORE"] <= t["VALIDATED_RELEVANCE"] + 1e-9
                for t in scored
            ),
        },
    }
    report["ADVISORY_ONLY_STAMP"] = advisory_safety_stamps()
    report["safety"] = advisory_safety_stamps()
    report["human"] = human_only_stamp()
    return report


# ---------------------------------------------------------------------------
# Chicken-gate composition — NBI can only lower an existing decision
# ---------------------------------------------------------------------------

_NBI_ACTION_TO_GATE_CAP: dict[str, str] = {
    ACTION_ACT: "BUY_ALLOWED",
    ACTION_ROTATE: "BUY_LIMITED",
    ACTION_WATCH: "WATCHLIST",
    ACTION_FOLD: "BUY_BLOCKED",
    ACTION_NO_EXPOSURE: "BUY_BLOCKED",
}
_GATE_RANK = {"BUY_BLOCKED": 0, "WATCHLIST": 1, "BUY_LIMITED": 2, "BUY_ALLOWED": 3}


def integrate_with_chicken_gate(
    chicken_result: dict[str, Any],
    nbi_report: dict[str, Any],
    ticker: str,
) -> dict[str, Any]:
    """Demote-only min() composition with an existing chicken-gate result.

        INTEGRATED_FINAL_SCORE = min(CHICKEN_FINAL, NBI_TICKER_FINAL)
        INTEGRATED_GATE        = min-rank(chicken gate, NBI action cap)

    A ticker unknown to the NBI report keeps the chicken decision unchanged
    (the overlay may only demote what it has actually scored, never guess).
    """
    ticker_norm = _text(ticker).upper()
    row = next(
        (t for t in nbi_report.get("tickers", []) if t["ticker"] == ticker_norm),
        None,
    )
    chicken_score = _num(chicken_result.get("FINAL_SCORE"), 0.0) or 0.0
    chicken_gate = _text(chicken_result.get("FINAL_ACTION_GATE")) or "BUY_BLOCKED"
    if row is None:
        return {
            "ticker": ticker_norm,
            "INTEGRATED_FINAL_SCORE": round(chicken_score, 4),
            "INTEGRATED_GATE": chicken_gate,
            "nbi_applied": False,
            "notes": ["ticker not scored by NBI report -> chicken decision unchanged"],
        }
    per_ticker_cap = (
        "WATCHLIST" if row["status"] in ("WATCH_ONLY", "RUMOR_CAPPED")
        else "BUY_BLOCKED" if row["status"] == "NO_VERIFIED_EVIDENCE"
        else _NBI_ACTION_TO_GATE_CAP.get(
            nbi_report.get("ACTION", ACTION_WATCH), "WATCHLIST"
        )
    )
    gate = min((chicken_gate, per_ticker_cap), key=lambda g: _GATE_RANK.get(g, 0))
    return {
        "ticker": ticker_norm,
        "INTEGRATED_FINAL_SCORE": round(min(chicken_score, row["FINAL_TICKER_SCORE"]), 4),
        "INTEGRATED_GATE": gate,
        "nbi_applied": True,
        "nbi_ticker_status": row["status"],
        "nbi_action": nbi_report.get("ACTION"),
        "notes": [],
    }


# ---------------------------------------------------------------------------
# Backtest case seed — the calibration schema this module will be judged by
# ---------------------------------------------------------------------------

BACKTEST_CASE_FIELDS: tuple[str, ...] = (
    "event_id", "category", "initial_narrative", "rumor_peak_at",
    "branch_probabilities_at_rumor_peak", "resolution_labels",
    "affected_basket", "benchmark", "outcome_label",
    "false_positive", "false_negative", "r_multiple",
)

OUTCOME_LABELS: tuple[str, ...] = (
    "CORE_HELD_SUB_BRANCH_COLLAPSED", "CORE_HELD_INTACT", "CORE_DIED",
    "RUMOR_TRUE", "RUMOR_FALSE", "UNRESOLVED",
)


def build_backtest_case(
    report: dict[str, Any],
    *,
    category: str,
    resolution_labels: dict[str, Any],
    outcome_label: str,
    affected_basket: list[str] | None = None,
    benchmark: str = "",
    r_multiple: float | None = None,
) -> dict[str, Any]:
    """Freeze one NBI report + its eventual resolution into a backtest case.

    ``false_positive`` = the model said actionable and the outcome label says
    the rumor was true / core died; ``false_negative`` = the model folded or
    watched while the core held intact.  Advisory bookkeeping only.
    """
    if outcome_label not in OUTCOME_LABELS:
        raise ValueError(f"outcome_label must be one of {OUTCOME_LABELS}")
    action = report.get("ACTION")
    false_positive = action == ACTION_ACT and outcome_label in ("RUMOR_TRUE", "CORE_DIED")
    false_negative = action in (ACTION_FOLD, ACTION_WATCH) and outcome_label in (
        "CORE_HELD_INTACT", "CORE_HELD_SUB_BRANCH_COLLAPSED",
    )
    case = {
        "event_id": report.get("event_id"),
        "category": category,
        "initial_narrative": report.get("event_name"),
        "rumor_peak_at": report.get("rumor", {}).get("RUMOR_RISK"),
        "branch_probabilities_at_rumor_peak": {
            b: report["branches"][b]["p"] for b in BRANCHES
        },
        "resolution_labels": resolution_labels,
        "affected_basket": affected_basket
        or [t["ticker"] for t in report.get("tickers", [])],
        "benchmark": benchmark,
        "outcome_label": outcome_label,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "r_multiple": r_multiple,
    }
    missing = [f for f in BACKTEST_CASE_FIELDS if f not in case]
    if missing:  # pragma: no cover - schema drift guard
        raise ValueError(f"backtest case missing fields: {missing}")
    return case


# ---------------------------------------------------------------------------
# Operator event card
# ---------------------------------------------------------------------------


def render_event_card(report: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    add(
        "=== SLEEPING PASSENGER - NARRATIVE BRANCH EVENT CARD "
        f"({NBI_PROFILE_VERSION}) ==="
    )
    add(f"EVENT: {report['event_name']}    STATE: {report['EVENT_STATE']}")
    add(f"  ({report['event_state_reason']})")
    branch_bits = []
    for b in BRANCHES:
        info = report["branches"][b]
        marker = "?" if info["status"] == INSUFFICIENT_EVIDENCE else ""
        branch_bits.append(f"{b}={info['p']}{marker}")
    add("BRANCHES: " + " | ".join(branch_bits))
    add("  (? = INSUFFICIENT_EVIDENCE: posterior is still the prior)")
    r = report["rumor"]
    add(
        f"RUMOR RISK: {r['RUMOR_RISK']}  verdict={r['verdict']}"
        f"  kernel={r['kernel_truth']} leap={r['causal_leap']}"
    )
    s = report["scores"]
    add(
        f"SCORES (0-10): confidence={s['NARRATIVE_CONFIDENCE']}"
        f" branch={s['EVENT_BRANCH']} disagreement={s['SOURCE_DISAGREEMENT']}"
        f" hedge_need={s['HEDGE_NEED']} operator_action={s['OPERATOR_ACTION']}"
    )
    add(
        f"EVIDENCE: {report['claims_verified']}/{report['claims_total']} claims verified"
        f" | {report['independent_clusters'].get('__all__', 0)} independent clusters"
    )
    d = report["confidence_decay"]
    add(
        f"CONFIDENCE DECAY: C_t={d['C_t']}"
        f" (days_unconfirmed={d['days_unconfirmed']}, source={d['source']})"
    )
    add(
        f"EPISTEMIC DRIFT (NDM): {report['ndm']['ndm_state']}"
        f" drift={report['ndm']['metrics']['ndm_drift']}"
    )
    if report["narrative_drift"] is not None:
        add(f"NARRATIVE DRIFT: {report['narrative_drift']} (1 - cosine)")
    if report["consensus"].get("status") == "COMPUTED":
        c = report["consensus"]
        add(f"CONSENSUS (CFD): {c['cfd_state']} cs={c['cs']} dcdt={c['dcdt']}")
    add(f"SURVIVING LAYER: {report['surviving_layer']['sentence']}")
    add("--- tickers (demote-only: FINAL <= VALIDATED <= BASE) ---")
    for t in report["tickers"]:
        flags = f"  flags={','.join(t['flags'])}" if t["flags"] else ""
        add(
            f"  {t['ticker']:<14} {t['status']:<20}"
            f" final={t['FINAL_TICKER_SCORE']:<7} base={t['BASE_RELEVANCE']:<5}"
            f" branch={t['governing_branch']}({t['branch_p']}){flags}"
        )
    h = report["hedge"]
    if h["status"] == "COMPUTED":
        add(
            f"HEDGE: ratio={h['hedge_ratio']} class={h['hedge_class']}"
            f"  long={','.join(h['long_basket']) or '-'}"
            f"  underweight={','.join(h['underweight_basket']) or '-'}"
        )
    else:
        add("HEDGE: " + "; ".join(h["notes"]))
    add(f"ACTION: {report['ACTION']}")
    add(f"WHY: {report['action_why']}")
    if report["verify_next"]:
        add("VERIFY NEXT:")
        for item in report["verify_next"]:
            add(f"  - {item}")
    if report["claims_excluded_unverified"]:
        add(
            f"EXCLUDED (UNVERIFIED, cite-or-drop): "
            f"{len(report['claims_excluded_unverified'])} claim(s)"
        )
    add("ADVISORY_ONLY | execution gate LOCKED | human decides")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Demo fixture — the Guwahati -> Delhi pattern, generalized
# ---------------------------------------------------------------------------

DEMO_EVENT: dict[str, Any] = {
    "event_id": "jp-india-summit-2026",
    "event_name": "Japan-India summit: Guwahati venue vs New Delhi shift",
    "decision_jurisdictions": ["JP", "IN"],
    "priors": {
        "core_event": 0.55, "venue_specific": 0.50, "delegation_intact": 0.50,
        "deals_or_mous": 0.40, "sector_impact": 0.50, "already_priced_in": 0.30,
    },
    "claims": [
        {
            "claim_id": "core-reuters", "layer": "CORE_FACT",
            "claim_text": "Japan-India summit planned with ~50-company business delegation",
            "source_cluster": "reuters", "source_class": "CREDIBLE_MEDIA",
            "jurisdiction": "GLOBAL", "historical_accuracy": 0.85,
            "age_hours": 24, "direction": "SUPPORTS", "branch": "core_event",
            "strength": 0.8, "evidence_refs": ["https://example.com/reuters-summit"],
        },
        {
            "claim_id": "core-nikkei", "layer": "CORE_FACT",
            "claim_text": "Japanese PM office confirms summit preparations continue",
            "source_cluster": "nikkei", "source_class": "CREDIBLE_MEDIA",
            "jurisdiction": "JP", "historical_accuracy": 0.85,
            "age_hours": 20, "direction": "SUPPORTS", "branch": "core_event",
            "strength": 0.8, "evidence_refs": ["https://example.com/nikkei-summit"],
        },
        {
            "claim_id": "trigger-traffic", "layer": "TRIGGER",
            "claim_text": "Traffic crowding near Ganeshguri flyover during mural gathering",
            "source_cluster": "assam-local-press", "source_class": "LOCAL_MEDIA",
            "jurisdiction": "IN", "age_hours": 30, "direction": "NEUTRAL",
            "strength": 0.9, "evidence_refs": ["https://example.com/local-traffic"],
        },
        {
            "claim_id": "rumor-cancel", "layer": "RUMOR",
            "claim_text": (
                "BREAKING!! advance security team STUCK in CHAOS near Ganeshguri "
                "- visit may be CANCELLED, share this!!"
            ),
            "source_cluster": "insta-page", "source_class": "SOCIAL_MEDIA",
            "jurisdiction": "IN", "age_hours": 12, "direction": "REFUTES",
            "branch": "core_event", "strength": 0.9,
            "claim_magnitude": 9.0, "evidence_strength": 1.0,
            "mentions_per_hour": 40,
            "evidence_refs": ["https://example.com/insta-rumor"],
        },
        {
            "claim_id": "amp-reposts", "layer": "AMPLIFICATION",
            "claim_text": "Cancellation rumor reposted across local pages",
            "source_cluster": "insta-page", "source_class": "SOCIAL_MEDIA",
            "jurisdiction": "IN", "age_hours": 10, "direction": "NEUTRAL",
            "mentions_per_hour": 40,
            "evidence_refs": ["https://example.com/insta-reposts"],
        },
        {
            "claim_id": "correction-pti", "layer": "CORRECTION",
            "claim_text": "No official confirmation of cancellation; preparations continue",
            "source_cluster": "pti", "source_class": "CREDIBLE_MEDIA",
            "jurisdiction": "IN", "historical_accuracy": 0.8,
            "age_hours": 8, "direction": "SUPPORTS", "branch": "core_event",
            "strength": 0.6, "evidence_refs": ["https://example.com/pti-correction"],
        },
        {
            "claim_id": "venue-shift-jp", "layer": "CORE_FACT",
            "claim_text": "Venue likely shifted to New Delhi due to PM scheduling",
            "source_cluster": "nhk", "source_class": "CREDIBLE_MEDIA",
            "jurisdiction": "JP", "historical_accuracy": 0.85,
            "age_hours": 6, "direction": "REFUTES", "branch": "venue_specific",
            "strength": 0.7, "evidence_refs": ["https://example.com/nhk-venue"],
        },
        {
            "claim_id": "venue-shift-in", "layer": "CORE_FACT",
            "claim_text": "Officials indicate Delhi venue under active preparation",
            "source_cluster": "hindu", "source_class": "CREDIBLE_MEDIA",
            "jurisdiction": "IN", "historical_accuracy": 0.7,
            "age_hours": 5, "direction": "REFUTES", "branch": "venue_specific",
            "strength": 0.6, "evidence_refs": ["https://example.com/hindu-venue"],
        },
        {
            "claim_id": "delegation-nikkei", "layer": "CORE_FACT",
            "claim_text": "Business delegation roster unchanged per organizers",
            "source_cluster": "nikkei", "source_class": "CREDIBLE_MEDIA",
            "jurisdiction": "JP", "historical_accuracy": 0.85,
            "age_hours": 6, "direction": "SUPPORTS", "branch": "delegation_intact",
            "strength": 0.6, "evidence_refs": ["https://example.com/nikkei-delegation"],
        },
    ],
    "exposures": [
        {
            "ticker": "ASSAMINFRA", "channel": "VENUE_SPECIFIC",
            "base_relevance": 8.0, "evidence_confidence": 0.8,
            "evidence_refs": ["https://example.com/assam-infra-note"],
            "filing_confirmed": False, "liquidity_ok": True,
            "days_since_last_verified": 1.0,
        },
        {
            "ticker": "NE_CEMENT", "channel": "SYMBOLIC_LOCAL",
            "base_relevance": 7.0, "evidence_confidence": 0.7,
            "evidence_refs": ["https://example.com/ne-cement-note"],
            "filing_confirmed": False, "liquidity_ok": True,
            "days_since_last_verified": 1.0,
        },
        {
            "ticker": "JPMACH", "channel": "BROAD_THEMATIC",
            "base_relevance": 7.5, "evidence_confidence": 0.9,
            "evidence_refs": ["https://example.com/jpmach-filing"],
            "filing_confirmed": True, "liquidity_ok": True,
            "days_since_last_verified": 0.5,
            "model_probability": 0.62, "market_implied_probability": 0.50,
            "realized_move_zscore": 1.2,
        },
        {
            "ticker": "INDAUTO", "channel": "INDIRECT_VALUE_CHAIN",
            "base_relevance": 7.0, "evidence_confidence": 0.8,
            "evidence_refs": ["https://example.com/indauto-filing"],
            "filing_confirmed": True, "liquidity_ok": True,
            "days_since_last_verified": 0.5,
            "model_probability": 0.58, "market_implied_probability": 0.52,
            "realized_move_zscore": 0.9,
        },
        {
            "ticker": "TATAELEC_PROXY", "channel": "DIRECT_COMPANY",
            "base_relevance": 8.0, "evidence_confidence": 0.6,
            "evidence_refs": ["https://example.com/tata-assam-note"],
            "filing_confirmed": False, "liquidity_ok": True,
            "days_since_last_verified": 2.0,
        },
    ],
    "consensus": {"pc": 0.7, "rs": 0.6, "cc": 0.5, "ms": 0.6, "cs_previous": 0.05},
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Narrative Branch Engine: advisory-only claim->branch->exposure "
            "pipeline.  Scores an event JSON and prints the operator card."
        )
    )
    parser.add_argument("--event-json", help="Path to an event JSON file")
    parser.add_argument(
        "--demo", action="store_true",
        help="Score the Guwahati->Delhi demo event",
    )
    parser.add_argument("--json", action="store_true", help="Emit raw JSON report")
    args = parser.parse_args(argv)

    if args.demo:
        event = json.loads(json.dumps(DEMO_EVENT))
    elif args.event_json:
        with open(args.event_json, "r", encoding="utf-8") as fh:
            event = json.load(fh)
    else:
        parser.print_help()
        return 2

    report = build_event_report(event)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(render_event_card(report))
    return 0


__all__ = [
    "NBI_PROFILE_VERSION",
    "NARRATIVE_LAYERS", "SOURCE_CLASSES", "SOURCE_CLASS_AUTHORITY",
    "TRUTH_BEARING_CLASSES", "CLASS_LLR", "BRANCHES", "CORE_BOUNDED_BRANCHES",
    "EVENT_STATES", "ACTIONS", "CATALYST_CHANNELS", "CHANNEL_GOVERNING_BRANCH",
    "BACKTEST_CASE_FIELDS", "OUTCOME_LABELS", "DEMO_EVENT",
    "normalize_claim", "normalize_claims", "source_quality_score",
    "independent_clusters", "evaluate_rumor_risk", "evaluate_event_branches",
    "source_disagreement_score", "derive_event_state",
    "evaluate_price_validation", "evaluate_confidence_decay",
    "score_exposure", "build_hedge_suggestion",
    "hedge_need_score", "build_ndm_view", "build_consensus_view",
    "cosine_drift", "explain_surviving_layer", "build_event_report",
    "integrate_with_chicken_gate", "build_backtest_case",
    "render_event_card", "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
