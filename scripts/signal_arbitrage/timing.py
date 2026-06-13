"""Layer 7 — Threshold / Ante / Half-Life Timing Layer.

A true signal can still fail if it misses the transfer window.  Each layer has:

  threshold       — minimum signal strength to activate the layer
  ante            — cost/risk required to play or survive the layer
  half_life_days  — decay speed (from the platform ecology)
  transfer_window — whether the signal moved on before decay

    Signal(t)    = Signal0 * (1/2) ** (t / half_life)
    Layer Pass   = strength >= threshold and payoff > ante and t < half_life

The alpha zone is *after threshold breach but before market recognition*.  The
state machine classifies where in that life a signal sits.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .util import clamp, r3

# Signal states, ordered from too-early to too-late.
PRE_THRESHOLD = "PRE_THRESHOLD"
THRESHOLD_BREACH = "THRESHOLD_BREACH"
ACTIVE_TRANSFER_WINDOW = "ACTIVE_TRANSFER_WINDOW"
FUNDAMENTAL_CONFIRMATION = "FUNDAMENTAL_CONFIRMATION"
MARKET_RECOGNITION = "MARKET_RECOGNITION"
POST_HALF_LIFE_DECAY = "POST_HALF_LIFE_DECAY"
CROWDED_EXHAUSTED = "CROWDED_EXHAUSTED"

DEFAULT_THRESHOLD = 0.35
DEFAULT_ANTE = 0.2


@dataclass(frozen=True)
class TimingResult:
    state: str
    decayed_strength: float
    age_half_lives: float
    timing_edge_score: float        # 0..1: how good the entry timing is
    within_transfer_window: bool
    reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("decayed_strength", "age_half_lives", "timing_edge_score"):
            d[k] = r3(d[k])
        return d


def classify_timing(
    *,
    strength: float,
    age_days: float,
    half_life_days: float,
    reality_confirmation: float = 0.0,
    price_recognition: float = 0.0,
    crowding: float = 0.0,
    threshold: float = DEFAULT_THRESHOLD,
    ante: float = DEFAULT_ANTE,
) -> TimingResult:
    """Place a signal on the threshold->recognition->decay timeline."""
    half_life_days = max(0.1, half_life_days)
    age_hl = age_days / half_life_days
    decayed = clamp(strength * (0.5 ** age_hl))

    reasons: list[str] = []
    payoff = decayed  # proxy: surviving strength is the playable payoff

    # State machine — order matters; first match wins on the "too late" side.
    if crowding >= 0.7:
        state = CROWDED_EXHAUSTED
        reasons.append("CROWDED")
    elif price_recognition >= 0.7:
        state = MARKET_RECOGNITION
        reasons.append("PRICED_IN")
    elif age_hl >= 1.0 and decayed < threshold:
        state = POST_HALF_LIFE_DECAY
        reasons.append("DECAYED_PAST_HALF_LIFE")
    elif strength < threshold:
        state = PRE_THRESHOLD
        reasons.append("BELOW_ACTIVATION_THRESHOLD")
    elif reality_confirmation >= 0.5 and price_recognition < 0.5:
        state = FUNDAMENTAL_CONFIRMATION
        reasons.append("CONFIRMED_NOT_YET_PRICED")
    else:
        state = THRESHOLD_BREACH if age_hl < 0.25 else ACTIVE_TRANSFER_WINDOW
        reasons.append("BREACH_FRESH" if age_hl < 0.25 else "IN_TRANSFER_WINDOW")

    within_window = state in (
        THRESHOLD_BREACH, ACTIVE_TRANSFER_WINDOW, FUNDAMENTAL_CONFIRMATION,
    )

    # Timing edge: best in the alpha zone (breach..confirmation, not priced),
    # decays as the signal ages and as the market recognizes it.
    if within_window:
        edge = clamp(decayed * (1.0 - 0.5 * price_recognition) * (1.0 - 0.5 * crowding))
        if payoff <= ante:
            edge = clamp(edge - 0.2)
            reasons.append("PAYOFF_BELOW_ANTE")
    elif state == PRE_THRESHOLD:
        edge = clamp(0.3 * strength)  # may yet activate; small option value
    else:
        edge = clamp(0.1 * decayed)   # too late / crowded — little edge left

    return TimingResult(
        state=state,
        decayed_strength=decayed,
        age_half_lives=age_hl,
        timing_edge_score=edge,
        within_transfer_window=within_window,
        reason_codes=reasons,
    )


__all__ = [
    "PRE_THRESHOLD", "THRESHOLD_BREACH", "ACTIVE_TRANSFER_WINDOW",
    "FUNDAMENTAL_CONFIRMATION", "MARKET_RECOGNITION", "POST_HALF_LIFE_DECAY",
    "CROWDED_EXHAUSTED", "TimingResult", "classify_timing",
]
