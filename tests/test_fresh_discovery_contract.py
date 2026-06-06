"""Hard tests for the Fresh Discovery Contract.

These prove that stale/static/fallback/prior/Moltbook/fixture/seed/prompt-example
names can NEVER appear as fresh discovery, and that the system fails closed
(``NO_FRESH_DISCOVERY_GENERATED``) rather than padding the board with old names.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from daily_payload_factory import write_daily_payload, write_stale_ledger

from scripts.daily_payload import load_daily_payload
from scripts.daily_synthesis_pipeline import run_daily_synthesis
from scripts.fresh_discovery_contract import (
    BLOCKED_EVIDENCE_TYPES,
    VERIFIED_LIVE,
    VIOLATION_CODE,
    DiscoveryProvenanceViolation,
    assert_no_provenance_violation,
    build_fresh_discovery_contract,
    candidate_is_stale,
    detect_provenance_violations,
    fresh_discovery_allowed,
    record_is_live,
)
from scripts.fresh_market_discovery import build_fresh_market_discovery
from scripts.portfolio_truth_gate import build_portfolio_truth_gate

SESSION = "2026-06-07"
OLD_NAMES = ("NVDA", "AMZN", "RHM.DE", "AIR.PA", "SAP.DE", "GLD", "ZIM", "NOC", "EWG", "INFY", "BHP")


def _live_mover(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "is_live": True,
        "source_health": "VERIFIED_LIVE",
        "provider": "yahoo_live",
        "freshness": "FRESH_TODAY",
        "timestamp_utc": f"{SESSION}T13:00:00Z",
        "why_today": "Live gap + volume confirmed today.",
    }


def _static_mover(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "is_live": False,
        "source_health": "UNVERIFIED",
        "provider": "STATIC_UNIVERSE_FALLBACK",
        "freshness": "UNVERIFIED",
    }


def _build(base: Path, *, open_positions=None, signal_ledger=None, model_candidates=None):
    payload = load_daily_payload(base)
    if open_positions is not None or signal_ledger is not None:
        op, sl = write_stale_ledger(base.parent / "stale", open_positions or [], signal_ledger or [])
        gate = build_portfolio_truth_gate(payload=payload, open_positions_path=op, signal_ledger_path=sl)
        disc = build_fresh_market_discovery(
            payload=payload, truth_gate=gate, model_candidates=model_candidates, signal_ledger_path=sl
        )
    else:
        gate = build_portfolio_truth_gate(payload=payload)
        disc = build_fresh_market_discovery(payload=payload, truth_gate=gate, model_candidates=model_candidates)
    return payload, gate, disc, disc["fresh_discovery"]


# ---------------------------------------------------------------------------
# A. No live data + static fallback exists -> empty board, fail closed.
# ---------------------------------------------------------------------------

def test_A_no_live_data_yields_no_fresh_discovery(tmp_path: Path) -> None:
    base = write_daily_payload(
        tmp_path / "p", run_date=SESSION, movers=[], news=[], filings=[],
        source_health="MISSING_OR_UNVERIFIED",
    )
    result = run_daily_synthesis(payload_dir=base)
    c = result["fresh_discovery_contract"]

    assert c["status"] == "NO_FRESH_DISCOVERY_GENERATED"
    assert c["fresh_discovery_board"] == []
    assert c["live_candidate_count"] == 0

    nfd = c["no_fresh_discovery"]
    assert nfd["status"] == "NO_FRESH_DISCOVERY_GENERATED"
    assert nfd["live_candidate_count"] == 0
    assert set(nfd["failed_payloads"]) == {
        "today_market_snapshot", "today_price_movers", "today_news_events", "today_filings_events",
    }
    assert nfd["next_required_fix"]
    assert nfd["fallback_candidate_count"] >= 1

    # The exact names the operator complained about are never fresh candidates.
    for name in OLD_NAMES:
        assert name not in c["fresh_discovery_board"]
    # But they ARE available in the research universe — proving they were
    # present and deliberately excluded, not merely absent.
    research = set(result["fresh_market_discovery"]["discovery_universe"])
    assert {"NVDA", "AMZN", "GLD"} <= research


def test_A_static_names_are_blocked_fallback(tmp_path: Path) -> None:
    base = write_daily_payload(tmp_path / "p", run_date=SESSION, movers=[], source_health="MISSING_OR_UNVERIFIED")
    # Isolate the historical Moltbook ledger so these names classify purely on
    # static-universe membership (otherwise NVDA/AMZN/GLD also appear in the
    # real signal ledger and would classify MOLTBOOK_MEMORY — also blocked).
    _payload, _gate, _disc, c = _build(base, open_positions=[], signal_ledger=[])
    prov = {p["ticker"]: p for p in c["provenance_report"]}
    for name in ("NVDA", "AMZN", "GLD"):
        assert name in prov
        assert prov[name]["evidence_type"] == "STATIC_UNIVERSE_FALLBACK"
        assert prov[name]["from_fallback"] is True
        assert prov[name]["allowed_in_fresh_discovery"] is False
        assert name in c["blocked_fallback_names"]


# ---------------------------------------------------------------------------
# B. Wiped trade logs -> no verified holdings inferred, no prior candidates current.
# ---------------------------------------------------------------------------

def test_B_wiped_logs_no_holdings_no_prior_candidates(tmp_path: Path) -> None:
    base = write_daily_payload(
        tmp_path / "p", run_date=SESSION, verified=[], closed=[], sold=[], movers=[],
        yesterday_final=["OLDZ"], yesterday_watchlist=["OLDW"],
    )
    payload, gate, _disc, c = _build(base)

    # No holdings inferred from wiped logs.
    assert gate["verified_open_holdings"] == []
    assert gate["can_manage_positions"] is False

    prov = {p["ticker"]: p for p in c["provenance_report"]}
    # Prior candidates are present in the universe but are NOT current candidates.
    assert prov["OLDZ"]["evidence_type"] == "PRIOR_CANDIDATE"
    assert prov["OLDZ"]["from_cache"] is True
    assert prov["OLDZ"]["allowed_in_fresh_discovery"] is False
    assert "OLDZ" not in c["fresh_discovery_board"]
    assert "OLDW" not in c["fresh_discovery_board"]
    assert c["status"] == "NO_FRESH_DISCOVERY_GENERATED"


# ---------------------------------------------------------------------------
# C. Moltbook old tickers -> learning/review only, blocked from fresh discovery
#    unless revalidated today.
# ---------------------------------------------------------------------------

def test_C_moltbook_old_ticker_excluded(tmp_path: Path) -> None:
    base = write_daily_payload(tmp_path / "p", run_date=SESSION, movers=[])
    _payload, _gate, _disc, c = _build(
        base, open_positions=[], signal_ledger=[{"ticker": "OLDMOLT", "status": "WATCHLIST"}]
    )
    prov = {p["ticker"]: p for p in c["provenance_report"]}
    assert "OLDMOLT" in prov
    assert prov["OLDMOLT"]["from_moltbook"] is True
    assert prov["OLDMOLT"]["evidence_type"] == "MOLTBOOK_MEMORY"
    assert prov["OLDMOLT"]["allowed_in_fresh_discovery"] is False
    assert "OLDMOLT" not in c["fresh_discovery_board"]


def test_C_moltbook_ticker_revalidated_today_enters(tmp_path: Path) -> None:
    base = write_daily_payload(tmp_path / "p", run_date=SESSION, movers=[_live_mover("OLDMOLT")])
    _payload, _gate, _disc, c = _build(
        base, open_positions=[], signal_ledger=[{"ticker": "OLDMOLT", "status": "WATCHLIST"}]
    )
    prov = {p["ticker"]: p for p in c["provenance_report"]}
    # Revalidated by fresh live evidence today -> may enter, history still recorded.
    assert prov["OLDMOLT"]["is_live"] is True
    assert prov["OLDMOLT"]["from_moltbook"] is True
    assert prov["OLDMOLT"]["allowed_in_fresh_discovery"] is True
    assert "OLDMOLT" in c["fresh_discovery_board"]
    assert c["status"] == "FRESH_DISCOVERY_OK"


# ---------------------------------------------------------------------------
# D. One live candidate -> only that candidate appears; static fallback excluded.
# ---------------------------------------------------------------------------

def test_D_single_live_candidate_only(tmp_path: Path) -> None:
    base = write_daily_payload(
        tmp_path / "p", run_date=SESSION,
        movers=[_live_mover("PLTR"), _static_mover("NVDA"), _static_mover("RHM.DE")],
        source_health="OK",
    )
    _payload, _gate, _disc, c = _build(base)

    assert c["status"] == "FRESH_DISCOVERY_OK"
    assert c["fresh_discovery_board"] == ["PLTR"]
    assert c["live_candidate_count"] == 1

    prov = {p["ticker"]: p for p in c["provenance_report"]}
    assert prov["PLTR"]["evidence_type"] == "LIVE_PRICE_MOVER"
    assert prov["PLTR"]["source_health"] == VERIFIED_LIVE
    assert prov["PLTR"]["live_evidence_count"] == 1

    for name in OLD_NAMES:
        assert name not in c["fresh_discovery_board"]
    # No provenance violation on a clean live board.
    assert c["discovery_provenance_violation"] is False


# ---------------------------------------------------------------------------
# E. Prompt-example / model-suggested tickers must not leak into output.
# ---------------------------------------------------------------------------

def test_E_prompt_examples_do_not_leak(tmp_path: Path) -> None:
    base = write_daily_payload(tmp_path / "p", run_date=SESSION, movers=[_live_mover("PLTR")], source_health="OK")
    _payload, _gate, _disc, c = _build(base, model_candidates=["EXAMPLEX"])

    prov = {p["ticker"]: p for p in c["provenance_report"]}
    assert "EXAMPLEX" in prov, "model/prompt name should be in the research universe"
    assert prov["EXAMPLEX"]["evidence_type"] == "EXAMPLE_PROMPT"
    assert prov["EXAMPLEX"]["allowed_in_fresh_discovery"] is False
    assert "EXAMPLEX" not in c["fresh_discovery_board"]
    assert c["fresh_discovery_board"] == ["PLTR"]


def test_E_explicit_example_prompt_tickers_blocked(tmp_path: Path) -> None:
    base = write_daily_payload(tmp_path / "p", run_date=SESSION, movers=[_live_mover("PLTR")], source_health="OK")
    payload = load_daily_payload(base)
    gate = build_portfolio_truth_gate(payload=payload)
    # Force EXMP into the universe so the contract must classify it.
    disc = build_fresh_market_discovery(payload=payload, truth_gate=gate, model_candidates=["EXMP"])
    c = build_fresh_discovery_contract(
        payload, disc, gate, current_session_date=SESSION,
        model_candidates=["EXMP"], example_prompt_tickers=["EXMP"],
    )
    prov = {p["ticker"]: p for p in c["provenance_report"]}
    assert prov["EXMP"]["evidence_type"] == "EXAMPLE_PROMPT"
    assert "EXMP" not in c["fresh_discovery_board"]


def test_E_fixture_and_seed_records_blocked(tmp_path: Path) -> None:
    base = write_daily_payload(
        tmp_path / "p", run_date=SESSION,
        movers=[
            {"ticker": "FIXX", "is_live": True, "source_health": "VERIFIED_LIVE", "provider": "TEST_FIXTURE", "freshness": "FRESH_TODAY"},
            {"ticker": "SEEDX", "is_live": True, "source_health": "VERIFIED_LIVE", "provider": "SEED_DATA", "freshness": "FRESH_TODAY"},
        ],
        source_health="OK",
    )
    _payload, _gate, _disc, c = _build(base)
    prov = {p["ticker"]: p for p in c["provenance_report"]}
    # Even though these rows CLAIM is_live + VERIFIED_LIVE, the synthetic provider
    # marker forces them out of fresh discovery (fail-closed).
    assert prov["FIXX"]["evidence_type"] == "TEST_FIXTURE"
    assert prov["FIXX"]["is_live"] is False
    assert prov["SEEDX"]["evidence_type"] == "SEED_DATA"
    assert "FIXX" not in c["fresh_discovery_board"]
    assert "SEEDX" not in c["fresh_discovery_board"]


# ---------------------------------------------------------------------------
# 8. Provenance report — every output ticker carries the full provenance schema.
# ---------------------------------------------------------------------------

def test_provenance_report_schema(tmp_path: Path) -> None:
    base = write_daily_payload(
        tmp_path / "p", run_date=SESSION, movers=[_live_mover("PLTR"), _static_mover("NVDA")], source_health="OK"
    )
    _payload, _gate, _disc, c = _build(base)
    required = {
        "ticker", "source_payload", "source_health", "is_live", "generated_at",
        "evidence_type", "live_evidence_count", "last_live_seen_date",
        "from_cache", "from_fallback", "from_moltbook", "from_trade_log",
        "allowed_in_fresh_discovery", "exclusion_reason",
    }
    assert c["provenance_report"], "provenance report must not be empty"
    for prov in c["provenance_report"]:
        assert required <= set(prov.keys()), f"missing fields in {prov['ticker']}"
        if not prov["allowed_in_fresh_discovery"]:
            assert prov["exclusion_reason"], f"{prov['ticker']} blocked without a reason"


# ---------------------------------------------------------------------------
# 9. Regression guard — DISCOVERY_PROVENANCE_VIOLATION fails closed.
# ---------------------------------------------------------------------------

def test_regression_guard_detects_contaminated_board() -> None:
    contaminated = [
        {"ticker": "NVDA", "from_fallback": True, "from_cache": False, "is_live": False,
         "source_health": "UNVERIFIED", "evidence_type": "STATIC_UNIVERSE_FALLBACK"},
    ]
    violations = detect_provenance_violations(contaminated)
    assert violations
    assert violations[0]["code"] == VIOLATION_CODE
    assert violations[0]["ticker"] == "NVDA"


def test_assert_no_provenance_violation_raises() -> None:
    bad_contract = {
        "discovery_provenance_violation": True,
        "provenance_violations": [{"ticker": "NVDA", "violations": ["from_fallback"], "code": VIOLATION_CODE}],
    }
    with pytest.raises(DiscoveryProvenanceViolation):
        assert_no_provenance_violation(bad_contract)


def test_clean_live_board_has_no_violation(tmp_path: Path) -> None:
    base = write_daily_payload(tmp_path / "p", run_date=SESSION, movers=[_live_mover("PLTR")], source_health="OK")
    _payload, _gate, _disc, c = _build(base)
    assert c["discovery_provenance_violation"] is False
    assert c["provenance_violations"] == []
    assert_no_provenance_violation(c)  # must not raise


# ---------------------------------------------------------------------------
# 6. Stale-name quarantine.
# ---------------------------------------------------------------------------

def test_stale_quarantine_lists_blocked_names(tmp_path: Path) -> None:
    base = write_daily_payload(
        tmp_path / "p", run_date=SESSION, movers=[_live_mover("PLTR"), _static_mover("NVDA")], source_health="OK"
    )
    _payload, _gate, _disc, c = _build(base)
    assert "NVDA" in c["stale_revalidation_needed"]
    assert "PLTR" not in c["stale_revalidation_needed"]


def test_candidate_is_stale_predicate() -> None:
    fresh = {"source_health": VERIFIED_LIVE, "is_live": True, "last_live_seen_date": SESSION}
    stale_old = {"source_health": VERIFIED_LIVE, "is_live": True, "last_live_seen_date": "2026-06-01"}
    not_live = {"source_health": "UNVERIFIED", "is_live": False, "last_live_seen_date": None}
    assert candidate_is_stale(fresh, SESSION) is False
    assert candidate_is_stale(stale_old, SESSION) is True
    assert candidate_is_stale(not_live, SESSION) is True


# ---------------------------------------------------------------------------
# Unit-level predicates.
# ---------------------------------------------------------------------------

def test_record_is_live_fail_closed() -> None:
    assert record_is_live(_live_mover("PLTR")) is True
    assert record_is_live(_static_mover("NVDA")) is False
    # Claims live but unverified health -> not live.
    assert record_is_live({"ticker": "X", "is_live": True, "source_health": "UNVERIFIED"}) is False
    # Claims live + verified but a stale freshness marker -> not live.
    assert record_is_live({"ticker": "X", "is_live": True, "source_health": "VERIFIED_LIVE", "provider": "yahoo", "freshness": "UNVERIFIED"}) is False


def test_fresh_discovery_allowed_predicate() -> None:
    good = {
        "source_health": VERIFIED_LIVE, "is_live": True, "last_live_seen_date": SESSION,
        "evidence_type": "LIVE_PRICE_MOVER", "live_evidence_count": 1,
        "from_fallback": False, "from_cache": False,
    }
    assert fresh_discovery_allowed(good, SESSION) is True
    for evil in BLOCKED_EVIDENCE_TYPES:
        bad = dict(good, evidence_type=evil)
        assert fresh_discovery_allowed(bad, SESSION) is False
    assert fresh_discovery_allowed(dict(good, from_fallback=True), SESSION) is False
    assert fresh_discovery_allowed(dict(good, last_live_seen_date="2026-06-01"), SESSION) is False
    assert fresh_discovery_allowed(dict(good, source_health="OK"), SESSION) is False
