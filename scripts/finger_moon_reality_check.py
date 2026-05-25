"""Finger / Moon Reality Check — "don't concentrate on the finger".

"It is like a finger pointing away to the moon. Don't concentrate on the
finger or you will miss all that heavenly glory."  AI output, news, narrative,
and Polymarket odds are *pointers*.  Price, volume, filings, and realised
outcomes are the *moon*.  This module measures how much of a read is anchored
in reality versus how much is pointer-worship.

Truth hierarchy (most → least authoritative):

    Filings / official      = legal reality
    Price                   = revealed market action
    Volume                  = commitment
    Polymarket              = priced belief (NOT truth)
    Outcome / Moltbook      = historical truth
    News                    = claim
    Narrative               = social transmission
    AI output               = interpretive pointer

Reality confirmation::

    RC = 0.22*PriceConfirmation + 0.18*VolumeConfirmation
         + 0.18*SourceCredibility + 0.16*LiquidityConfirmation
         + 0.14*FilingOrOfficialConfirmation
         + 0.12*OutcomeOrMoltbookConfirmation

Inputs are 0–1; RC is returned on a 0–10 scale to feed JKD directly.

Rules enforced as diagnostics:

    AIConsensus      != RealityConfirmation
    PolymarketOdds   != Truth
    NarrativeStrength!= FundamentalTruth

So a high ``ai_consensus`` / ``narrative_strength`` / ``polymarket_odds`` with
LOW real anchors (price/volume/filings) raises ``pointer_dominance_warning``
and lists the ``missing_reality_anchor`` set.

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

W_PRICE = 0.22
W_VOLUME = 0.18
W_SOURCE = 0.18
W_LIQUIDITY = 0.16
W_FILING = 0.14
W_OUTCOME = 0.12

# Source truth hierarchy, most → least authoritative.  Pointers are the ones a
# disciplined operator must never mistake for the moon.
SOURCE_TRUTH_HIERARCHY: tuple[str, ...] = (
    "filings_official",   # legal reality
    "price",              # revealed market action
    "volume",             # commitment
    "outcome_moltbook",   # historical truth
    "polymarket",         # priced belief (pointer)
    "news",               # claim (pointer)
    "narrative",          # social transmission (pointer)
    "ai_output",          # interpretive pointer
)
POINTER_SOURCES: frozenset[str] = frozenset(
    {"polymarket", "news", "narrative", "ai_output"}
)

# A real anchor is considered "present" at/above this 0–1 strength.
ANCHOR_PRESENT_THRESHOLD = 0.35
# Pointer is considered "loud" at/above this 0–1 strength.
POINTER_LOUD_THRESHOLD = 0.60

ADVISORY_DISCLAIMER = (
    "Advisory-only reality-confirmation check. AI/news/Polymarket/narrative are "
    "pointers, not truth; only price/volume/filings/outcomes anchor reality. "
    "No broker action is performed."
)


def _clamp01(value: Any) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, v))


def compute_reality_confirmation(
    *,
    price_confirmation: float = 0.0,
    volume_confirmation: float = 0.0,
    source_credibility: float = 0.0,
    liquidity_confirmation: float = 0.0,
    filing_or_official_confirmation: float = 0.0,
    outcome_or_moltbook_confirmation: float = 0.0,
    ai_consensus: float = 0.0,
    polymarket_odds: float = 0.0,
    narrative_strength: float = 0.0,
) -> dict[str, Any]:
    """Compute reality-confirmation (0–10) and pointer-dominance diagnostics."""
    price = _clamp01(price_confirmation)
    volume = _clamp01(volume_confirmation)
    source = _clamp01(source_credibility)
    liquidity = _clamp01(liquidity_confirmation)
    filing = _clamp01(filing_or_official_confirmation)
    outcome = _clamp01(outcome_or_moltbook_confirmation)

    rc01 = (
        W_PRICE * price
        + W_VOLUME * volume
        + W_SOURCE * source
        + W_LIQUIDITY * liquidity
        + W_FILING * filing
        + W_OUTCOME * outcome
    )
    rc_score = round(10.0 * rc01, 4)

    # Real anchors that are missing (below the present threshold).
    anchors = {
        "price": price,
        "volume": volume,
        "filings_official": filing,
        "liquidity": liquidity,
    }
    missing = sorted(k for k, v in anchors.items() if v < ANCHOR_PRESENT_THRESHOLD)

    # Pointer dominance: at least one loud pointer while real anchors are weak.
    pointers = {
        "ai_consensus": _clamp01(ai_consensus),
        "polymarket_odds": _clamp01(polymarket_odds),
        "narrative_strength": _clamp01(narrative_strength),
    }
    loud_pointer = any(v >= POINTER_LOUD_THRESHOLD for v in pointers.values())
    weak_reality = rc01 < 0.40
    pointer_dominance = bool(loud_pointer and weak_reality)

    out: dict[str, Any] = {
        "reality_confirmation_score": rc_score,
        "components": {
            "price_confirmation": price,
            "volume_confirmation": volume,
            "source_credibility": source,
            "liquidity_confirmation": liquidity,
            "filing_or_official_confirmation": filing,
            "outcome_or_moltbook_confirmation": outcome,
        },
        "pointers": {k: round(v, 4) for k, v in pointers.items()},
        "pointer_dominance_warning": pointer_dominance,
        "missing_reality_anchor": missing,
        "source_truth_hierarchy": list(SOURCE_TRUTH_HIERARCHY),
        "advisory_disclaimer": ADVISORY_DISCLAIMER,
        "human_review_required": True,
    }
    out.update(_contract.advisory_safety_stamps())
    return out


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="finger_moon_reality_check.py",
        description=(
            "Advisory-only reality-confirmation check. Separates pointers "
            "(AI/news/PM/narrative) from the moon (price/volume/filings). "
            "Pure compute, no broker calls."
        ),
    )
    for name in (
        "price", "volume", "source", "liquidity", "filing", "outcome",
        "ai-consensus", "polymarket-odds", "narrative-strength",
    ):
        p.add_argument(f"--{name}", type=float, default=0.0)
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    rep = compute_reality_confirmation(
        price_confirmation=args.price, volume_confirmation=args.volume,
        source_credibility=args.source, liquidity_confirmation=args.liquidity,
        filing_or_official_confirmation=args.filing,
        outcome_or_moltbook_confirmation=args.outcome,
        ai_consensus=getattr(args, "ai_consensus"),
        polymarket_odds=getattr(args, "polymarket_odds"),
        narrative_strength=getattr(args, "narrative_strength"),
    )
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
    else:
        print("Finger / Moon Reality Check (advisory-only)")
        print("=" * 43)
        print(f"  reality confirmation : {rep['reality_confirmation_score']} / 10")
        print(f"  pointer dominance    : {rep['pointer_dominance_warning']}")
        print(f"  missing anchors      : {rep['missing_reality_anchor']}")
        print(f"\n  {rep['advisory_disclaimer']}")
    return 0


__all__ = [
    "compute_reality_confirmation",
    "SOURCE_TRUTH_HIERARCHY",
    "POINTER_SOURCES",
    "ADVISORY_DISCLAIMER",
]


if __name__ == "__main__":
    raise SystemExit(main())
