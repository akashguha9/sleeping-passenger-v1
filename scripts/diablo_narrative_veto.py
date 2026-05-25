"""Diablo Narrative Veto — hard advisory veto combinations.

Some combinations of weak signal and strong distortion are dangerous enough
that no amount of upside justifies a *new* risk decision.  This module names
those combinations and returns a hard advisory veto.  The veto blocks no
execution path (none exists) — it tightens the *advice* to a safe, non-trading
action and forces human review.

Veto combinations (each input is 0–1; a flag fires when its terms cross the
configured thresholds)::

    WeakSignal + StrongEmotion + Leverage      -> DIABLO
    ViralNarrative + NoFundamentalSupport       -> DIABLO
    ThinPolymarketMove + HighAssetImpact        -> DIABLO_REVIEW
    OldNews + HighConviction                     -> DIABLO
    HighOperatorHeat + UnclearInvalidation       -> DIABLO
    HighCrowding + LowLiquidity                  -> DIABLO

Safe actions only (never execution language): wait, reconcile first, reduce
size, review Moltbook, require fresh confirmation, no-new-risk recommended.

Safety
------
Pure functions.  No DB, no network, no broker calls.  Advisory-only.
"""
from __future__ import annotations

import argparse
import json
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

HIGH = 0.70   # "strong / high" threshold
LOW = 0.30    # "weak / thin / low" threshold

VETO_DIABLO = "DIABLO"
VETO_REVIEW = "DIABLO_REVIEW"
VETO_NONE = "CLEAR"

SAFE_ACTION_WAIT = "wait for a fresh, confirmed signal"
SAFE_ACTION_RECONCILE = "reconcile open trades first, then re-assess"
SAFE_ACTION_REDUCE = "reduce size and require fresh confirmation"
SAFE_ACTION_REVIEW_MOLTBOOK = "review Moltbook for this pattern before any new risk"
SAFE_ACTION_NO_NEW_RISK = "no-new-risk recommended until the combination clears"

ADVISORY_DISCLAIMER = (
    "Advisory-only narrative veto. It constrains advice to safe non-trading "
    "actions and forces human review; it performs no broker action and blocks "
    "no execution path because none exists."
)


def _clamp01(value: Any) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, v))


def evaluate_veto(
    *,
    signal_strength: float = 0.5,
    operator_emotion: float = 0.0,
    leverage: float = 0.0,
    narrative_virality: float = 0.0,
    fundamental_support: float = 0.5,
    polymarket_move_thinness: float = 0.0,
    asset_impact: float = 0.0,
    news_age: float = 0.0,
    conviction: float = 0.0,
    invalidation_clarity: float = 0.5,
    crowding: float = 0.0,
    liquidity: float = 0.5,
) -> dict[str, Any]:
    """Evaluate the hard advisory veto combinations.

    Returns the veto verdict (DIABLO / DIABLO_REVIEW / CLEAR), the firing
    combinations, the recommended safe (non-trading) action, and the
    advisory-only stamps.
    """
    s = _clamp01(signal_strength)
    emotion = _clamp01(operator_emotion)
    lev = _clamp01(leverage)
    viral = _clamp01(narrative_virality)
    fundamentals = _clamp01(fundamental_support)
    pm_thin = _clamp01(polymarket_move_thinness)
    impact = _clamp01(asset_impact)
    age = _clamp01(news_age)
    conv = _clamp01(conviction)
    inval = _clamp01(invalidation_clarity)
    crowd = _clamp01(crowding)
    liq = _clamp01(liquidity)

    fired: list[str] = []
    review: list[str] = []

    if s <= LOW and emotion >= HIGH and lev >= HIGH:
        fired.append("weak_signal+strong_emotion+leverage")
    if viral >= HIGH and fundamentals <= LOW:
        fired.append("viral_narrative+no_fundamental_support")
    if age >= HIGH and conv >= HIGH:
        fired.append("old_news+high_conviction")
    if emotion >= HIGH and inval <= LOW:
        fired.append("high_operator_heat+unclear_invalidation")
    if crowd >= HIGH and liq <= LOW:
        fired.append("high_crowding+low_liquidity")
    # Softer combination → review rather than hard veto.
    if pm_thin >= HIGH and impact >= HIGH:
        review.append("thin_polymarket_move+high_asset_impact")

    if fired:
        veto = VETO_DIABLO
    elif review:
        veto = VETO_REVIEW
    else:
        veto = VETO_NONE

    # Pick the most relevant safe action.
    if "high_operator_heat+unclear_invalidation" in fired or emotion >= HIGH:
        safe_action = SAFE_ACTION_RECONCILE
    elif "old_news+high_conviction" in fired:
        safe_action = SAFE_ACTION_WAIT
    elif fired:
        safe_action = SAFE_ACTION_NO_NEW_RISK
    elif review:
        safe_action = SAFE_ACTION_REVIEW_MOLTBOOK
    else:
        safe_action = "discipline intact; standard human review still required"

    out: dict[str, Any] = {
        "diablo_veto": veto != VETO_NONE,
        "veto_state": veto,
        "veto_reason": fired or review or [],
        "risk_combination": (fired + review) or [],
        "recommended_safe_action": safe_action,
        "advisory_disclaimer": ADVISORY_DISCLAIMER,
        "human_review_required": True,
    }
    out.update(_contract.advisory_safety_stamps())
    return out


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="diablo_narrative_veto.py",
        description=(
            "Advisory-only narrative veto for dangerous risk combinations. "
            "Pure compute, no broker calls. Recommends only safe non-trading "
            "actions."
        ),
    )
    for name, default in (
        ("signal-strength", 0.5), ("operator-emotion", 0.0), ("leverage", 0.0),
        ("narrative-virality", 0.0), ("fundamental-support", 0.5),
        ("polymarket-move-thinness", 0.0), ("asset-impact", 0.0),
        ("news-age", 0.0), ("conviction", 0.0), ("invalidation-clarity", 0.5),
        ("crowding", 0.0), ("liquidity", 0.5),
    ):
        p.add_argument(f"--{name}", type=float, default=default)
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    ns = vars(args)
    rep = evaluate_veto(
        signal_strength=ns["signal_strength"],
        operator_emotion=ns["operator_emotion"],
        leverage=ns["leverage"],
        narrative_virality=ns["narrative_virality"],
        fundamental_support=ns["fundamental_support"],
        polymarket_move_thinness=ns["polymarket_move_thinness"],
        asset_impact=ns["asset_impact"],
        news_age=ns["news_age"],
        conviction=ns["conviction"],
        invalidation_clarity=ns["invalidation_clarity"],
        crowding=ns["crowding"],
        liquidity=ns["liquidity"],
    )
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
    else:
        print("Diablo Narrative Veto (advisory-only)")
        print("=" * 38)
        print(f"  veto state         : {rep['veto_state']}")
        print(f"  veto reason        : {rep['veto_reason']}")
        print(f"  safe action        : {rep['recommended_safe_action']}")
        print(f"\n  {rep['advisory_disclaimer']}")
    return 0


__all__ = [
    "evaluate_veto",
    "VETO_DIABLO",
    "VETO_REVIEW",
    "VETO_NONE",
    "ADVISORY_DISCLAIMER",
]


if __name__ == "__main__":
    raise SystemExit(main())
