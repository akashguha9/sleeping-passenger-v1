"""Operator Emotional Content Gate — "emotional content, not anger".

Bruce Lee's instruction to the student was *emotional content* — focus and
intent — not *anger*.  Translated to operating discipline: operator emotion is
a measurable risk variable that distorts sizing and timing, and when it runs
hot the only safe advisory output is *no new risk*.

This is a decision-discipline risk variable ONLY.  It is not therapy, not a
diagnosis, and emits no medical language.  It measures distortion pressure on
the *decision*, never on the person.

Formula::

    OperatorHeat = 0.30*FOMO + 0.25*Revenge + 0.20*Overconfidence
                   + 0.15*Urgency + 0.10*IdentityAttachment

Inputs are 0–1; OperatorHeat is 0–1.

Consequence:

    OperatorHeat > 0.70  ->  DIABLO_NO_NEW_RISK
    EffectivePositionSize = BaseSize * (1 - OperatorHeat)   (sizing shrinks with heat)

Recommended actions are always NON-trading discipline actions: reconcile open
trades, review Moltbook, wait for a fresh signal, reduce size, no new risk.
There is no "execute", "buy", or "sell" path anywhere in this module.

Safety
------
Pure functions.  No DB, no network, no broker calls.  Advisory-only stamps on
every output.
"""
from __future__ import annotations

import argparse
import json
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

W_FOMO = 0.30
W_REVENGE = 0.25
W_OVERCONFIDENCE = 0.20
W_URGENCY = 0.15
W_IDENTITY = 0.10

DIABLO_HEAT_THRESHOLD = 0.70

# Heat buckets (lower bound inclusive).
HEAT_BUCKETS: tuple[tuple[float, str], ...] = (
    (0.70, "HOT"),
    (0.45, "ELEVATED"),
    (0.20, "WARM"),
    (0.0, "COOL"),
)

ADVISORY_DISCLAIMER = (
    "Advisory-only operator decision-discipline variable. Not therapy, not a "
    "diagnosis, no medical claim. It constrains sizing/new-risk advice only; "
    "no broker action is performed."
)

# Recommended NON-trading actions, ordered by severity.
ACTION_HOT = "no-new-risk recommended; reconcile open trades and review Moltbook before any new decision"
ACTION_ELEVATED = "reduce size and wait for a fresh, confirmed signal"
ACTION_WARM = "review Moltbook for the relevant pattern before sizing up"
ACTION_COOL = "discipline intact; standard human review still required"


def _clamp01(value: Any) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, v))


def _bucket(heat: float) -> str:
    for lo, name in HEAT_BUCKETS:
        if heat >= lo:
            return name
    return "COOL"


def compute_operator_heat(
    *,
    fomo: float = 0.0,
    revenge: float = 0.0,
    overconfidence: float = 0.0,
    urgency: float = 0.0,
    identity_attachment: float = 0.0,
    base_size: float = 1.0,
) -> dict[str, Any]:
    """Compute operator heat, the heat bucket, the dominant emotion, the
    size adjustment, and the recommended non-trading action.

    ``base_size`` is the operator's intended size unit (default 1.0 = "one
    unit"); the returned ``effective_position_size`` is advisory guidance
    only — it instructs no order.
    """
    emotions = {
        "FOMO": _clamp01(fomo),
        "Revenge": _clamp01(revenge),
        "Overconfidence": _clamp01(overconfidence),
        "Urgency": _clamp01(urgency),
        "IdentityAttachment": _clamp01(identity_attachment),
    }
    heat = (
        W_FOMO * emotions["FOMO"]
        + W_REVENGE * emotions["Revenge"]
        + W_OVERCONFIDENCE * emotions["Overconfidence"]
        + W_URGENCY * emotions["Urgency"]
        + W_IDENTITY * emotions["IdentityAttachment"]
    )
    heat = max(0.0, min(1.0, heat))
    bucket = _bucket(heat)
    dominant = max(emotions, key=emotions.get) if any(emotions.values()) else "none"
    diablo = heat > DIABLO_HEAT_THRESHOLD

    base = max(0.0, float(base_size or 0.0))
    effective_size = round(base * (1.0 - heat), 6)

    if diablo:
        action = ACTION_HOT
    elif bucket == "ELEVATED":
        action = ACTION_ELEVATED
    elif bucket == "WARM":
        action = ACTION_WARM
    else:
        action = ACTION_COOL

    out: dict[str, Any] = {
        "operator_heat": round(heat, 4),
        "heat_bucket": bucket,
        "dominant_emotion": dominant,
        "components": {k: round(v, 4) for k, v in emotions.items()},
        "base_size": base,
        "effective_position_size": effective_size,
        "size_adjustment": round(effective_size - base, 6),
        "diablo_no_new_risk": bool(diablo),
        "recommended_operator_action": action,
        "advisory_disclaimer": ADVISORY_DISCLAIMER,
        "human_review_required": True,
    }
    out.update(_contract.advisory_safety_stamps())
    return out


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="operator_emotional_content_gate.py",
        description=(
            "Advisory-only operator-heat decision variable. Not therapy. Pure "
            "compute, no broker calls. Recommends only non-trading actions."
        ),
    )
    for name in ("fomo", "revenge", "overconfidence", "urgency", "identity"):
        p.add_argument(f"--{name}", type=float, default=0.0)
    p.add_argument("--base-size", type=float, default=1.0)
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    rep = compute_operator_heat(
        fomo=args.fomo, revenge=args.revenge, overconfidence=args.overconfidence,
        urgency=args.urgency, identity_attachment=args.identity,
        base_size=args.base_size,
    )
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
    else:
        print("Operator Emotional Content Gate (advisory-only)")
        print("=" * 47)
        print(f"  operator heat        : {rep['operator_heat']}  ({rep['heat_bucket']})")
        print(f"  dominant emotion     : {rep['dominant_emotion']}")
        print(f"  effective size       : {rep['effective_position_size']} (base {rep['base_size']})")
        print(f"  diablo no-new-risk   : {rep['diablo_no_new_risk']}")
        print(f"  recommended action   : {rep['recommended_operator_action']}")
        print(f"\n  {rep['advisory_disclaimer']}")
    return 0


__all__ = [
    "compute_operator_heat",
    "DIABLO_HEAT_THRESHOLD",
    "ADVISORY_DISCLAIMER",
]


if __name__ == "__main__":
    raise SystemExit(main())
