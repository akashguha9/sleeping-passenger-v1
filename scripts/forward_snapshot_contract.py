"""Forward Snapshot Contract Sprint — Phase 1: the forward snapshot contract.

The previous sprint built the real outcome loop, but **no real-forward outcome
could ever attach** because production decision snapshots were structurally
incomplete: ``ticker`` was NULL, ``prediction_horizon_days`` was NULL, the
``target_event_definition`` was a manual/reconciliation string (not price-based),
and there was no entry/reference price.  This module defines — purely, with no
side effects — what a *forward-outcome-eligible* decision snapshot must carry so
that a future outcome can attach after its horizon closes.

It is ADVISORY-ONLY by construction.  Nothing here places an order, calls a
broker, or unlocks execution.  It NEVER claims calibration and NEVER claims edge:
making a snapshot outcome-*eligible* only means a binary ``y`` can be measured
later — it does not assert the model is right.

Eligibility (every factor must hold)::

    ForwardOutcomeEligible_i =
        I(ticker_i is valid)
      · I(model_probability_i is not null) · I(0 <= p_i <= 1)
      · I(prediction_horizon_days_i is not null) · I(horizon_i > 0)
      · I(target_event_definition_i in PRICE_BASED_TARGETS)
      · I(entry_price_i is not null) · I(entry_price_i > 0)
      · I(entry_price_timestamp_utc_i <= decision_timestamp_utc_i)
      · I(is_real_forward_i)
      · I(advisory_status_i == "ADVISORY_ONLY")
      · I(execution_gate_i == "LOCKED")

Outcome math (computed elsewhere, after the horizon closes — shown here for the
contract reader)::

    r_i = (P_exit_i - P_entry_i) / P_entry_i
    y_i = I(r_i >= target_return_threshold_i)

With the documented default ``target_return_threshold = 0.0`` this is the honest
first calibration target ``y_i = I(P_exit_i >= P_entry_i)`` — a measurable binary
outcome, NOT a claim of edge.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

try:  # pragma: no cover - exercised both ways across the suite
    from scripts.advisory_contract import advisory_safety_stamps
except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]

# --------------------------------------------------------------------------- #
# Documented, explicit defaults (never silently invented).
# --------------------------------------------------------------------------- #
# Price-based target definitions that yield a measurable binary outcome.
PRICE_BASED_TARGETS: frozenset[str] = frozenset(
    {
        "forward_return_ge_threshold",
        "forward_alpha_ge_threshold",
        "stop_or_target_first",
        "forward_return_between_bounds",
    }
)

# Manual / reconciliation targets are NOT valid for a real-forward calibration
# label — they are not price-based and cannot produce y in {0,1} from prices.
MANUAL_RECONCILIATION_TARGETS: frozenset[str] = frozenset(
    {
        "manual_trade_reconciliation_win_loss",
        "manual_reconciliation",
        "manual",
        "reconciliation",
    }
)

DEFAULT_FORWARD_HORIZON_DAYS: int = 5
DEFAULT_TARGET_EVENT_DEFINITION: str = "forward_return_ge_threshold"
DEFAULT_TARGET_RETURN_THRESHOLD: float = 0.0
# Stamped on every snapshot whose horizon/target/threshold came from these
# defaults rather than an explicit source-specific value — so the provenance of
# the target is auditable and never silently assumed.
TARGET_SOURCE: str = "DEFAULT_FORWARD_SNAPSHOT_CONTRACT_V1"

ADVISORY_STATUS: str = "ADVISORY_ONLY"
EXECUTION_GATE_LOCKED: str = "LOCKED"

# Max staleness for an entry/reference price relative to the decision timestamp.
MAX_ENTRY_PRICE_LOOKBACK_DAYS: float = 7.0

CONTRACT_VERSION: str = "forward-snapshot-contract-v1"

# --------------------------------------------------------------------------- #
# Honest unavailability reasons (one per failing eligibility factor).
# --------------------------------------------------------------------------- #
REASON_OK = "OK"
REASON_MISSING_TICKER = "MISSING_TICKER"
REASON_MISSING_PROBABILITY = "MISSING_PROBABILITY"
REASON_INVALID_PROBABILITY = "INVALID_PROBABILITY"
REASON_MISSING_HORIZON = "MISSING_HORIZON"
REASON_INVALID_HORIZON = "MISSING_HORIZON"  # non-positive == missing for our gate
REASON_MISSING_PRICE_TARGET = "MISSING_PRICE_TARGET"
REASON_MANUAL_RECONCILIATION_TARGET = "MISSING_PRICE_TARGET"
REASON_MISSING_ENTRY_PRICE = "MISSING_ENTRY_PRICE"
REASON_ENTRY_PRICE_AFTER_DECISION = "ENTRY_PRICE_AFTER_DECISION"
REASON_NOT_REAL_FORWARD = "NOT_REAL_FORWARD"
REASON_NOT_ADVISORY_ONLY = "NOT_ADVISORY_ONLY"
REASON_EXECUTION_NOT_LOCKED = "EXECUTION_NOT_LOCKED"


# --------------------------------------------------------------------------- #
# Ticker normalization (Phase 2 reuses this)
# --------------------------------------------------------------------------- #
_REJECTED_TICKERS = {"", "UNKNOWN", "NONE", "NULL", "NAN"}


def normalize_ticker(raw: Any) -> str | None:
    """Normalize a raw ticker string to the canonical form, or ``None``.

    * trims whitespace, uppercases;
    * preserves exchange prefixes already in use (``NSE:``/``BSE:``/``NASDAQ:``/
      ``NYSE:``) and suffixes (``.NS`` / ``.BO`` / ``.DE`` / ``.L`` ...);
    * rejects empty / ``"UNKNOWN"`` / null — those are never a valid ticker.

    It deliberately does NOT guess or strip exchange decorations: a bare symbol
    is used verbatim, a decorated one is preserved, so the price layer can match
    on whatever convention the source already used.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    upper = text.upper()
    if upper in _REJECTED_TICKERS:
        return None
    return upper


