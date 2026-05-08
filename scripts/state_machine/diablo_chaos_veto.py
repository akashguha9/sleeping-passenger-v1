"""DIABLO chaos veto.

If the regime is in chaos, no new risk may be promoted. In particular,
AVENTADOR and GALLARDO promotions are forbidden while DIABLO is active.
"""
from __future__ import annotations

from scripts.normalization.signal_event_schema import SignalEvent

BLOCKED_PROMOTIONS = frozenset({"AVENTADOR", "GALLARDO"})


def apply_diablo_veto(event: SignalEvent, *, chaos_active: bool) -> SignalEvent:
    if not chaos_active:
        return event
    if event.mvp_state in BLOCKED_PROMOTIONS:
        event.mvp_state = "DIABLO"
    elif event.mvp_state != "ISLERO":
        # ISLERO is the shock override and outranks DIABLO.
        event.mvp_state = "DIABLO"
    return event
