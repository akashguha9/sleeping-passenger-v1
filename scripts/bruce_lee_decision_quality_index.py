"""Bruce Lee Decision Quality Index (BLDQI) — the synthesis score.

This is the single index that fuses the Jeet Kune Do virtues, the survival
calculus, and the operator/distortion penalties into one advisory decision
quality number with a state that has consequence.

BLDQI (0–10)::

    BLDQI = 0.12*Interception + 0.10*Directness + 0.10*Adaptability
            + 0.10*Economy + 0.12*RealityConfirmation + 0.10*SignalEfficiency
            + 0.08*BrokenRhythm + 0.08*AntiDogma + 0.10*SurvivalUtility
            - 0.10*OperatorHeat - 0.10*DiabloRisk

Component sub-formulas (all normalised to 0–10):

    SignalEfficiency = (EV * Confidence * SurvivalQuality)
                       / (Assumptions + DataFragility + OperationalComplexity + eps)
        — economy of motion: edge per unit of fragility/complexity.

    BrokenRhythm = 10 * (0.30*Dislocation + 0.25*DelayedConsensus
                         + 0.20*AsymmetricSetup + 0.15*VolatilityCompression
                         + 0.10*NarrativeMismatch)
        — the half-beat: act where the market's timing is broken.

    AntiDogma ("no way as way") = 10 * (0.40*Adaptability + 0.30*InvalidationClarity
                         + 0.30*(1 - SingleSourceDependence))
        — refusing to be locked into one fixed style/source.

    SurvivalUtility = 10 * (0.20*ReturnPotential + 0.30*SurvivalQuality
                       + 0.25*FeedbackValue + 0.15*InvalidationClarity
                       + 0.10*Liquidity - 0.20*ChaosRisk)
        — survival and feedback value outrank raw return.

State consequence (mirrors JKD; DIABLO overrides on high heat/diablo risk):

    bldqi >= 8.0  -> AVENTADOR_CANDIDATE / HUMAN_REVIEW_REQUIRED
    6.5 <= < 8.0  -> MURCIELAGO_WATCH    / WATCHLIST_ONLY
    5.0 <= < 6.5  -> MIURA_MONITOR       / MONITOR_ONLY
    < 5.0         -> WAIT_OR_AVOID       / NO_NEW_RISK_RECOMMENDED
    high heat OR high diablo risk -> DIABLO_NO_NEW_RISK / RECONCILE_OR_WAIT

Safety
------
Pure functions.  No DB, no network, no broker calls.  Strongest verdict is
HUMAN_REVIEW_REQUIRED.  Advisory-only stamps on every output.
"""
from __future__ import annotations

import argparse
import json
from typing import Any

try:
    from scripts import advisory_contract as _contract
    from scripts.jkd_decision_discipline import (
        _state_for,
        STATE_DIABLO,
        CONSTRAINT_RECONCILE,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]
    from jkd_decision_discipline import (  # type: ignore[no-redef]
        _state_for,
        STATE_DIABLO,
        CONSTRAINT_RECONCILE,
    )

EPS = 1e-6

# BLDQI weights.
W = {
    "interception": 0.12,
    "directness": 0.10,
    "adaptability": 0.10,
    "economy": 0.10,
    "reality_confirmation": 0.12,
    "signal_efficiency": 0.10,
    "broken_rhythm": 0.08,
    "anti_dogma": 0.08,
    "survival_utility": 0.10,
    "operator_heat": 0.10,   # penalty
    "diablo_risk": 0.10,     # penalty
}

# High-heat / high-diablo thresholds (0–10).
HEAT_HIGH = 7.0
DIABLO_RISK_HIGH = 7.0

ADVISORY_DISCLAIMER = (
    "Advisory-only Bruce Lee decision-quality index. The strongest verdict is "
    "HUMAN_REVIEW_REQUIRED; no state authorises or performs a broker action."
)


def _clamp(value: Any, lo: float = 0.0, hi: float = 10.0) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, v))


def _clamp01(value: Any) -> float:
    return _clamp(value, 0.0, 1.0)


