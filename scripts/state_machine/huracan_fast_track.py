"""HURACAN momentum fast-track.

A HURACAN promotion may *only* occur when the minimum validation floor is
met. It never bypasses validation.
"""
from __future__ import annotations

from scripts.normalization.signal_event_schema import SignalEvent
from scripts.state_machine.bull_state_classifier import meets_validation_floor


def apply_huracan_fast_track(event: SignalEvent, *, requested: bool) -> SignalEvent:
    if not requested:
        return event
    if meets_validation_floor(event):
        event.mvp_state = "HURACAN"
    # If floor not met, fast-track is denied — leave state untouched.
    return event
