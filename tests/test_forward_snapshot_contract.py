"""Phase 1 — forward snapshot contract tests (pure, advisory-only)."""
from __future__ import annotations

from scripts.forward_snapshot_contract import (
    DEFAULT_FORWARD_HORIZON_DAYS,
    DEFAULT_TARGET_EVENT_DEFINITION,
    DEFAULT_TARGET_RETURN_THRESHOLD,
    REASON_ENTRY_PRICE_AFTER_DECISION,
    REASON_MISSING_ENTRY_PRICE,
    REASON_MISSING_HORIZON,
    REASON_MISSING_PRICE_TARGET,
    REASON_MISSING_TICKER,
    TARGET_SOURCE,
    build_forward_contract,
    eligibility_indicator,
    forward_outcome_eligible,
    normalize_ticker,
    resolve_target,
)

_BASE = dict(
    decision_id="DPS_1",
    event_id="ev_1",
    ticker="AAPL",
    timestamp_utc="2026-05-10T00:00:00Z",
    model_probability=0.62,
    entry_price=190.0,
    entry_price_timestamp_utc="2026-05-09T00:00:00Z",
)


def test_forward_contract_requires_ticker():
    eligible, reason = forward_outcome_eligible(
        ticker=None,
        model_probability=0.6,
        prediction_horizon_days=5,
        target_event_definition="forward_return_ge_threshold",
        entry_price=100.0,
    )
    assert eligible is False
    assert reason == REASON_MISSING_TICKER

    c = build_forward_contract(**{**_BASE, "ticker": None})
    assert c["forward_outcome_eligible"] is False
    assert c["forward_outcome_unavailable_reason"] == REASON_MISSING_TICKER


def test_forward_contract_requires_positive_horizon():
    eligible, reason = forward_outcome_eligible(
        ticker="AAPL",
        model_probability=0.6,
        prediction_horizon_days=0,
        target_event_definition="forward_return_ge_threshold",
        entry_price=100.0,
    )
    assert eligible is False
    assert reason == REASON_MISSING_HORIZON

    eligible2, reason2 = forward_outcome_eligible(
        ticker="AAPL",
        model_probability=0.6,
        prediction_horizon_days=None,
        target_event_definition="forward_return_ge_threshold",
        entry_price=100.0,
    )
    assert eligible2 is False
    assert reason2 == REASON_MISSING_HORIZON


def test_forward_contract_requires_price_based_target():
    eligible, reason = forward_outcome_eligible(
        ticker="AAPL",
        model_probability=0.6,
        prediction_horizon_days=5,
        target_event_definition="manual_trade_reconciliation_win_loss",
        entry_price=100.0,
    )
    assert eligible is False
    assert reason == REASON_MISSING_PRICE_TARGET


def test_forward_contract_requires_entry_price():
    eligible, reason = forward_outcome_eligible(
        ticker="AAPL",
        model_probability=0.6,
        prediction_horizon_days=5,
        target_event_definition="forward_return_ge_threshold",
        entry_price=None,
    )
    assert eligible is False
    assert reason == REASON_MISSING_ENTRY_PRICE

    # zero / negative price is not a valid entry price either
    assert forward_outcome_eligible(
        ticker="AAPL", model_probability=0.6, prediction_horizon_days=5,
        target_event_definition="forward_return_ge_threshold", entry_price=0.0,
    )[1] == REASON_MISSING_ENTRY_PRICE


def test_forward_contract_marks_eligible_when_all_fields_present():
    eligible, reason = forward_outcome_eligible(
        ticker="AAPL",
        model_probability=0.6,
        prediction_horizon_days=5,
        target_event_definition="forward_return_ge_threshold",
        entry_price=190.0,
        entry_price_timestamp_utc="2026-05-09T00:00:00Z",
        decision_timestamp_utc="2026-05-10T00:00:00Z",
        is_real_forward=True,
    )
    assert eligible is True
    assert reason == "OK"

    c = build_forward_contract(**_BASE)
    assert c["forward_outcome_eligible"] is True
    assert c["forward_outcome_unavailable_reason"] is None