def compute_signal_efficiency(
    *,
    expected_value: float,
    confidence: float,
    survival_quality: float,
    assumptions: float,
    data_fragility: float,
    operational_complexity: float,
) -> float:
    """Edge per unit of fragility/complexity, normalised to 0–10.

    ``expected_value`` may be on any non-negative scale; ``confidence`` and
    ``survival_quality`` are 0–1; the denominator terms are non-negative
    counts/levels.  The raw ratio is squashed to 0–10 with a saturating curve
    so a clean low-assumption setup scores high and an assumption-stacked one
    scores low.
    """
    ev = max(0.0, float(expected_value or 0.0))
    conf = _clamp01(confidence)
    surv = _clamp01(survival_quality)
    denom = (
        max(0.0, float(assumptions or 0.0))
        + max(0.0, float(data_fragility or 0.0))
        + max(0.0, float(operational_complexity or 0.0))
        + EPS
    )
    raw = (ev * conf * surv) / denom
    # Saturating map: raw of ~1.0 -> 5.0, large raw -> approaches 10.
    score = 10.0 * (raw / (raw + 1.0))
    return round(_clamp(score), 4)


def compute_broken_rhythm(
    *,
    dislocation: float,
    delayed_consensus: float,
    asymmetric_setup: float,
    volatility_compression: float,
    narrative_mismatch: float,
) -> float:
    """Broken-rhythm score (0–10).  Inputs 0–1."""
    score = 10.0 * (
        0.30 * _clamp01(dislocation)
        + 0.25 * _clamp01(delayed_consensus)
        + 0.20 * _clamp01(asymmetric_setup)
        + 0.15 * _clamp01(volatility_compression)
        + 0.10 * _clamp01(narrative_mismatch)
    )
    return round(_clamp(score), 4)


def compute_anti_dogma(
    *,
    adaptability: float,
    invalidation_clarity: float,
    single_source_dependence: float,
) -> float:
    """Anti-dogma score (0–10) — "using no way as way".

    ``adaptability`` is 0–10; ``invalidation_clarity`` and
    ``single_source_dependence`` are 0–1.  Rigidity (locked into one source,
    no invalidation) tanks the score.
    """
    adapt01 = _clamp(adaptability) / 10.0
    score = 10.0 * (
        0.40 * adapt01
        + 0.30 * _clamp01(invalidation_clarity)
        + 0.30 * (1.0 - _clamp01(single_source_dependence))
    )
    return round(_clamp(score), 4)


def compute_survival_utility(
    *,
    return_potential: float,
    survival_quality: float,
    feedback_value: float,
    invalidation_clarity: float,
    liquidity: float,
    chaos_risk: float,
) -> float:
    """Survival-utility score (0–10).  Inputs 0–1.

    Survival and feedback value are weighted above raw return; chaos risk
    subtracts.
    """
    raw01 = (
        0.20 * _clamp01(return_potential)
        + 0.30 * _clamp01(survival_quality)
        + 0.25 * _clamp01(feedback_value)
        + 0.15 * _clamp01(invalidation_clarity)
        + 0.10 * _clamp01(liquidity)
        - 0.20 * _clamp01(chaos_risk)
    )
    return round(_clamp(10.0 * raw01), 4)


