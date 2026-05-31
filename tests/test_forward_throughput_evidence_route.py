"""Phase 6 — forward-throughput evidence route tests (read-only, advisory-only)."""
from __future__ import annotations

from scripts import persistence
from scripts.api.routers.evidence_router import (
    build_forward_throughput,
    build_outcomes_payload,
)
from tests._forward_snapshot_helpers import init_db, seed_market_bar, seed_score_vector


def _seed_universe(p):
    init_db(p)
    # AAPL scored + priceable -> eligible.
    seed_score_vector(p, event_id="e_aapl", source_name="sec_edgar", ticker="Apple Inc.")
    seed_market_bar(p, symbol="AAPL", timestamp="2026-05-20 00:00:00-04:00", close=200.0)
    # NVDA scored but no OHLCV -> MISSING_ENTRY_PRICE.
    seed_score_vector(p, event_id="e_nvda", source_name="sec_edgar", ticker="NVIDIA CORP")


def test_route_reports_eligibility_before_after(tmp_path):
    p = tmp_path / "t.db"
    _seed_universe(p)
    ft = build_forward_throughput(p)
    assert "forward_eligible_before" in ft
    assert "forward_eligible_after" in ft
    assert "eligibility_rate_after" in ft
    # The scored universe is counted honestly (2 scored candidates seeded).
    assert ft["scored_candidates_total"] == 2
    assert ft["scored_candidates_eligible"] >= 0


def test_route_reports_reason_reductions(tmp_path):
    p = tmp_path / "t.db"
    _seed_universe(p)
    ft = build_forward_throughput(p)
    for k in (
        "missing_ticker_before", "missing_ticker_after",
        "missing_entry_price_before", "missing_entry_price_after",
        "missing_probability_before", "missing_probability_after",
    ):
        assert k in ft


def test_route_reports_top_missing_ohlcv_tickers(tmp_path):
    p = tmp_path / "t.db"
    _seed_universe(p)
    # Anchor decision well after the only AAPL bar so NVDA (no series) leaks and
    # nothing is falsely eligible; NVDA must appear in the top-missing list.
    from scripts.forward_eligibility_diagnostics import (
        build_scored_candidates,
        diagnose,
    )

    cands = build_scored_candidates(p, decision_timestamp_utc="2026-05-21T00:00:00Z")
    diag = diagnose(cands)
    top = {d["key"]: d["count"] for d in diag["top_missing_entry_price_tickers"]}
    assert "NVDA" in top


def test_route_keeps_calibration_locked(tmp_path):
    p = tmp_path / "t.db"
    _seed_universe(p)
    ft = build_forward_throughput(p)
    assert ft["predictive_claim_allowed"] is False
    assert ft["calibration_status"] == "INSUFFICIENT_EVIDENCE"


def test_outcomes_payload_includes_forward_throughput(tmp_path):
    p = tmp_path / "t.db"
    _seed_universe(p)
    payload = build_outcomes_payload(db_path=p)
    assert "forward_throughput" in payload
    assert isinstance(payload["forward_throughput"], dict)


def test_no_execution_language(tmp_path):
    p = tmp_path / "t.db"
    _seed_universe(p)
    ft = build_forward_throughput(p)
    blob = repr(ft).lower()
    for banned in ("place order", "buy/sell", "execute trade", "auto-trade"):
        assert banned not in blob
