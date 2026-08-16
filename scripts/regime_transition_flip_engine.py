"""Regime-transition sprint — narrative instability + regime-flip engine.

The Dzhanibekov layer, used strictly as a regime-instability ABSTRACTION
(reflection §1, failure 1).  It answers TWO deliberately distinct
questions with two distinct outputs:

    NarrativeInstabilityScore (0–100)  — is the current consensus fragile?
    RegimeFlipProbability (EXPERIMENTAL) — is a transition actually likely?

Instability ≠ flip: a fragile regime can persist; the flip probability is
only computed when instability AND threshold pressure corroborate, is
squashed through a conservative logistic, carries a wide uncertainty band
and an UNCALIBRATED stamp.  It must never gate real-money anything.

Inputs are the OUTPUTS of the other regime-transition modules plus the
existing ``narrative_structure_divergence`` (NSD) score — no raw feeds
are re-interpreted here, which keeps module responsibilities disjoint.
"""
from __future__ import annotations

import math
from typing import Any

from scripts.regime_transition_titration_engine import (
    TP_CRITICAL_ZONE,
    TP_ELEVATED,
)

ADVISORY_STATUS = "ADVISORY_ONLY"
REAL_MONEY = "PROHIBITED"
CALIBRATION_STATUS = "UNCALIBRATED_DEFAULTS"
OK = "OK"
UNKNOWN = "UNKNOWN"

# Narrative regime states (reflection §5).
NARRATIVE_OLD = "OLD"
NARRATIVE_TRANSITION = "TRANSITION"
NARRATIVE_NEW = "NEW"

# Instability component weights (documented heuristics; sum 1.0).
_NIS_WEIGHTS = {
    "cross_market_divergence": 0.20,   # |P_K − P_P| (CES-gated upstream)
    "divergence_velocity": 0.15,       # widening gap > static gap
    "probability_acceleration": 0.10,  # consensus break emerging
    "narrative_structure_divergence": 0.20,  # |NSD| — narrative vs structure gap
    "threshold_pressure": 0.20,        # titration says system is loaded
    "model_disagreement": 0.10,        # cross-model variance (existing module)
    "catalyst_proximity": 0.05,        # near-dated catalyst amplifies fragility
}
_MIN_NIS_COVERAGE = 0.50
_FLIP_INSTABILITY_FLOOR = 55.0   # below this, flip probability not computed
_FLIP_UNCERTAINTY_BAND = 0.25    # ± band; honest width for an uncalibrated model


def narrative_instability_score(
    *,
    divergence_latest: float | None = None,
    divergence_velocity: float | None = None,
    probability_acceleration: float | None = None,
    nsd_score: float | None = None,            # from narrative_structure_divergence
    threshold_pressure_band: str | None = None,  # from titration engine
    model_disagreement_0_1: float | None = None,
    catalyst_days_until: int | None = None,
) -> dict[str, Any]:
    """NIS ∈ [0, 100], coverage-aware.  Fragility measure ONLY."""
    credits: dict[str, float | None] = {
        "cross_market_divergence": None if divergence_latest is None
        else min(1.0, max(0.0, divergence_latest) / 0.25),
        "divergence_velocity": None if divergence_velocity is None
        else min(1.0, max(0.0, divergence_velocity) / 0.05),
        "probability_acceleration": None if probability_acceleration is None
        else min(1.0, abs(probability_acceleration) / 0.02),
        "narrative_structure_divergence": None if nsd_score is None
        else min(1.0, abs(nsd_score)),
        "threshold_pressure": {
            TP_CRITICAL_ZONE: 1.0, TP_ELEVATED: 0.6, "LOW": 0.1,
        }.get(threshold_pressure_band) if threshold_pressure_band else None,
        "model_disagreement": None if model_disagreement_0_1 is None
        else max(0.0, min(1.0, model_disagreement_0_1)),
        "catalyst_proximity": None if catalyst_days_until is None
        else (1.0 if catalyst_days_until <= 7
              else max(0.0, 1.0 - (catalyst_days_until - 7) / 60.0)),
    }
    known_w = sum(_NIS_WEIGHTS[k] for k, v in credits.items() if v is not None)
    coverage = known_w / sum(_NIS_WEIGHTS.values())
    base = {"calibration_status": CALIBRATION_STATUS,
            "safety": {"advisory_status": ADVISORY_STATUS,
                       "real_money": REAL_MONEY}}
    if coverage < _MIN_NIS_COVERAGE:
        return {**base, "status": "INSUFFICIENT_COMPONENTS",
                "instability_score": None,
                "component_coverage": round(coverage, 4),
                "missing_components": sorted(
                    k for k, v in credits.items() if v is None)}
    raw = sum(_NIS_WEIGHTS[k] * v for k, v in credits.items() if v is not None)
    nis = round(100.0 * raw / known_w, 2)
    return {**base, "status": OK, "instability_score": nis,
            "component_coverage": round(coverage, 4),
            "component_credits": {k: (None if v is None else round(v, 4))
                                  for k, v in credits.items()},
            "missing_components": sorted(k for k, v in credits.items()
                                         if v is None)}


