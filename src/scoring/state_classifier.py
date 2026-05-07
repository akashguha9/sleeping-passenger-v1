"""Deterministic state classification for signal admission."""

from __future__ import annotations

from src.models.signal import StateDecision


def classify_state(
    *,
    ems: float,
    eqs: float,
    ds: float,
    ls: float,
    efs: float,
    aps: float,
) -> StateDecision:
    """Classify a signal into IGNORE, WATCH, VALIDATE, or PAPER_TRADE."""
    if ems >= 0.75 and eqs < 0.45:
        return StateDecision(
            state="IGNORE",
            reason_codes=["HIGH_ENGAGEMENT_MANIPULATION", "LOW_EVIDENCE_QUALITY"],
            explanation="Ignored because manipulation risk is high while evidence quality is weak.",
        )
    if efs >= 0.80:
        return StateDecision(
            state="IGNORE",
            reason_codes=["HIGH_EXECUTION_FRICTION"],
            explanation="Ignored because execution friction is too high for even paper admission.",
        )
    if (
        aps >= 0.70
        and eqs >= 0.65
        and ds >= 0.60
        and ls >= 0.50
        and ems < 0.60
        and efs < 0.50
    ):
        return StateDecision(
            state="PAPER_TRADE",
            reason_codes=["PAPER_EDGE_DETECTED", "ALL_PAPER_THRESHOLDS_PASSED"],
            explanation="Admitted to paper trade because evidence, durability, liquidity, and edge thresholds are all satisfied.",
        )
    if aps >= 0.55 and eqs >= 0.50 and ds >= 0.45 and ems < 0.70:
        return StateDecision(
            state="VALIDATE",
            reason_codes=["REQUIRES_DURABILITY_VALIDATION"],
            explanation="Admitted to validation because the signal is promising but not yet strong enough for paper trading.",
        )
    if 0.35 <= aps < 0.55:
        return StateDecision(
            state="WATCH",
            reason_codes=["WATCHLIST_THRESHOLD_MET"],
            explanation="Admitted to watch because the signal is early or incomplete.",
        )
    return StateDecision(
        state="IGNORE",
        reason_codes=["INSUFFICIENT_PRIORITY_SCORE"],
        explanation="Ignored because the signal did not clear the minimum watch threshold.",
    )
