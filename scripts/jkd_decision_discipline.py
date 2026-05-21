"""JKD Decision Discipline — Jeet Kune Do as decision architecture.

Bruce Lee is not a theme here; he is a scoring function.  This module turns
the Jeet Kune Do reflection into a single advisory discipline score with a
*state that has consequence* — a state without consequence is decorative
complexity, which JKD itself forbids (economy of motion).

The score blends six virtues and three penalties::

    JKD = 0.22*I + 0.16*D + 0.16*A + 0.14*E + 0.18*R
          - 0.10*N - 0.12*G - 0.18*C

    I = Interception          (early belief-shift detection — see compute_interception)
    D = Directness            (thesis clarity / invalidation — see compute_directness)
    A = Adaptability          (be water: regime fit)
    E = Economy of motion     (useful signal / ornamentation ratio)
    R = Reality confirmation  (price/volume/filings vs. pointers)
    N = Noise                 (headline churn without confirmation)
    G = Greed / ego / operator emotional distortion (operator heat)
    C = Chaos risk            (regime instability / negative reflexivity)

All nine inputs are on a 0–10 scale.  The weighted sum is clamped to [0, 10].
Note the positive ceiling is 8.6 by construction (0.86 * 10) — perfection is
deliberately unclaimable; the highest-discipline signal still leaves room to
adapt.  This is on purpose.

State mapping (the consequence):

    jkd >= 8.0 and chaos low and operator-heat low : AVENTADOR_CANDIDATE / HUMAN_REVIEW_REQUIRED
    6.5 <= jkd < 8.0                               : MURCIELAGO_WATCH    / WATCHLIST_ONLY
    5.0 <= jkd < 6.5                               : MIURA_MONITOR       / MONITOR_ONLY
    jkd < 5.0                                      : WAIT_OR_AVOID       / NO_NEW_RISK_RECOMMENDED
    chaos high OR operator-heat high               : DIABLO_NO_NEW_RISK  / RECONCILE_OR_WAIT (overrides)

Additionally, the "a signal that cannot be invalidated is useless" rule: when
directness is low (weak invalidation clarity), the JKD score is *capped* and
the constraint is tightened — no AVENTADOR promotion on an un-invalidatable
thesis.

Safety
------
Pure functions.  No DB, no network, no broker calls, no execution.  Every
output carries the advisory-only stamps and ``human_review_required``.  No
state this module emits is an execution instruction; the strongest possible
verdict is HUMAN_REVIEW_REQUIRED.

Usage
-----
    python scripts/jkd_decision_discipline.py --interception 8 --directness 7 \
        --adaptability 6 --economy 7 --reality 8 --noise 2 --greed 1 --chaos 1
    python scripts/jkd_decision_discipline.py --demo --json
"""
from __future__ import annotations

import argparse
import json
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

# JKD virtue / penalty weights.  Positive weights sum to 0.86; penalty weights
# sum to 0.40.  Kept as named constants so docs/tests cannot drift from code.
W_INTERCEPTION = 0.22
W_DIRECTNESS = 0.16
W_ADAPTABILITY = 0.16
W_ECONOMY = 0.14
W_REALITY = 0.18
W_NOISE = 0.10
W_GREED = 0.12
W_CHAOS = 0.18

# Thresholds for the chaos / operator-heat override (0–10 scale).
CHAOS_HIGH = 7.0
OPERATOR_HEAT_HIGH = 7.0
# Directness floor below which the "un-invalidatable thesis" cap applies.
DIRECTNESS_FLOOR = 4.0
# JKD ceiling imposed when directness is below the floor.
LOW_DIRECTNESS_CAP = 6.0

# Advisory states (consequence).  Lamborghini naming matches the existing
# AVENTADOR/MURCIELAGO/DIABLO vocabulary in runtime_common.
STATE_AVENTADOR = "AVENTADOR_CANDIDATE"
STATE_MURCIELAGO = "MURCIELAGO_WATCH"
STATE_MIURA = "MIURA_MONITOR"
STATE_WAIT = "WAIT_OR_AVOID"
STATE_DIABLO = "DIABLO_NO_NEW_RISK"

# Action constraints (all advisory; none is an execution instruction).
CONSTRAINT_HUMAN_REVIEW = "HUMAN_REVIEW_REQUIRED"
CONSTRAINT_WATCHLIST = "WATCHLIST_ONLY"
CONSTRAINT_MONITOR = "MONITOR_ONLY"
CONSTRAINT_NO_NEW_RISK = "NO_NEW_RISK_RECOMMENDED"
CONSTRAINT_RECONCILE = "RECONCILE_OR_WAIT"