def compute_bldqi(
    *,
    interception: float,
    directness: float,
    adaptability: float,
    economy: float,
    reality_confirmation: float,
    signal_efficiency: float,
    broken_rhythm: float,
    anti_dogma: float,
    survival_utility: float,
    operator_heat: float,
    diablo_risk: float,
) -> dict[str, Any]:
    """Fuse all components (each 0–10) into the BLDQI score and advisory state."""
    comps = {
        "interception": _clamp(interception),
        "directness": _clamp(directness),
        "adaptability": _clamp(adaptability),
        "economy": _clamp(economy),
        "reality_confirmation": _clamp(reality_confirmation),
        "signal_efficiency": _clamp(signal_efficiency),
        "broken_rhythm": _clamp(broken_rhythm),
        "anti_dogma": _clamp(anti_dogma),
        "survival_utility": _clamp(survival_utility),
    }
    heat = _clamp(operator_heat)
    diablo = _clamp(diablo_risk)

    raw = (
        sum(W[k] * v for k, v in comps.items())
        - W["operator_heat"] * heat
        - W["diablo_risk"] * diablo
    )
    bldqi = _clamp(raw)

    # State: DIABLO override on high heat / high diablo risk.
    if heat >= HEAT_HIGH or diablo >= DIABLO_RISK_HIGH:
        state, constraint = STATE_DIABLO, CONSTRAINT_RECONCILE
    else:
        state, constraint = _state_for(bldqi, 0.0, 0.0)

    dominant_weakness = min(comps, key=comps.get)
    if max(heat, diablo) >= 6.0:
        dominant_weakness = "operator_heat" if heat >= diablo else "diablo_risk"

    # Moltbook feedback is required whenever the decision is non-trivial: any
    # promotion candidate or any DIABLO state must produce a logged lesson.
    moltbook_feedback_required = state in (STATE_DIABLO, "AVENTADOR_CANDIDATE")

    out: dict[str, Any] = {
        "bldqi_score": round(bldqi, 4),
        "component_scores": {k: round(v, 4) for k, v in comps.items()},
        "operator_heat_penalty": round(heat, 4),
        "diablo_risk_penalty": round(diablo, 4),
        "dominant_weakness": dominant_weakness,
        "state_recommendation": state,
        "action_constraint": constraint,
        "moltbook_feedback_required": bool(moltbook_feedback_required),
        "advisory_disclaimer": ADVISORY_DISCLAIMER,
        "human_review_required": True,
    }
    out.update(_contract.advisory_safety_stamps())
    return out


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bruce_lee_decision_quality_index.py",
        description=(
            "Advisory-only Bruce Lee decision-quality index. Pure compute, no "
            "broker calls. Strongest verdict is HUMAN_REVIEW_REQUIRED."
        ),
    )
    p.add_argument("--demo", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def _demo() -> dict[str, Any]:
    se = compute_signal_efficiency(
        expected_value=2.0, confidence=0.7, survival_quality=0.8,
        assumptions=1.0, data_fragility=0.5, operational_complexity=0.5,
    )
    br = compute_broken_rhythm(
        dislocation=0.7, delayed_consensus=0.6, asymmetric_setup=0.6,
        volatility_compression=0.4, narrative_mismatch=0.3,
    )
    ad = compute_anti_dogma(
        adaptability=6.5, invalidation_clarity=0.7, single_source_dependence=0.3,
    )
    su = compute_survival_utility(
        return_potential=0.6, survival_quality=0.8, feedback_value=0.7,
        invalidation_clarity=0.7, liquidity=0.7, chaos_risk=0.2,
    )
    return compute_bldqi(
        interception=8.0, directness=7.5, adaptability=6.5, economy=7.0,
        reality_confirmation=8.0, signal_efficiency=se, broken_rhythm=br,
        anti_dogma=ad, survival_utility=su, operator_heat=1.5, diablo_risk=1.0,
    )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    rep = _demo()
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
    else:
        print("Bruce Lee Decision Quality Index (advisory-only)")
        print("=" * 48)
        print(f"  BLDQI score        : {rep['bldqi_score']} / 10")
        print(f"  state              : {rep['state_recommendation']}")
        print(f"  action constraint  : {rep['action_constraint']}")
        print(f"  dominant weakness  : {rep['dominant_weakness']}")
        print(f"  moltbook feedback  : {rep['moltbook_feedback_required']}")
        print(f"\n  {rep['advisory_disclaimer']}")
    return 0


__all__ = [
    "compute_signal_efficiency",
    "compute_broken_rhythm",
    "compute_anti_dogma",
    "compute_survival_utility",
    "compute_bldqi",
    "ADVISORY_DISCLAIMER",
]


if __name__ == "__main__":
    raise SystemExit(main())
