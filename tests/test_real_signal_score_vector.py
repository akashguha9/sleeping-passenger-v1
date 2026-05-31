"""Score the Real Rows Sprint — Phase 3 tests for the score-vector contract.

These exercise the pure scoring module (no DB, no network).  They assert the
six axes stay in [0, 1], the three real source types score from realistic
fixtures, missing fields fail honestly, mock/backfill rows never score as real,
the advisory-only stamps survive, the idempotency key is stable, and no
calibration / edge claim leaks in.
"""
from __future__ import annotations

import datetime as _dt

import pytest

from scripts.real_signal_score_vector import (
    MODEL_VERSION,
    PARTIAL_SCORE,
    SCORE_UNAVAILABLE,
    SCORED,
    SCORING_VERSION,
    axes_complete,
    score_key,
    score_signal_event,
)

_AXES = ("EMS", "EQS", "DS", "LS", "EFS", "APS")


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _recent_iso(hours_ago: float = 1.0) -> str:
    return (
        _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=hours_ago)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")


def _yfinance_row() -> dict:
    return {
        "source": "market_data_yahoo",
        "ticker": "AAPL",
        "symbol": "AAPL",
        "latest_price": 190.0,
        "previous_close": 185.0,
        "price_change_pct": 2.7027,
        "volume": 90_000_000.0,
        "average_volume": 60_000_000.0,
        "volume_change_ratio": 1.5,
        "timestamp": _recent_iso(1.0),
        "market_confirmation_score": 0.6,
    }


def _polymarket_row() -> dict:
    return {
        "source": "polymarket",
        "market_id": "0xabc",
        "question": "Will X happen by year end?",
        "implied_probability": 0.72,
        "liquidity": 50_000.0,
        "volume": 120_000.0,
        "timestamp": _recent_iso(2.0),
    }


def _sec_edgar_row() -> dict:
    return {
        "source": "sec_edgar",
        "cik": "0000320193",
        "entity_name": "Apple Inc.",
        "form_type": "8-K",
        "filing_date": _dt.date.today().isoformat(),
        "accession_number": "0000320193-26-000001",
    }


# --------------------------------------------------------------------------- #
# 1. all axes in [0, 1]
# --------------------------------------------------------------------------- #
def test_score_vector_all_axes_between_zero_and_one():
    now = _now()
    for row, src in (
        (_yfinance_row(), "yfinance"),
        (_polymarket_row(), "polymarket"),
        (_sec_edgar_row(), "sec_edgar"),
    ):
        vec = score_signal_event(row, source_name=src, now_iso=now)
        assert vec["score_status"] in (SCORED, PARTIAL_SCORE), (src, vec)
        for axis in _AXES:
            v = vec[axis]
            assert v is not None, (src, axis)
            assert 0.0 <= float(v) <= 1.0, (src, axis, v)


# --------------------------------------------------------------------------- #
# 2. yfinance scores with price fields present
# --------------------------------------------------------------------------- #
def test_yfinance_real_row_scores_when_price_fields_present():
    vec = score_signal_event(_yfinance_row(), source_name="yfinance", now_iso=_now())
    assert vec["score_status"] == SCORED
    assert vec["real_row"] is True
    assert vec["source_type"] == "market_data"
    assert axes_complete(vec)
    # A clear up-move should push momentum above the neutral 0.5 mark.
    assert vec["EMS"] > 0.5


# --------------------------------------------------------------------------- #
# 3. polymarket scores with probability present
# --------------------------------------------------------------------------- #
def test_polymarket_real_row_scores_when_probability_present():
    vec = score_signal_event(_polymarket_row(), source_name="polymarket", now_iso=_now())
    assert vec["score_status"] == SCORED
    assert vec["real_row"] is True
    assert vec["source_type"] == "prediction_market"
    assert axes_complete(vec)
    # p=0.72 => |p-0.5|*2 = 0.44 momentum.
    assert vec["EMS"] == pytest.approx(0.44, abs=1e-6)


# --------------------------------------------------------------------------- #
# 4. sec edgar scores with form_type present
# --------------------------------------------------------------------------- #
def test_sec_edgar_real_row_scores_when_form_type_present():
    vec = score_signal_event(_sec_edgar_row(), source_name="sec_edgar", now_iso=_now())
    assert vec["score_status"] == SCORED
    assert vec["real_row"] is True
    assert vec["source_type"] == "regulatory_filing"
    assert axes_complete(vec)
    # 8-K is top materiality => strong EMS for a fresh filing.
    assert vec["EMS"] > 0.5


