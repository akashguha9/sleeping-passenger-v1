"""Market-physics simulator layer (advisory-only).

Doctrine:
    No signal is immortal.
    No score is naked.
    No stale soft signal can support hard conviction.
    No fire extinguisher, no trade.
    No high opportunity score can override high crash density.
    No candidate is promoted without telemetry.
    No user action is allowed if driver discipline is dangerous.
    Prediction markets are radar, not the trade.
    Narratives are weather. Signals are tyres.
    Evidence is downforce. Noise is drag.
    The MVP is the chassis. Crash cases are the wall.
    Telemetry is truth.

Every output of this package is ADVISORY_ONLY: it informs a human journal
decision and never places, routes, or sizes a real order.
"""

DOCTRINE: tuple[str, ...] = (
    "No signal is immortal.",
    "No score is naked.",
    "No stale soft signal can support hard conviction.",
    "No fire extinguisher, no trade.",
    "No high opportunity score can override high crash density.",
    "No candidate is promoted without telemetry.",
    "No user action is allowed if driver discipline is dangerous.",
    "Prediction markets are radar, not the trade.",
    "Narratives are weather.",
    "Signals are tyres.",
    "Evidence is downforce.",
    "Noise is drag.",
    "The MVP is the chassis.",
    "Crash cases are the wall.",
    "Telemetry is truth.",
)

ADVISORY_NOTE = (
    "ADVISORY_ONLY — simulator output for journal review. "
    "No order is placed, sized, or routed. Human decision required."
)
