"""Canonical SignalEvent schema for the Global Signal Fabric.

This MVP is signal-intelligence only. Every SignalEvent is ADVISORY_ONLY and
human review is required. No state, score, or override may set
``execution_permission`` to anything other than ``ADVISORY_ONLY``.

Formula reminders (for human reviewers):

    Detected Signal != Investable Signal

    InvestableSignal = Detection
                       * Validation
                       * Durability
                       * ExecutionSurvivability
                       * HumanReview

    UsefulSource = MachineReadability
                   * LegalIngestion
                   * TimestampQuality
                   * SourceReliability
                   * PredictiveValue
                   * LowMaintenanceCost

Hard invariants:
    AI_ACTION_PERMISSION    = ADVISORY_ONLY
    BROKER_ORDER_PERMISSION = FALSE
    HUMAN_EXECUTION_REQUIRED = TRUE
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

ADVISORY_ONLY = "ADVISORY_ONLY"

# Hard ban: no SignalEvent or downstream module may set execution_permission to
# any of these values. The schema enforces this in __post_init__.
FORBIDDEN_PERMISSIONS = frozenset(
    {
        "EXECUTE",
        "AUTO_EXECUTE",
        "PLACE_ORDER",
        "SUBMIT_ORDER",
        "MARKET_ORDER",
        "LIMIT_ORDER",
        "AUTO_BUY",
        "AUTO_SELL",
        "BUY",
        "SELL",
    }
)

VALID_STATES = frozenset(
    {
        "MIURA",        # raw novelty
        "MURCIELAGO",   # cross-validated
        "AVENTADOR",    # promoted action candidate (human review only)
        "GALLARDO",     # manual execution checklist only
        "ISLERO",       # shock override
        "DIABLO",       # chaos veto
        "HURACAN",      # momentum fast-track (gated)
    }
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class NumericSignal:
    probability: float | None = None
    price_change: float | None = None
    volume_change: float | None = None
    transfer_value_usd: float | None = None
    filing_materiality_score: float = 0.0


@dataclass
class SignalEvent:
    """Canonical advisory signal record.

    Defaults are intentionally conservative: every event starts in MIURA
    (raw novelty), advisory-only, and flagged for human review.
    """

    source_name: str = "unknown"
    source_type: str = "unknown"
    jurisdiction: str = "GLOBAL"
    headline_or_label: str = ""
    raw_text_or_summary: str = ""
    url: str | None = None

    asset_tags: list[str] = field(default_factory=list)
    sector_tags: list[str] = field(default_factory=list)
    event_type: str = "generic"
    timestamp_utc: str = field(default_factory=_utc_now)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    numeric_signal: NumericSignal = field(default_factory=NumericSignal)

    source_reliability: float = 0.0
    freshness_score: float = 0.0
    narrative_intensity: float = 0.0
    market_confirmation: float = 0.0
    contradiction_score: float = 0.0

    mvp_state: str = "MIURA"
    execution_permission: str = ADVISORY_ONLY
    human_review_required: bool = True

    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Hard guardrails — never relax these.
        if self.execution_permission != ADVISORY_ONLY:
            raise ValueError(
                f"execution_permission must be {ADVISORY_ONLY}; got {self.execution_permission!r}"
            )
        if not self.human_review_required:
            raise ValueError("human_review_required must be True for every SignalEvent")
        if self.mvp_state not in VALID_STATES:
            raise ValueError(f"Unknown mvp_state {self.mvp_state!r}")
        if isinstance(self.numeric_signal, dict):
            self.numeric_signal = NumericSignal(**self.numeric_signal)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def assert_advisory_only(event: SignalEvent) -> None:
    """Defense in depth: callers can re-check the safety invariant."""
    if event.execution_permission != ADVISORY_ONLY:
        raise ValueError("SignalEvent execution_permission drifted from ADVISORY_ONLY")
    if not event.human_review_required:
        raise ValueError("SignalEvent human_review_required drifted from True")
    if event.execution_permission in FORBIDDEN_PERMISSIONS:
        raise ValueError("SignalEvent execution_permission is forbidden")
