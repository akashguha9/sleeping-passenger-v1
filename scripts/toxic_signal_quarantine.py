"""
Toxic signal quarantine diagnostic.

Purpose
-------
Decide whether a signal should be promoted to the human-review queue, held
for monitoring, quarantined, or blocked from promotion altogether. The
decision is **derived**, not destructive: the underlying signal is never
deleted, and the diagnostic never grants any form of execution permission.

It answers one question:

    "Is this signal contaminated enough that promoting it without an
     explicit operator override would be a process violation?"

Formula
-------

    Contamination Score =
          w1 × Unreliability
        + w2 × Contradiction
        + w3 × Emotional_Manipulation
        + w4 × Recycled_Narrative
        + w5 × Hallucination_Risk
        + w6 × Fallback_or_Noncanonical_Risk
        + w7 × Operator_Desire_Distortion
        + w8 × AI_Invalidity

All inputs are clipped to [0, 1] and the weighted sum is clipped to [0, 1].
Bucket thresholds determine ``toxic_quarantine_state``:

    contamination < 0.20  -> clean
    contamination < 0.40  -> monitor
    contamination < 0.70  -> quarantine
    contamination >= 0.70 -> block_from_promotion

Safety contract (every output)
------------------------------

    advisory_status        = "ADVISORY_ONLY"
    execution_gate         = "LOCKED"
    broker_api_called      = False
    ai_execution_count     = 0
    execution_permission   = False
    can_execute            = False

Public API
----------
- ``classify_toxic_signal(signal)`` -> dict
- ``CONTAMINATION_WEIGHTS`` -> dict[str, float]
- ``QUARANTINE_THRESHOLDS`` -> dict[str, float]
"""
from __future__ import annotations

from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_GATE_LOCKED = "LOCKED"


# Default weights. Tuned so that any *single* maxed-out toxic dimension
# (contradiction, AI invalidity, etc.) is enough to escape the ``clean``
# band, but no single dimension can single-handedly trigger
# ``block_from_promotion``. The operator can override per-call.
#
# Weights sum > 1.0 by design — the final score is clipped to [0, 1] and the
# bucket thresholds are calibrated against that clipped scale. The intent is
# "if multiple toxic dimensions co-occur, escalate hard".
CONTAMINATION_WEIGHTS: dict[str, float] = {
    "unreliability": 0.22,
    "contradiction": 0.25,
    "emotional_manipulation": 0.15,
    "recycled_narrative": 0.15,
    "hallucination_risk": 0.18,
    "fallback_or_noncanonical_risk": 0.18,
    "operator_desire_distortion": 0.10,
    "ai_invalidity": 0.20,
}


QUARANTINE_THRESHOLDS: dict[str, float] = {
    "monitor": 0.15,
    "quarantine": 0.35,
    "block_from_promotion": 0.65,
}


_SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": ADVISORY_STATUS,
    "execution_gate": EXECUTION_GATE_LOCKED,
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
    "may_inform_human_review": True,
    "may_execute": False,
    "may_call_broker": False,
}