def ticker_valid(ticker: Any) -> bool:
    """``TickerValid_i = I(t not null) · I(t != "") · I(t != "UNKNOWN")``."""
    return normalize_ticker(ticker) is not None


def is_price_based_target(target_event_definition: Any) -> bool:
    """True iff the target is a price-based definition usable for a real-forward
    calibration label.  Manual/reconciliation targets are explicitly rejected."""
    text = str(target_event_definition or "").strip()
    return text in PRICE_BASED_TARGETS


def _valid_probability(p: Any) -> tuple[bool, str]:
    if p is None:
        return False, REASON_MISSING_PROBABILITY
    try:
        pf = float(p)
    except (TypeError, ValueError):
        return False, REASON_INVALID_PROBABILITY
    if pf < 0.0 or pf > 1.0:
        return False, REASON_INVALID_PROBABILITY
    return True, REASON_OK


def _parse_iso(ts: Any) -> datetime | None:
    if not ts:
        return None
    text = str(ts).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.fromisoformat(text[:10])
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --------------------------------------------------------------------------- #
# The eligibility boolean math
# --------------------------------------------------------------------------- #
def forward_outcome_eligible(
    *,
    ticker: Any,
    model_probability: Any,
    prediction_horizon_days: Any,
    target_event_definition: Any,
    entry_price: Any,
    entry_price_timestamp_utc: Any = None,
    decision_timestamp_utc: Any = None,
    is_real_forward: bool = True,
    advisory_status: Any = ADVISORY_STATUS,
    execution_gate: Any = EXECUTION_GATE_LOCKED,
) -> tuple[bool, str]:
    """Return ``(eligible, reason)`` for a single decision snapshot.

    ``eligible`` is the product of every indicator in the contract; ``reason`` is
    ``"OK"`` when eligible, else the first failing factor's honest reason code.
    Nothing here is fabricated — a missing field simply makes the snapshot
    ineligible with an explicit reason.
    """
    if not ticker_valid(ticker):
        return False, REASON_MISSING_TICKER

    p_ok, p_reason = _valid_probability(model_probability)
    if not p_ok:
        return False, p_reason

    if prediction_horizon_days is None:
        return False, REASON_MISSING_HORIZON
    try:
        horizon = float(prediction_horizon_days)
    except (TypeError, ValueError):
        return False, REASON_MISSING_HORIZON
    if horizon <= 0:
        return False, REASON_INVALID_HORIZON

    if not is_price_based_target(target_event_definition):
        return False, REASON_MISSING_PRICE_TARGET

    if entry_price is None:
        return False, REASON_MISSING_ENTRY_PRICE
    try:
        entry = float(entry_price)
    except (TypeError, ValueError):
        return False, REASON_MISSING_ENTRY_PRICE
    if entry <= 0:
        return False, REASON_MISSING_ENTRY_PRICE

    # The reference price must be anchored at/before the decision — never after
    # (no look-ahead).  When either timestamp is provided we enforce ordering.
    entry_dt = _parse_iso(entry_price_timestamp_utc)
    decision_dt = _parse_iso(decision_timestamp_utc)
    if entry_dt is not None and decision_dt is not None and entry_dt > decision_dt:
        return False, REASON_ENTRY_PRICE_AFTER_DECISION

    if not bool(is_real_forward):
        return False, REASON_NOT_REAL_FORWARD

    if str(advisory_status) != ADVISORY_STATUS:
        return False, REASON_NOT_ADVISORY_ONLY
    if str(execution_gate) != EXECUTION_GATE_LOCKED:
        return False, REASON_EXECUTION_NOT_LOCKED

    return True, REASON_OK