ADVISORY_DISCLAIMER = (
    "Advisory-only JKD decision-discipline score. The strongest verdict is "
    "HUMAN_REVIEW_REQUIRED; no state authorises or performs a broker action."
)


def _clamp(value: float, lo: float = 0.0, hi: float = 10.0) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, v))


def compute_interception(
    price_structure_shift: float,
    narrative_acceleration: float,
    volume_confirmation: float,
    consensus_delay: float,
) -> dict[str, Any]:
    """Intercepting fist — early belief-shift detection (Task B2).

    I = 10 * (0.35*P_s + 0.25*N_a + 0.20*V_c + 0.20*C_d)

    Inputs are 0–1.  High acceleration + delayed consensus raises interception;
    high headline count without volume confirmation does not.  Low volume
    reduces interception.  This is an *early warning*, never an execution
    trigger.
    """
    p_s = _clamp(price_structure_shift, 0.0, 1.0)
    n_a = _clamp(narrative_acceleration, 0.0, 1.0)
    v_c = _clamp(volume_confirmation, 0.0, 1.0)
    c_d = _clamp(consensus_delay, 0.0, 1.0)
    score = 10.0 * (0.35 * p_s + 0.25 * n_a + 0.20 * v_c + 0.20 * c_d)
    # False-positive warning: loud narrative acceleration with no volume
    # behind it is the classic head-fake.
    false_positive = n_a >= 0.6 and v_c <= 0.3
    return {
        "interception_score": round(score, 4),
        "price_structure_shift": p_s,
        "narrative_acceleration": n_a,
        "volume_confirmation": v_c,
        "consensus_delay": c_d,
        "false_positive_warning": bool(false_positive),
        "human_review_required": True,
        **_contract.advisory_safety_stamps(),
    }


def compute_directness(
    invalidation_clarity: float,
    thesis_specificity: float,
    source_specificity: float,
    time_horizon_clarity: float,
    risk_reward_clarity: float,
) -> dict[str, Any]:
    """Directness — thesis clarity (Task B3).

    D = 10 * (0.30*invalidation + 0.25*specificity + 0.20*source
              + 0.15*time_horizon + 0.10*risk_reward)

    Inputs are 0–1.  Rule: a signal that cannot be invalidated is useless, so
    ``invalidation_clarity`` carries the most weight and gates promotion
    downstream in :func:`compute_jkd`.
    """
    inv = _clamp(invalidation_clarity, 0.0, 1.0)
    spec = _clamp(thesis_specificity, 0.0, 1.0)
    src = _clamp(source_specificity, 0.0, 1.0)
    horizon = _clamp(time_horizon_clarity, 0.0, 1.0)
    rr = _clamp(risk_reward_clarity, 0.0, 1.0)
    score = 10.0 * (0.30 * inv + 0.25 * spec + 0.20 * src + 0.15 * horizon + 0.10 * rr)
    return {
        "directness_score": round(score, 4),
        "invalidation_clarity": inv,
        "thesis_specificity": spec,
        "source_specificity": src,
        "time_horizon_clarity": horizon,
        "risk_reward_clarity": rr,
        "human_review_required": True,
        **_contract.advisory_safety_stamps(),
    }


def _state_for(jkd: float, chaos: float, operator_heat: float) -> tuple[str, str]:
    """Map a JKD score (with chaos / heat overrides) to (state, constraint)."""
    if chaos >= CHAOS_HIGH or operator_heat >= OPERATOR_HEAT_HIGH:
        return STATE_DIABLO, CONSTRAINT_RECONCILE
    if jkd >= 8.0:
        return STATE_AVENTADOR, CONSTRAINT_HUMAN_REVIEW
    if jkd >= 6.5:
        return STATE_MURCIELAGO, CONSTRAINT_WATCHLIST
    if jkd >= 5.0:
        return STATE_MIURA, CONSTRAINT_MONITOR
    return STATE_WAIT, CONSTRAINT_NO_NEW_RISK


