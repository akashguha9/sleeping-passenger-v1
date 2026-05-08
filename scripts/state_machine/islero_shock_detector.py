"""ISLERO shock detector.

A shock can force reclassification of any event into the ISLERO state.
"""
from __future__ import annotations

from scripts.normalization.signal_event_schema import SignalEvent


def apply_islero_override(event: SignalEvent, *, shock_active: bool) -> SignalEvent:
    if shock_active:
        event.mvp_state = "ISLERO"
    return event


def detect_shock(event: SignalEvent) -> bool:
    """Heuristic: huge probability swing or huge market move counts as a shock."""
    ns = event.numeric_signal
    if ns.probability is not None and abs(ns.probability - 0.5) >= 0.45:
        return True
    if ns.price_change is not None and abs(ns.price_change) >= 0.10:
        return True
    if ns.transfer_value_usd is not None and ns.transfer_value_usd >= 50_000_000:
        return True
    return False