# --------------------------------------------------------------------------- #
# 5. missing required fields => SCORE_UNAVAILABLE
# --------------------------------------------------------------------------- #
def test_missing_required_fields_returns_score_unavailable():
    now = _now()
    # yfinance with no price at all.
    m = {"source": "yfinance", "ticker": "AAPL", "timestamp": _recent_iso(1.0)}
    vm = score_signal_event(m, source_name="yfinance", now_iso=now)
    assert vm["score_status"] == SCORE_UNAVAILABLE
    assert vm["score_reason"] == "MISSING_PRICE"
    assert all(vm[a] is None for a in _AXES)

    # polymarket with no probability.
    p = {"source": "polymarket", "market_id": "x", "timestamp": _recent_iso(1.0)}
    vp = score_signal_event(p, source_name="polymarket", now_iso=now)
    assert vp["score_status"] == SCORE_UNAVAILABLE
    assert vp["score_reason"] == "MISSING_PROBABILITY"

    # sec with no form_type.
    s = {"source": "sec_edgar", "cik": "1", "filing_date": "2026-01-01"}
    vs = score_signal_event(s, source_name="sec_edgar", now_iso=now)
    assert vs["score_status"] == SCORE_UNAVAILABLE
    assert vs["score_reason"] == "MISSING_FORM_TYPE"


def test_yfinance_missing_previous_price_is_partial_not_fabricated():
    row = _yfinance_row()
    row.pop("previous_close", None)
    row.pop("price_change_pct", None)
    vec = score_signal_event(row, source_name="yfinance", now_iso=_now())
    # A confirmation proxy exists, so PARTIAL_SCORE (never a fabricated SCORED).
    assert vec["score_status"] == PARTIAL_SCORE
    assert not axes_complete(vec)


# --------------------------------------------------------------------------- #
# 6. mock row never scores as real
# --------------------------------------------------------------------------- #
def test_mock_row_never_scores_as_real():
    vec = score_signal_event(
        _yfinance_row(), source_name="yfinance", now_iso=_now(), mock_flag=True
    )
    assert vec["score_status"] == SCORE_UNAVAILABLE
    assert vec["real_row"] is False
    assert vec["mock_flag"] is True
    assert vec["score_reason"] == "MOCK_ROW_NOT_REAL"
    assert all(vec[a] is None for a in _AXES)


# --------------------------------------------------------------------------- #
# 7. backfill row never scores as fresh-live
# --------------------------------------------------------------------------- #
def test_backfill_row_never_scores_as_fresh_live():
    vec = score_signal_event(
        _yfinance_row(), source_name="yfinance", now_iso=_now(), backfill_flag=True
    )
    assert vec["score_status"] == SCORE_UNAVAILABLE
    assert vec["real_row"] is False
    assert vec["backfill_flag"] is True
    assert vec["score_reason"] == "BACKFILL_ROW_NOT_FRESH_LIVE"
    assert all(vec[a] is None for a in _AXES)


# --------------------------------------------------------------------------- #
# 8. advisory-only stamps preserved
# --------------------------------------------------------------------------- #
def test_score_vector_preserves_advisory_only_stamps():
    for row, src in (
        (_yfinance_row(), "yfinance"),
        (_polymarket_row(), "polymarket"),
        (_sec_edgar_row(), "sec_edgar"),
        # An unavailable vector must still carry the stamps.
        ({"source": "yfinance"}, "yfinance"),
    ):
        vec = score_signal_event(row, source_name=src, now_iso=_now())
        assert vec["advisory_status"] == "ADVISORY_ONLY"
        assert vec["human_execution_required"] is True
        assert vec["execution_gate"] == "LOCKED"
        assert vec["broker_api_called"] is False
        assert vec["ai_execution_count"] == 0


# --------------------------------------------------------------------------- #
# 9. idempotency key stable
# --------------------------------------------------------------------------- #
def test_score_vector_idempotency_key_stable():
    k1 = score_key("EVT_1", "yfinance", SCORING_VERSION)
    k2 = score_key("EVT_1", "yfinance", SCORING_VERSION)
    assert k1 == k2
    # Different event / source / version => different key.
    assert score_key("EVT_2", "yfinance", SCORING_VERSION) != k1
    assert score_key("EVT_1", "polymarket", SCORING_VERSION) != k1
    assert score_key("EVT_1", "yfinance", "real-row-score-v2") != k1


# --------------------------------------------------------------------------- #
# 10. no calibration / edge claim
# --------------------------------------------------------------------------- #
def test_score_vector_not_claiming_calibration():
    for row, src in (
        (_yfinance_row(), "yfinance"),
        (_polymarket_row(), "polymarket"),
        (_sec_edgar_row(), "sec_edgar"),
    ):
        vec = score_signal_event(row, source_name=src, now_iso=_now())
        assert vec["predictive_claim_allowed"] is False
        assert vec["edge_claimed"] is False
        assert vec["model_version"] == MODEL_VERSION
        assert vec["scoring_version"] == SCORING_VERSION
        # No probability is emitted by the pure scorer — that is the decision
        # path's job, gated behind calibration.
        assert "model_probability" not in vec
