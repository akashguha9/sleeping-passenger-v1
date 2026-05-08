"""Bull-state classifier.

States:
    MIURA       raw novelty, unvalidated signal
    MURCIELAGO  survives cross-source validation
    AVENTADOR   promoted action candidate, human review only
    GALLARDO    manual execution checklist only
    ISLERO      shock event override
    DIABLO      chaos veto / no new risk
    HURACAN     momentum fast-track only if minimum validation floor is met

Hard rules (also enforced in the processor):
    - DIABLO blocks promotion to AVENTADOR or GALLARDO.
    - HURACAN cannot bypass the minimum validation floor.
    - ISLERO may force reclassification.
    - No state may set execution_permission to anything but ADVISORY_ONLY.
"""
from __future__ import annotations

from scripts.normalization.signal_event_schema import SignalEvent

# Minimum validation floor (used by HURACAN fast-track).
MIN_VALIDATION_FLOOR = {
    "source_reliability": 0.5,
    "freshness_score": 0.4,
    "market_confirmation": 0.2,
}


def meets_validation_floor(event: SignalEvent) -> bool:
    return (
        event.source_reliability >= MIN_VALIDATION_FLOOR["source_reliability"]
        and event.freshness_score >= MIN_VALIDATION_FLOOR["freshness_score"]
        and event.market_confirmation >= MIN_VALIDATION_FLOOR["market_confirmation"]
    )


def classify(event: SignalEvent, *, chaos_active: bool = False, shock_active: bool = False,
             fast_track_requested: bool = False, cross_validated: bool = False) -> str:
    """Return the next mvp_state for ``event``. Pure function — does not mutate."""
    if shock_active:
        return "ISLERO"
    if chaos_active:
        return "DIABLO"
    if fast_track_requested:
        return "HURACAN" if meets_validation_floor(event) else "MIURA"
    if cross_validated and event.contradiction_score < 0.5:
        # Promotion path is candidate-only; final action stays advisory.
        if event.market_confirmation >= 0.6 and event.source_reliability >= 0.7:
            return "AVENTADOR"
        return "MURCIELAGO"
    return "MIURA"