def eligibility_indicator(**kwargs: Any) -> int:
    """The integer product form of :func:`forward_outcome_eligible` (0 or 1)."""
    eligible, _ = forward_outcome_eligible(**kwargs)
    return int(eligible)


# --------------------------------------------------------------------------- #
# Default resolution helpers (explicit, stamped — never silent)
# --------------------------------------------------------------------------- #
def resolve_horizon_days(explicit: Any = None) -> tuple[int, str]:
    """Return ``(horizon_days, source)``; falls back to the documented default."""
    if explicit is not None:
        try:
            v = int(float(explicit))
            if v > 0:
                return v, "SOURCE_SPECIFIC"
        except (TypeError, ValueError):
            pass
    return DEFAULT_FORWARD_HORIZON_DAYS, TARGET_SOURCE


def resolve_target(
    explicit_target: Any = None,
    explicit_threshold: Any = None,
) -> tuple[str, float, str]:
    """Return ``(target_event_definition, target_return_threshold, target_source)``.

    A source-specific price-based target/threshold is honoured; otherwise the
    documented default forward-return target with a 0.0 threshold is used and the
    provenance is stamped ``DEFAULT_FORWARD_SNAPSHOT_CONTRACT_V1``.
    """
    target = DEFAULT_TARGET_EVENT_DEFINITION
    threshold = DEFAULT_TARGET_RETURN_THRESHOLD
    source = TARGET_SOURCE
    if explicit_target is not None and is_price_based_target(explicit_target):
        target = str(explicit_target).strip()
        source = "SOURCE_SPECIFIC"
        if explicit_threshold is not None:
            try:
                threshold = float(explicit_threshold)
            except (TypeError, ValueError):
                threshold = DEFAULT_TARGET_RETURN_THRESHOLD
    return target, threshold, source


