"""Score the Real Rows Sprint — Phase 7B tests for bundle scoring coverage.

Prove the evidence bundle now carries a ``scoring`` section + an n_valid_p,
that scoring coverage feeds S_evidence WITHOUT unlocking any predictive claim,
that unavailable reasons are reported, and that the markdown states the honest
uncalibrated / no-edge / not-real-money truth.  All deterministic, offline,
against a TEMP DB.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

from scripts import persistence
from scripts import real_evidence_bundle as bundle_mod
from scripts.decision_probability_snapshot import record_decision_probability
from scripts.score_real_signal_events import score_real_signal_events


_AXES = {"EMS": 0.6, "EQS": 0.55, "DS": 0.5, "LS": 0.45, "EFS": 0.5, "APS": 0.5}


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _recent_iso(h: float = 1.0) -> str:
    return (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=h)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _yf_payload():
    return {
        "source": "market_data_yahoo", "ticker": "AAPL",
        "latest_price": 190.0, "previous_close": 185.0, "price_change_pct": 2.7,
        "volume": 9e7, "average_volume": 6e7, "volume_change_ratio": 1.5,
        "timestamp": _recent_iso(1.0),
    }


def _canary_report() -> dict:
    return {
        "per_source": [
            {"source_name": "yfinance", "activated": True, "canary_real": True},
            {"source_name": "polymarket", "activated": True, "canary_real": True},
            {"source_name": "sec_edgar", "activated": True, "canary_real": True},
        ],
        "C_global": 1.0,
        "live_canonical_count": 3,
    }


@pytest.fixture()
def scored_db(tmp_path):
    db = tmp_path / "snap.db"
    persistence.init_schema(db)
    # Two scorable yfinance rows + one missing-price (unavailable) row.
    persistence.upsert_signal_event_observation(
        event_id="YF_AAPL", source_name="yfinance", raw_payload=_yf_payload(),
        fetched_at=_now(), db_path=db,
    )
    persistence.upsert_signal_event_observation(
        event_id="YF_MSFT", source_name="yfinance", raw_payload=_yf_payload(),
        fetched_at=_now(), db_path=db,
    )
    persistence.upsert_signal_event_observation(
        event_id="YF_NOPRICE", source_name="yfinance",
        raw_payload={"source": "yfinance", "ticker": "X", "timestamp": _recent_iso(1.0)},
        fetched_at=_now(), db_path=db,
    )
    score_real_signal_events(db_path=db, now_iso=_now(), write=True)
    # Record two decision snapshots so n_valid_p > 0.
    for sid in ("YF_AAPL", "YF_MSFT"):
        record_decision_probability(db_path=db, signal_id=sid, axes=_AXES, prediction_horizon_days=5)
    return db


# --- 1. bundle contains scoring coverage ---------------------------------- #
def test_bundle_contains_scoring_coverage(scored_db):
    b = bundle_mod.build_evidence_bundle(scored_db, canary_report=_canary_report())
    assert "scoring" in b
    sc = b["scoring"]
    assert sc["n_real_canonical_rows"] == 3
    assert sc["n_scored_real_rows"] == 2
    assert sc["scoring_coverage"] == pytest.approx(2 / 3, abs=1e-6)
    assert sc["n_complete_score_vectors"] == 2
    assert sc["score_quality_coverage"] == pytest.approx(2 / 3, abs=1e-6)
    assert "yfinance" in sc["sources_scored"]


# --- 2. bundle contains n_valid_p ----------------------------------------- #
def test_bundle_contains_n_valid_p(scored_db):
    b = bundle_mod.build_evidence_bundle(scored_db, canary_report=_canary_report())
    assert b["scoring"]["n_valid_p"] == 2
    assert b["decision_snapshots"]["n_valid_p"] == 2


# --- 3. scoring coverage does NOT unlock the predictive claim -------------- #
def test_bundle_scoring_coverage_does_not_unlock_predictive_claim(scored_db):
    b = bundle_mod.build_evidence_bundle(scored_db, canary_report=_canary_report())
    assert b["scoring"]["predictive_claim_allowed"] is False
    assert b["predictive_claim_allowed"] is False
    assert b["scoring"]["calibration_status"] == "INSUFFICIENT_EVIDENCE"
    assert b["s_evidence"]["components"]["calibration_gate_score"] == 0.0
    assert b["scoring"]["edge_claimed"] is False
    assert b["scoring"]["real_money_ready"] is False


# --- 4. S_evidence uses scoring coverage ---------------------------------- #
def test_evidence_score_uses_scoring_coverage(scored_db):
    b = bundle_mod.build_evidence_bundle(scored_db, canary_report=_canary_report())
    comps = b["s_evidence"]["components"]
    assert "scoring_coverage" in comps
    assert comps["scoring_coverage"] == pytest.approx(2 / 3, abs=1e-6)
    # Close-the-Outcome-Loop re-weighting: scoring carries 0.15.
    assert b["s_evidence"]["weights"]["scoring"] == 0.15
    # The scoring component must actually move the total (weight * value > 0).
    assert b["s_evidence"]["score"] >= 0.15 * comps["scoring_coverage"]


# --- 5. S_evidence uses snapshot coverage --------------------------------- #
def test_evidence_score_uses_snapshot_coverage(scored_db):
    b = bundle_mod.build_evidence_bundle(scored_db, canary_report=_canary_report())
    comps = b["s_evidence"]["components"]
    assert "snapshot_coverage" in comps
    # 2 valid p / 200 target.
    assert comps["snapshot_coverage"] == pytest.approx(2 / 200, abs=1e-6)
    assert b["s_evidence"]["weights"]["snapshot"] == 0.20


# --- 6. score unavailable reasons ----------------------------------------- #
def test_bundle_reports_score_unavailable_reasons(scored_db):
    b = bundle_mod.build_evidence_bundle(scored_db, canary_report=_canary_report())
    reasons = b["scoring"]["score_unavailable_reasons"]
    assert isinstance(reasons, dict)
    assert reasons.get("MISSING_PRICE") == 1


# --- 7. markdown says uncalibrated when N < 200 --------------------------- #
def test_markdown_says_uncalibrated_when_n_below_200(scored_db):
    b = bundle_mod.build_evidence_bundle(scored_db, canary_report=_canary_report())
    md = bundle_mod.render_markdown(b).lower()
    assert "uncalibrated" in md
    assert "insufficient_evidence" in md
    assert "predictive claim" in md or "predictive_claim" in md


# --- 8. markdown says no edge claim --------------------------------------- #
def test_markdown_says_no_edge_claim(scored_db):
    b = bundle_mod.build_evidence_bundle(scored_db, canary_report=_canary_report())
    md = bundle_mod.render_markdown(b).lower()
    assert "edge is" in md and "not proven" in md
    # Must never claim an edge.
    for forbidden in ("edge proven", "edge confirmed", "proven edge"):
        assert forbidden not in md


# --- 9. markdown says not real-money ready -------------------------------- #
def test_markdown_says_not_real_money_ready(scored_db):
    b = bundle_mod.build_evidence_bundle(scored_db, canary_report=_canary_report())
    md = bundle_mod.render_markdown(b).lower()
    assert "not real-money ready" in md
    for forbidden in ("real-money ready: true", "real money ready", "place order",
                      "execute trade", "auto-trade"):
        assert forbidden not in md


# --- 10. advisory safety stamps preserved --------------------------------- #
def test_bundle_preserves_advisory_safety_stamps(scored_db):
    b = bundle_mod.build_evidence_bundle(scored_db, canary_report=_canary_report())
    assert b["advisory_status"] == "ADVISORY_ONLY"
    assert b["execution_gate"] == "LOCKED"
    assert b["broker_api_called"] is False
    assert b["ai_execution_count"] == 0
    assert b["human_execution_required"] is True
    assert b["real_money_ready"] is False
