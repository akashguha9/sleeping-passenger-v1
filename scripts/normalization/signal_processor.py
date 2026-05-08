"""Canonical processing pipeline for raw events.

``process_signal`` is the single entry point used by every loader's
``normalize`` step *and* by the report builders. It enforces the advisory-only
invariants in one place so individual loaders can stay small.

Order of operations:
    1. normalize raw_event -> SignalEvent
    2. score source reliability
    3. score freshness
    4. score materiality / narrative intensity (loader-supplied if present)
    5. check market confirmation (loader-supplied if present)
    6. check contradiction
    7. classify bull state
    8. apply DIABLO chaos veto
    9. apply ISLERO shock override
   10. stamp execution_permission = ADVISORY_ONLY
   11. stamp human_review_required = True
   12. return SignalEvent
"""
from __future__ import annotations

from typing import Any

from scripts.normalization.signal_event_schema import (
    ADVISORY_ONLY,
    NumericSignal,
    SignalEvent,
    assert_advisory_only,
)
from scripts.normalization.source_reliability import reliability_for
from scripts.scoring.contradiction_score import contradiction_score
from scripts.scoring.freshness_score import freshness_score
from scripts.scoring.market_confirmation_score import market_confirmation_score
from scripts.state_machine.bull_state_classifier import classify
from scripts.state_machine.diablo_chaos_veto import apply_diablo_veto
from scripts.state_machine.huracan_fast_track import apply_huracan_fast_track
from scripts.state_machine.islero_shock_detector import (
    apply_islero_override,
    detect_shock,
)


def _coerce_numeric(payload: Any) -> NumericSignal:
    if isinstance(payload, NumericSignal):
        return payload
    if isinstance(payload, dict):
        return NumericSignal(
            probability=payload.get("probability"),
            price_change=payload.get("price_change"),
            volume_change=payload.get("volume_change"),
            transfer_value_usd=payload.get("transfer_value_usd"),
            filing_materiality_score=float(payload.get("filing_materiality_score") or 0.0),
        )
    return NumericSignal()


def _to_signal_event(raw: Any) -> SignalEvent:
    if isinstance(raw, SignalEvent):
        return raw
    if not isinstance(raw, dict):
        raise TypeError(f"raw_event must be SignalEvent or dict, got {type(raw).__name__}")
    payload = dict(raw)
    payload["numeric_signal"] = _coerce_numeric(payload.get("numeric_signal"))
    # Defensive: never accept caller-supplied execution overrides.
    payload["execution_permission"] = ADVISORY_ONLY
    payload["human_review_required"] = True
    # Drop unknown fields gracefully.
    allowed = SignalEvent.__dataclass_fields__.keys()  # type: ignore[attr-defined]
    payload = {k: v for k, v in payload.items() if k in allowed}
    return SignalEvent(**payload)


def process_signal(
    raw_event: Any,
    *,
    chaos_active: bool = False,
    fast_track_requested: bool = False,
    cross_validated: bool = False,
    peer_directions: list[int] | None = None,
    market_direction: int = 0,
) -> SignalEvent:
    event = _to_signal_event(raw_event)

    # 2. source reliability — keep loader-supplied value if it already provided one.
    if event.source_reliability == 0.0:
        event.source_reliability = reliability_for(event.source_type)

    # 3. freshness
    if event.freshness_score == 0.0:
        event.freshness_score = freshness_score(event.timestamp_utc)

    # 4. narrative_intensity / materiality — left to loader-supplied values for now.
    if event.numeric_signal.filing_materiality_score and event.narrative_intensity == 0.0:
        event.narrative_intensity = max(
            event.narrative_intensity, event.numeric_signal.filing_materiality_score
        )

    # 5. market confirmation
    if event.market_confirmation == 0.0 and market_direction != 0:
        event.market_confirmation = market_confirmation_score(
            market_direction, event.numeric_signal.price_change
        )

    # 6. contradiction across peers
    if peer_directions:
        event.contradiction_score = contradiction_score(peer_directions)

    # 7. classify
    shock_active = detect_shock(event)
    event.mvp_state = classify(
        event,
        chaos_active=chaos_active,
        shock_active=shock_active,
        fast_track_requested=fast_track_requested,
        cross_validated=cross_validated,
    )

    # 8/9. veto + override (idempotent against the classifier).
    apply_diablo_veto(event, chaos_active=chaos_active)
    apply_islero_override(event, shock_active=shock_active)
    apply_huracan_fast_track(event, requested=fast_track_requested)

    # 10/11. final advisory stamps (defense in depth).
    event.execution_permission = ADVISORY_ONLY
    event.human_review_required = True

    assert_advisory_only(event)
    return event
