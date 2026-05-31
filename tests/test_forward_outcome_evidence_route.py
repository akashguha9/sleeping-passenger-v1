"""Phase 8 — /evidence/outcomes surfaces forward-eligibility (read-only)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from _forward_snapshot_helpers import (  # type: ignore[import-not-found]
    event_row,
    init_db,
    seed_market_bar,
    seed_score_vector,
)
from scripts.api.routers.evidence_router import build_outcomes_payload
from scripts.run_daily_live_advisory_decisions import run_daily_decision_batch


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "mvp.db"
    init_db(p)
    return p


def test_outcomes_route_reports_forward_eligible_count(db):
    # An old, priceable, scored row -> forward-eligible AND due (horizon long
    # past relative to the real clock the route reads).
    seed_score_vector(db, event_id="ev1", ticker="AAPL")
    seed_market_bar(db, symbol="AAPL", timestamp="2026-05-09T00:00:00Z", close=190.0)
    run_daily_decision_batch(
        db_path=db, events=[event_row("ev1", payload={})],
        now_iso="2026-05-10T00:00:00Z", write=True,
    )
    payload = build_outcomes_payload(db_path=db)
    assert payload["status"] == "OK"
    assert payload["n_forward_outcome_eligible"] == 1
    assert payload["n_due_forward"] == 1  # 05-15 close is in the past
    assert payload["entry_price_present_count"] == 1


def test_outcomes_route_reports_forward_unavailable_reasons(db):
    seed_score_vector(db, event_id="ev2", ticker="NVDA")  # no price bars
    run_daily_decision_batch(
        db_path=db, events=[event_row("ev2", payload={})],
        now_iso="2026-05-10T00:00:00Z", write=True,
    )
    payload = build_outcomes_payload(db_path=db)
    assert payload["n_forward_ineligible"] == 1
    assert payload["forward_unavailable_reasons"].get("MISSING_ENTRY_PRICE") == 1


def test_outcomes_route_reports_pending_horizon(db):
    # A freshly-created live snapshot (decision ~now) has an open horizon.
    now = datetime.now(timezone.utc)
    seed_score_vector(db, event_id="ev3", ticker="AAPL")
    seed_market_bar(db, symbol="AAPL", timestamp=_iso(now - timedelta(days=1)), close=190.0)
    run_daily_decision_batch(
        db_path=db, events=[event_row("ev3", payload={})],
        now_iso=_iso(now), write=True,
    )
    payload = build_outcomes_payload(db_path=db)
    assert payload["n_pending_horizon"] >= 1
    assert payload["n_due_forward"] == 0


def test_no_green_calibration_below_200(db):
    seed_score_vector(db, event_id="ev1", ticker="AAPL")
    seed_market_bar(db, symbol="AAPL", timestamp="2026-05-09T00:00:00Z", close=190.0)
    run_daily_decision_batch(
        db_path=db, events=[event_row("ev1", payload={})],
        now_iso="2026-05-10T00:00:00Z", write=True,
    )
    payload = build_outcomes_payload(db_path=db)
    assert payload["predictive_claim_allowed"] is False
    assert payload["predictive_claim_label"] == "PREDICTIVE_CLAIM_LOCKED"
    assert payload["calibration_status"] != "CALIBRATED"
    assert payload["n_needed_to_200"] == 200 - payload["n_real_forward_pairs"]


def test_no_execution_language(db):
    payload = build_outcomes_payload(db_path=db)
    blob = repr(payload).lower()
    for banned in ("buy ", "sell ", "place order", "execute trade", "auto-trade"):
        assert banned not in blob
    # The advisory safety stamps affirm NO execution, never the reverse.
    assert payload["execution_gate"] == "LOCKED"
    assert payload["broker_api_called"] is False
    assert payload.get("broker_order_id", "NONE") == "NONE"
    assert payload["ai_execution_count"] == 0
    assert payload["real_money_ready"] is False