def test_forward_contract_preserves_advisory_only_stamps():
    c = build_forward_contract(**_BASE)
    assert c["advisory_status"] == "ADVISORY_ONLY"
    assert c["human_execution_required"] is True
    assert c["execution_gate"] == "LOCKED"
    assert c["broker_api_called"] is False
    assert c["ai_execution_count"] == 0
    # An execution-unlocked snapshot can NEVER be forward-eligible.
    eligible, reason = forward_outcome_eligible(
        ticker="AAPL", model_probability=0.6, prediction_horizon_days=5,
        target_event_definition="forward_return_ge_threshold", entry_price=190.0,
        execution_gate="UNLOCKED",
    )
    assert eligible is False
    assert reason == "EXECUTION_NOT_LOCKED"


def test_default_forward_return_target_is_explicit_not_silent():
    target, threshold, source = resolve_target(None, None)
    assert target == DEFAULT_TARGET_EVENT_DEFINITION == "forward_return_ge_threshold"
    assert threshold == DEFAULT_TARGET_RETURN_THRESHOLD == 0.0
    assert source == TARGET_SOURCE == "DEFAULT_FORWARD_SNAPSHOT_CONTRACT_V1"

    c = build_forward_contract(**_BASE)
    assert c["prediction_horizon_days"] == DEFAULT_FORWARD_HORIZON_DAYS == 5
    assert c["target_source"] == TARGET_SOURCE


def test_contract_does_not_claim_edge_or_calibration():
    c = build_forward_contract(**_BASE)
    assert c["predictive_claim_allowed"] is False
    assert c["edge_claimed"] is False
    assert c["real_money_ready"] is False


def test_contract_rejects_manual_reconciliation_target_for_real_forward():
    # An explicit manual target is never promoted to a price-based default; it
    # must fall back to the documented price-based default.
    target, _thr, source = resolve_target("manual_trade_reconciliation_win_loss", None)
    assert target == "forward_return_ge_threshold"
    assert source == TARGET_SOURCE
    # And eligibility with a manual target is rejected.
    eligible, reason = forward_outcome_eligible(
        ticker="AAPL", model_probability=0.6, prediction_horizon_days=5,
        target_event_definition="manual_reconciliation", entry_price=100.0,
    )
    assert eligible is False
    assert reason == REASON_MISSING_PRICE_TARGET


def test_forward_outcome_eligibility_boolean_math():
    # Indicator is the product of all factors: flip any one to 0 -> 0.
    full = dict(
        ticker="AAPL", model_probability=0.6, prediction_horizon_days=5,
        target_event_definition="forward_return_ge_threshold", entry_price=190.0,
        entry_price_timestamp_utc="2026-05-09T00:00:00Z",
        decision_timestamp_utc="2026-05-10T00:00:00Z", is_real_forward=True,
    )
    assert eligibility_indicator(**full) == 1
    assert eligibility_indicator(**{**full, "ticker": "UNKNOWN"}) == 0
    assert eligibility_indicator(**{**full, "model_probability": 1.7}) == 0
    assert eligibility_indicator(**{**full, "prediction_horizon_days": -1}) == 0
    assert eligibility_indicator(**{**full, "entry_price": -5.0}) == 0
    assert eligibility_indicator(**{**full, "is_real_forward": False}) == 0
    # entry price after decision timestamp == look-ahead -> ineligible
    bad = {**full, "entry_price_timestamp_utc": "2026-05-11T00:00:00Z"}
    assert eligibility_indicator(**bad) == 0
    assert forward_outcome_eligible(**bad)[1] == REASON_ENTRY_PRICE_AFTER_DECISION


def test_normalize_ticker_rejects_and_preserves():
    assert normalize_ticker(None) is None
    assert normalize_ticker("  ") is None
    assert normalize_ticker("unknown") is None
    assert normalize_ticker(" aapl ") == "AAPL"
    # exchange prefixes / suffixes preserved
    assert normalize_ticker("RELIANCE.NS") == "RELIANCE.NS"
    assert normalize_ticker("NSE:SBIN") == "NSE:SBIN"
    assert normalize_ticker("rhm.de") == "RHM.DE"