def compute_jkd(
    *,
    interception: float,
    directness: float,
    adaptability: float,
    economy: float,
    reality_confirmation: float,
    noise: float,
    greed_ego: float,
    chaos_risk: float,
) -> dict[str, Any]:
    """Compute the JKD decision-discipline score and its advisory state.

    All nine inputs are 0–10.  Returns the score, every component, the
    advisory state, the action constraint, and the advisory-only stamps.
    """
    i = _clamp(interception)
    d = _clamp(directness)
    a = _clamp(adaptability)
    e = _clamp(economy)
    r = _clamp(reality_confirmation)
    n = _clamp(noise)
    g = _clamp(greed_ego)
    c = _clamp(chaos_risk)

    raw = (
        W_INTERCEPTION * i
        + W_DIRECTNESS * d
        + W_ADAPTABILITY * a
        + W_ECONOMY * e
        + W_REALITY * r
        - W_NOISE * n
        - W_GREED * g
        - W_CHAOS * c
    )
    jkd = _clamp(raw)

    # "A signal that cannot be invalidated is useless." Cap the score when
    # directness (which is dominated by invalidation clarity) is too low, so
    # an un-invalidatable thesis can never reach AVENTADOR.
    invalidation_capped = False
    if d < DIRECTNESS_FLOOR and jkd > LOW_DIRECTNESS_CAP:
        jkd = LOW_DIRECTNESS_CAP
        invalidation_capped = True

    state, constraint = _state_for(jkd, c, g)

    # Identify the dominant weakness for the operator's eye.
    components = {
        "interception_score": i,
        "directness_score": d,
        "adaptability_score": a,
        "economy_score": e,
        "reality_confirmation_score": r,
    }
    penalties = {
        "noise_penalty": n,
        "operator_greed_ego_penalty": g,
        "chaos_risk_penalty": c,
    }
    dominant_weakness = min(components, key=components.get)
    if max(penalties.values()) >= 6.0:
        dominant_weakness = max(penalties, key=penalties.get)

    out: dict[str, Any] = {
        "jkd_score": round(jkd, 4),
        "interception_score": round(i, 4),
        "directness_score": round(d, 4),
        "adaptability_score": round(a, 4),
        "economy_score": round(e, 4),
        "reality_confirmation_score": round(r, 4),
        "noise_penalty": round(n, 4),
        "operator_greed_ego_penalty": round(g, 4),
        "chaos_risk_penalty": round(c, 4),
        "invalidation_capped": invalidation_capped,
        "dominant_weakness": dominant_weakness,
        "advisory_state": state,
        "action_constraint": constraint,
        "advisory_disclaimer": ADVISORY_DISCLAIMER,
        "human_review_required": True,
    }
    out.update(_contract.advisory_safety_stamps())
    return out


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jkd_decision_discipline.py",
        description=(
            "Advisory-only JKD decision-discipline score. Pure compute; no DB, "
            "no broker calls. Strongest verdict is HUMAN_REVIEW_REQUIRED."
        ),
    )
    for name in (
        "interception", "directness", "adaptability", "economy",
        "reality", "noise", "greed", "chaos",
    ):
        p.add_argument(f"--{name}", type=float, default=5.0)
    p.add_argument("--demo", action="store_true", help="Use a high-discipline demo input set.")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.demo:
        rep = compute_jkd(
            interception=8.0, directness=7.5, adaptability=6.5, economy=7.0,
            reality_confirmation=8.0, noise=2.0, greed_ego=1.0, chaos_risk=1.5,
        )
    else:
        rep = compute_jkd(
            interception=args.interception, directness=args.directness,
            adaptability=args.adaptability, economy=args.economy,
            reality_confirmation=args.reality, noise=args.noise,
            greed_ego=args.greed, chaos_risk=args.chaos,
        )
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
    else:
        print("JKD Decision Discipline (advisory-only)")
        print("=" * 40)
        print(f"  jkd score          : {rep['jkd_score']}")
        print(f"  advisory state     : {rep['advisory_state']}")
        print(f"  action constraint  : {rep['action_constraint']}")
        print(f"  dominant weakness  : {rep['dominant_weakness']}")
        if rep["invalidation_capped"]:
            print("  note: capped — thesis lacks invalidation clarity (useless if uninvalidatable).")
        print(f"\n  {rep['advisory_disclaimer']}")
    return 0


__all__ = [
    "compute_interception",
    "compute_directness",
    "compute_jkd",
    "STATE_AVENTADOR",
    "STATE_MURCIELAGO",
    "STATE_MIURA",
    "STATE_WAIT",
    "STATE_DIABLO",
    "CONSTRAINT_HUMAN_REVIEW",
    "CONSTRAINT_WATCHLIST",
    "CONSTRAINT_MONITOR",
    "CONSTRAINT_NO_NEW_RISK",
    "CONSTRAINT_RECONCILE",
    "ADVISORY_DISCLAIMER",
]


if __name__ == "__main__":
    raise SystemExit(main())