def _clip01(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    if n != n:  # NaN
        return default
    if n < 0.0:
        return 0.0
    if n > 1.0:
        return 1.0
    return n


def _derive_unreliability(signal: dict[str, Any]) -> float:
    if "source_reliability" in signal:
        return 1.0 - _clip01(signal["source_reliability"])
    if "source_reputation" in signal:
        return 1.0 - _clip01(signal["source_reputation"])
    if "reliability_score" in signal:
        return 1.0 - _clip01(signal["reliability_score"])
    return 0.0


def _derive_ai_invalidity(signal: dict[str, Any]) -> float:
    status = signal.get("ai_validation_status")
    if status == "invalid":
        return 1.0
    if status == "partial":
        return 0.5
    if status in {"valid", "not_applicable"}:
        return 0.0
    return 0.0


def _derive_fallback_risk(signal: dict[str, Any]) -> float:
    risk = 0.0
    if signal.get("fallback_used") is True:
        risk += 0.6
    truth_source = signal.get("truth_source")
    if truth_source and truth_source != "sqlite":
        risk += 0.3
    if signal.get("canonical") is False:
        risk += 0.2
    return min(1.0, risk)


def classify_toxic_signal(
    signal: Any,
    *,
    weights: dict[str, float] | None = None,
    thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Score a signal for contamination risk and classify its quarantine state.

    Parameters
    ----------
    signal : dict
        A signal-like mapping. Known fields:

        - ``source_reliability`` / ``source_reputation`` / ``reliability_score``
        - ``contradiction_score``
        - ``ai_validation_status`` (``valid``/``partial``/``invalid``/``not_applicable``)
        - ``hallucination_risk``
        - ``recycled_narrative_risk``
        - ``emotional_manipulation_score``
        - ``operator_desire_distortion_score``
        - ``fallback_used`` (bool), ``truth_source`` (str), ``canonical`` (bool)

        Missing fields are treated as zero contamination, not as a failure.

    weights, thresholds : optional overrides.

    Returns
    -------
    dict
        ``contamination_score``, ``toxic_quarantine_state``,
        ``quarantine_reasons``, ``promotion_allowed``, ``component_scores``,
        plus the canonical advisory-only safety stamps.
    """
    if not isinstance(signal, dict):
        out = {
            "diagnostic": "toxic_signal_quarantine",
            "contamination_score": 1.0,
            "toxic_quarantine_state": "block_from_promotion",
            "quarantine_reasons": ["signal_not_a_dict"],
            "component_scores": {},
            "weights": dict(CONTAMINATION_WEIGHTS),
            "thresholds": dict(QUARANTINE_THRESHOLDS),
            "validation_status": "invalid",
            "promotion_allowed": False,
        }
        out.update(_SAFETY_STAMPS)
        return out

    w = dict(CONTAMINATION_WEIGHTS)
    if isinstance(weights, dict):
        for key, value in weights.items():
            if key in w:
                try:
                    w[key] = float(value)
                except (TypeError, ValueError):
                    continue

    t = dict(QUARANTINE_THRESHOLDS)
    if isinstance(thresholds, dict):
        for key, value in thresholds.items():
            if key in t:
                try:
                    t[key] = float(value)
                except (TypeError, ValueError):
                    continue

    components: dict[str, float] = {
        "unreliability": _derive_unreliability(signal),
        "contradiction": _clip01(signal.get("contradiction_score")),
        "emotional_manipulation": _clip01(signal.get("emotional_manipulation_score")),
        "recycled_narrative": _clip01(signal.get("recycled_narrative_risk")),
        "hallucination_risk": _clip01(signal.get("hallucination_risk")),
        "fallback_or_noncanonical_risk": _derive_fallback_risk(signal),
        "operator_desire_distortion": _clip01(
            signal.get("operator_desire_distortion_score")
        ),
        "ai_invalidity": _derive_ai_invalidity(signal),
    }

    score = 0.0
    for key, comp in components.items():
        score += w.get(key, 0.0) * comp
    score = max(0.0, min(1.0, score))

    if score >= t["block_from_promotion"]:
        state = "block_from_promotion"
    elif score >= t["quarantine"]:
        state = "quarantine"
    elif score >= t["monitor"]:
        state = "monitor"
    else:
        state = "clean"

    reasons: list[str] = []
    for key, comp in components.items():
        if comp >= 0.5:
            reasons.append(f"high_{key}")
    if signal.get("ai_validation_status") == "invalid":
        reasons.append("ai_validation_invalid")
    if signal.get("fallback_used") is True:
        reasons.append("fallback_used_for_signal_source")

    promotion_allowed = state in {"clean", "monitor"}

    out = {
        "diagnostic": "toxic_signal_quarantine",
        "contamination_score": round(score, 6),
        "toxic_quarantine_state": state,
        "quarantine_reasons": reasons,
        "component_scores": {k: round(v, 6) for k, v in components.items()},
        "weights": w,
        "thresholds": t,
        "validation_status": "valid",
        "promotion_allowed": promotion_allowed,
    }
    out.update(_SAFETY_STAMPS)
    return out


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "CONTAMINATION_WEIGHTS",
    "QUARANTINE_THRESHOLDS",
    "classify_toxic_signal",
]
