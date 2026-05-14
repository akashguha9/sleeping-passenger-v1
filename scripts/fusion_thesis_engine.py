"""Fusion thesis engine — pure, deterministic, advisory-only.

Engineering translation of the reflection's "fusion thesis" metaphor.
Many weak *independent* signals can synthesize into a review-worthy
thesis. Many copies of the *same* signal cannot. The module measures
evidence density, signal temperature, confinement quality, time
durability, and source independence, and emits one of:

    valid_fusion
    weak_fusion
    echo_not_fusion
    overheated_uncontained
    insufficient_data

Output never grants execution permission.

Safety contract on every public output

    output["safety"]["advisory_status"]     == "ADVISORY_ONLY"
    output["safety"]["execution_gate"]      == "LOCKED"
    output["safety"]["broker_api_called"]   is False
    output["safety"]["ai_execution_count"]  == 0
    output["safety"]["execution_permission"] is False
    output["safety"]["can_execute"]         is False

Public API

    compute_evidence_density(signals)        -> dict
    compute_fusion_thesis_strength(signals)  -> dict
    classify_fusion_candidate(signals)       -> dict
"""

from __future__ import annotations

from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_GATE_LOCKED = "LOCKED"

SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": ADVISORY_STATUS,
    "execution_gate": EXECUTION_GATE_LOCKED,
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
}

FUSION_VALIDITIES: tuple[str, ...] = (
    "valid_fusion",
    "weak_fusion",
    "echo_not_fusion",
    "overheated_uncontained",
    "insufficient_data",
)