def regime_flip_probability(
    *,
    instability: dict[str, Any],
    threshold_pressure_band: str | None,
    iir_band: str | None = None,
) -> dict[str, Any]:
    """EXPERIMENTAL flip probability — distinct from instability.

    Computed only when instability is high AND threshold pressure
    corroborates; otherwise honestly reports NOT_COMPUTED with the reason.
    Output is a logistic squash of corroborating factors with a wide
    uncertainty band; it is a research prior, never a trade input.
    """
    base = {"experimental": True, "calibration_status": CALIBRATION_STATUS,
            "signal_class": "RESEARCH_PRIOR_ONLY",
            "safety": {"advisory_status": ADVISORY_STATUS,
                       "real_money": REAL_MONEY}}
    nis = instability.get("instability_score")
    if nis is None:
        return {**base, "status": "NOT_COMPUTED",
                "reason": "instability unknown", "flip_probability": None}
    if nis < _FLIP_INSTABILITY_FLOOR:
        return {**base, "status": "NOT_COMPUTED",
                "reason": f"instability {nis} below floor "
                          f"{_FLIP_INSTABILITY_FLOOR} — fragile != flipping",
                "flip_probability": None}
    if threshold_pressure_band not in (TP_ELEVATED, TP_CRITICAL_ZONE):
        return {**base, "status": "NOT_COMPUTED",
                "reason": "threshold pressure does not corroborate "
                          "(instability without accumulated evidence)",
                "flip_probability": None}
    x = (nis - _FLIP_INSTABILITY_FLOOR) / 45.0                # 0..1
    x += 0.3 if threshold_pressure_band == TP_CRITICAL_ZONE else 0.0
    x += {"DESTABILIZING": 0.15, "REGIME_THREAT": 0.3}.get(iir_band or "", 0.0)
    p = 1.0 / (1.0 + math.exp(-3.0 * (x - 0.5)))
    lo = max(0.0, p - _FLIP_UNCERTAINTY_BAND)
    hi = min(1.0, p + _FLIP_UNCERTAINTY_BAND)
    return {**base, "status": OK, "flip_probability": round(p, 4),
            "uncertainty_band": [round(lo, 4), round(hi, 4)],
            "inputs": {"instability": nis,
                       "threshold_pressure_band": threshold_pressure_band,
                       "iir_band": iir_band}}


def classify_narrative_state(*, instability: dict[str, Any],
                             flip: dict[str, Any],
                             new_regime_evidence_share: float | None,
                             ) -> dict[str, Any]:
    """OLD / TRANSITION / NEW label (reflection §5).

    ``new_regime_evidence_share`` ∈ [0, 1] is the share of accumulated
    (titration) evidence supporting the NEW regime; None → UNKNOWN.
    """
    if new_regime_evidence_share is None:
        return {"status": UNKNOWN, "narrative_state": None,
                "reason": "no evidence share available"}
    nis = instability.get("instability_score") or 0.0
    share = max(0.0, min(1.0, new_regime_evidence_share))
    if share >= 0.75 and nis < _FLIP_INSTABILITY_FLOOR:
        state = NARRATIVE_NEW
    elif share <= 0.25 and nis < _FLIP_INSTABILITY_FLOOR:
        state = NARRATIVE_OLD
    else:
        state = NARRATIVE_TRANSITION
    return {"status": OK, "narrative_state": state,
            "new_regime_evidence_share": round(share, 4),
            "instability_score": nis,
            "flip_status": flip.get("status")}