def horizon_close_utc(decision_timestamp_utc: Any, prediction_horizon_days: Any) -> str | None:
    """``horizon_close = decision_timestamp + prediction_horizon_days·24h`` (UTC)."""
    from datetime import timedelta

    start = _parse_iso(decision_timestamp_utc)
    if start is None:
        return None
    try:
        days = float(prediction_horizon_days)
    except (TypeError, ValueError):
        return None
    if days <= 0:
        return None
    return (start + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# Build the full contract dict (advisory-only stamps included)
# --------------------------------------------------------------------------- #
def build_forward_contract(
    *,
    decision_id: str,
    event_id: str,
    source_name: str | None = None,
    source_type: str | None = None,
    signal_id: str | None = None,
    ticker: Any = None,
    timestamp_utc: str | None = None,
    model_probability: Any = None,
    prediction_horizon_days: Any = None,
    target_event_definition: Any = None,
    target_return_threshold: Any = None,
    benchmark_ticker: str | None = None,
    entry_price: Any = None,
    entry_price_timestamp_utc: str | None = None,
    entry_price_source: str | None = None,
    scoring_version: str | None = None,
    model_version: str | None = None,
    score_vector: Mapping[str, Any] | None = None,
    is_real_forward: bool = True,
) -> dict[str, Any]:
    """Assemble a :data:`ForwardSnapshotContract` dict, applying documented
    defaults and computing eligibility.  Always advisory-only; never claims a
    predictive edge or real-money readiness.
    """
    stamps = advisory_safety_stamps()
    norm_ticker = normalize_ticker(ticker)
    horizon, _h_src = resolve_horizon_days(prediction_horizon_days)
    target, threshold, target_source = resolve_target(
        target_event_definition, target_return_threshold
    )
    close_utc = horizon_close_utc(timestamp_utc, horizon)

    eligible, reason = forward_outcome_eligible(
        ticker=norm_ticker,
        model_probability=model_probability,
        prediction_horizon_days=horizon,
        target_event_definition=target,
        entry_price=entry_price,
        entry_price_timestamp_utc=entry_price_timestamp_utc,
        decision_timestamp_utc=timestamp_utc,
        is_real_forward=is_real_forward,
        advisory_status=stamps.get("advisory_status", ADVISORY_STATUS),
        execution_gate=stamps.get("execution_gate", EXECUTION_GATE_LOCKED),
    )

    contract: dict[str, Any] = {
        "decision_id": str(decision_id),
        "signal_id": signal_id,
        "event_id": str(event_id),
        "source_name": source_name,
        "source_type": source_type,
        "ticker": norm_ticker,
        "timestamp_utc": timestamp_utc,
        "model_probability": (
            float(model_probability) if model_probability is not None else None
        ),
        "prediction_horizon_days": int(horizon),
        "target_event_definition": target,
        "target_return_threshold": float(threshold),
        "target_source": target_source,
        "benchmark_ticker": benchmark_ticker,
        "entry_price": (float(entry_price) if entry_price is not None else None),
        "entry_price_timestamp_utc": entry_price_timestamp_utc,
        "entry_price_source": entry_price_source,
        "horizon_close_utc": close_utc,
        "scoring_version": scoring_version,
        "model_version": model_version,
        "score_vector": dict(score_vector or {}),
        "is_real_forward": bool(is_real_forward),
        "forward_outcome_eligible": bool(eligible),
        "forward_outcome_unavailable_reason": None if eligible else reason,
        "contract_version": CONTRACT_VERSION,
        # Advisory-only invariants — these can never be flipped here.
        "advisory_status": ADVISORY_STATUS,
        "human_execution_required": True,
        "execution_gate": EXECUTION_GATE_LOCKED,
        "broker_api_called": False,
        "ai_execution_count": 0,
        "predictive_claim_allowed": False,
        "edge_claimed": False,
        "real_money_ready": False,
    }
    return contract


__all__ = [
    "PRICE_BASED_TARGETS",
    "MANUAL_RECONCILIATION_TARGETS",
    "DEFAULT_FORWARD_HORIZON_DAYS",
    "DEFAULT_TARGET_EVENT_DEFINITION",
    "DEFAULT_TARGET_RETURN_THRESHOLD",
    "TARGET_SOURCE",
    "MAX_ENTRY_PRICE_LOOKBACK_DAYS",
    "CONTRACT_VERSION",
    "REASON_OK",
    "REASON_MISSING_TICKER",
    "REASON_MISSING_PROBABILITY",
    "REASON_INVALID_PROBABILITY",
    "REASON_MISSING_HORIZON",
    "REASON_MISSING_PRICE_TARGET",
    "REASON_MISSING_ENTRY_PRICE",
    "REASON_ENTRY_PRICE_AFTER_DECISION",
    "REASON_NOT_REAL_FORWARD",
    "REASON_EXECUTION_NOT_LOCKED",
    "normalize_ticker",
    "ticker_valid",
    "is_price_based_target",
    "forward_outcome_eligible",
    "eligibility_indicator",
    "resolve_horizon_days",
    "resolve_target",
    "horizon_close_utc",
    "build_forward_contract",
]