def _stamp(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out["safety"] = dict(SAFETY_STAMPS)
    out.setdefault("advisory_status", ADVISORY_STATUS)
    out.setdefault("execution_gate", EXECUTION_GATE_LOCKED)
    return out


def _clamp(value: Any, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return lo
    if x != x:
        return lo
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _coerce_float(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _rows(signals: Any) -> list[dict[str, Any]]:
    if not isinstance(signals, list):
        return []
    return [s for s in signals if isinstance(s, dict)]


def _direction(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"up", "bull", "bullish", "long", "+", "1"}:
            return 1
        if text in {"down", "bear", "bearish", "short", "-", "-1"}:
            return -1
        return 0
    try:
        x = float(value)
    except (TypeError, ValueError):
        return 0
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


def compute_evidence_density(signals: Any) -> dict[str, Any]:
    rows = _rows(signals)
    if not rows:
        return _stamp({
            "evidence_density": 0.0,
            "signal_count": 0,
            "independent_source_count": 0,
            "mean_reliability": 0.0,
            "mean_evidence_strength": 0.0,
            "reasons": ["no_signals"],
        })
    reliabilities = [_clamp(s.get("reliability")) for s in rows]
    strengths = [_clamp(s.get("evidence_strength")) for s in rows]
    confirmations = [_clamp(s.get("market_confirmation")) for s in rows]
    contradictions = [_clamp(s.get("contradiction_score") or s.get("contradiction")) for s in rows]
    independence_scores = [_clamp(s.get("independence_score")) for s in rows]

    source_families = {_text(s.get("source_family") or s.get("source_type")) for s in rows}
    source_names = {_text(s.get("source_name")) for s in rows if _text(s.get("source_name"))}
    independent_sources = max(len(source_names), len([f for f in source_families if f]))

    mean = lambda xs: (sum(xs) / len(xs)) if xs else 0.0  # noqa: E731

    raw = (
        0.4 * mean(reliabilities)
        + 0.3 * mean(strengths)
        + 0.2 * mean(confirmations)
        + 0.1 * mean(independence_scores)
        - 0.3 * mean(contradictions)
    )
    # bonus for diversity of sources
    diversity_bonus = _clamp(independent_sources / max(len(rows), 1)) * 0.2
    density = _clamp(raw + diversity_bonus)

    return _stamp({
        "evidence_density": round(density, 4),
        "signal_count": len(rows),
        "independent_source_count": independent_sources,
        "mean_reliability": round(mean(reliabilities), 4),
        "mean_evidence_strength": round(mean(strengths), 4),
        "mean_market_confirmation": round(mean(confirmations), 4),
        "mean_contradiction": round(mean(contradictions), 4),
        "reasons": [],
    })


def compute_fusion_thesis_strength(signals: Any) -> dict[str, Any]:
    rows = _rows(signals)
    density = compute_evidence_density(rows)
    if density["signal_count"] == 0:
        return _stamp({
            "fusion_thesis_strength": 0.0,
            "evidence_density": 0.0,
            "signal_temperature": 0.0,
            "confinement_quality": 0.0,
            "time_durability": 0.0,
            "independence_score": 0.0,
            "signal_count": 0,
            "reasons": ["no_signals"],
        })

    intensities = [_clamp(s.get("intensity") or s.get("narrative_charge")) for s in rows]
    contradictions = [_clamp(s.get("contradiction_score") or s.get("contradiction")) for s in rows]
    durabilities = [_clamp(s.get("durability_score")) for s in rows]
    fresh = [_clamp(s.get("freshness_score")) for s in rows]
    independence_scores = [_clamp(s.get("independence_score")) for s in rows]
    echo_risks = [_clamp(s.get("echo_risk_score")) for s in rows]

    source_families = {_text(s.get("source_family") or s.get("source_type")) for s in rows}
    source_names = {_text(s.get("source_name")) for s in rows if _text(s.get("source_name"))}
    independent_sources = max(len(source_names), len([f for f in source_families if f]))

    mean = lambda xs: (sum(xs) / len(xs)) if xs else 0.0  # noqa: E731

    signal_temperature = _clamp(mean(intensities))
    confinement_quality = _clamp(1.0 - mean(contradictions) - 0.5 * mean(echo_risks))
    time_durability = _clamp(0.5 * mean(durabilities) + 0.5 * mean(fresh))
    structural_ratio = independent_sources / max(len(rows), 1)
    has_explicit_independence = any("independence_score" in s for s in rows)
    if has_explicit_independence:
        # When signals self-declare their independence, take the
        # *more conservative* of (declared mean, structural ratio).
        indep_score = _clamp(min(mean(independence_scores), structural_ratio))
    else:
        indep_score = _clamp(structural_ratio)

    raw_strength = (
        density["evidence_density"]
        * (0.5 + 0.5 * signal_temperature)
        * (0.5 + 0.5 * confinement_quality)
        * (0.5 + 0.5 * time_durability)
        * (0.5 + 0.5 * indep_score)
    )
    fusion_strength = _clamp(raw_strength)

    return _stamp({
        "fusion_thesis_strength": round(fusion_strength, 4),
        "evidence_density": density["evidence_density"],
        "signal_temperature": round(signal_temperature, 4),
        "confinement_quality": round(confinement_quality, 4),
        "time_durability": round(time_durability, 4),
        "independence_score": round(indep_score, 4),
        "signal_count": density["signal_count"],
        "independent_source_count": independent_sources,
        "reasons": [],
    })


def classify_fusion_candidate(signals: Any) -> dict[str, Any]:
    rows = _rows(signals)
    strength_payload = compute_fusion_thesis_strength(rows)
    signal_count = strength_payload["signal_count"]

    if signal_count == 0:
        recommendation = "watch"
        validity = "insufficient_data"
        candidate = False
        reasons = ["no_signals"]
    else:
        indep = strength_payload["independence_score"]
        confinement = strength_payload["confinement_quality"]
        temperature = strength_payload["signal_temperature"]
        density = strength_payload["evidence_density"]
        durability = strength_payload["time_durability"]
        directions = [_direction(s.get("direction")) for s in rows]
        same_direction = (
            len(directions) >= 2
            and all(d == directions[0] for d in directions if d != 0)
            and any(d != 0 for d in directions)
        )

        reasons = []
        if signal_count >= 2 and indep < 0.3:
            validity = "echo_not_fusion"
            candidate = False
            recommendation = "require_independence"
            reasons.append("low_source_independence")
        elif temperature >= 0.7 and confinement <= 0.3:
            validity = "overheated_uncontained"
            candidate = False
            recommendation = "cool_down"
            reasons.append("high_heat_low_containment")
        elif durability < 0.2 and signal_count >= 2:
            validity = "weak_fusion"
            candidate = False
            recommendation = "watch"
            reasons.append("low_durability")
        elif (
            signal_count >= 2
            and indep >= 0.5
            and density >= 0.4
            and confinement >= 0.4
            and same_direction
        ):
            validity = "valid_fusion"
            candidate = True
            recommendation = "review_candidate"
            reasons.append("independent_aligned_evidence")
        elif signal_count >= 2 and indep >= 0.3:
            validity = "weak_fusion"
            candidate = False
            recommendation = "watch"
            reasons.append("partial_evidence_or_alignment")
        else:
            validity = "insufficient_data"
            candidate = False
            recommendation = "watch"
            reasons.append("insufficient_signals")

    return _stamp({
        "fusion_candidate": candidate,
        "fusion_validity": validity,
        "fusion_thesis_strength": strength_payload["fusion_thesis_strength"],
        "evidence_density": strength_payload["evidence_density"],
        "signal_temperature": strength_payload["signal_temperature"],
        "confinement_quality": strength_payload["confinement_quality"],
        "time_durability": strength_payload["time_durability"],
        "independence_score": strength_payload["independence_score"],
        "signal_count": signal_count,
        "independent_source_count": strength_payload.get("independent_source_count", 0),
        "operator_action": recommendation,
        "recommendation": recommendation,
        "reasons": reasons,
    })


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "SAFETY_STAMPS",
    "FUSION_VALIDITIES",
    "compute_evidence_density",
    "compute_fusion_thesis_strength",
    "classify_fusion_candidate",
]
