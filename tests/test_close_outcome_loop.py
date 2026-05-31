"""Close the Outcome Loop Sprint — Phase 2 tests.

Proves the outcome loop closes on REAL ingested OHLCV price bars and stays
honest at every boundary:

* a due snapshot with real entry/exit bars attaches a real-forward y∈{0,1};
* an unelapsed horizon stays pending and never gains a label;
* missing price bars / missing target definition / missing probability are each
  handled with the correct exclusion accounting;
* a mock / fabricated outcome is rejected and an open trade is never labelled;
* N_real_forward grows ONLY for genuinely eligible pairs;
* advisory safety stamps survive every path.

All deterministic and offline — real price bars are seeded into ``signal_events``
exactly as the live ``market_data`` ingestion would.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import persistence
from scripts.decision_probability_snapshot import (
    persist_decision_snapshot,
    build_decision_snapshot,
)
from scripts.attach_due_outcomes import (
    REASON_MISSING_TARGET_DEFINITION,
    REASON_NO_PRICE_EVIDENCE,
    REASON_OPEN_TRADE,
    attach_due_outcomes,
)
from scripts.real_calibration_evidence import extract_datasets
from scripts.real_price_outcome_evidence import (
    build_real_price_evidence,
    load_price_series,
    make_real_price_evidence_provider,
)

_AXES = {"EMS": 0.6, "EQS": 0.55, "DS": 0.45, "LS": 0.5, "EFS": 0.5, "APS": 0.5}
_DECISION_TS = "2026-01-05T00:00:00Z"
_NOW = "2026-05-31T00:00:00Z"
_PRICE_TARGET = "forward_return_ge_threshold"


def _seed_bar(db: Path, symbol: str, ts: str, close: float) -> None:
    eid = f"market_data_{symbol}_{ts}".replace(" ", "_").replace(":", "")
    persistence.insert_signal_event(
        event_id=eid,
        source_name="market_data",
        raw_payload={"symbol": symbol, "timestamp": ts, "close": close,
                     "signal_type": None},
        fetched_at=ts,
        db_path=db,
    )


def _seed_snapshot(
    db: Path,
    sid: str,
    *,
    ticker: str | None = "SPY",
    horizon: float = 5.0,
    ts: str = _DECISION_TS,
    target: str = _PRICE_TARGET,
    axes=_AXES,
) -> str:
    snap = build_decision_snapshot(
        signal_id=sid,
        axes=axes,
        ticker=ticker,
        prediction_horizon_days=horizon,
        target_event_definition=target,
        timestamp_utc=ts,
    )
    persist_decision_snapshot(snap, db)
    return snap["snapshot_id"]


def _seed_spy_window(db: Path, *, entry: float, exit_: float) -> None:
    # Two real bars: one strictly before the decision (entry), one at/just
    # before the +5d horizon close (exit).  Decision ts is 2026-01-05T00:00Z;
    # horizon close is 2026-01-10T00:00Z.
    _seed_bar(db, "SPY", "2026-01-02 00:00:00-05:00", entry)
    _seed_bar(db, "SPY", "2026-01-09 00:00:00-05:00", exit_)


def _assert_locked(summary: dict) -> None:
    assert summary["advisory_only"] is True
    assert summary["execution_gate"] == "LOCKED"
    assert summary["broker_api_called"] is False
    assert summary["ai_execution_count"] == 0
    assert summary["predictive_claim_allowed"] is False


# --- 1. real bars -> y=1 -------------------------------------------------- #

def test_due_snapshot_attaches_real_forward_y_one(tmp_path):
    db = tmp_path / "mvp.db"
    persistence.init_schema(db)
    sid = _seed_snapshot(db, "WIN")
    _seed_spy_window(db, entry=100.0, exit_=110.0)  # +10% -> y=1 at threshold 0
    summary = attach_due_outcomes(
        db_path=db, use_real_price_evidence=True, now_utc=_NOW, write=True,
    )
    assert summary["outcomes_attached"] == 1
    assert summary["n_real_forward_after"] == 1
    rf = extract_datasets(db)["real_forward"]
    assert rf and rf[0]["y"] == 1
    _assert_locked(summary)


# --- 2. real bars -> y=0 -------------------------------------------------- #

def test_due_snapshot_attaches_real_forward_y_zero(tmp_path):
    db = tmp_path / "mvp.db"
    persistence.init_schema(db)
    _seed_snapshot(db, "LOSS")
    _seed_spy_window(db, entry=100.0, exit_=92.0)  # -8% -> y=0 at threshold 0
    summary = attach_due_outcomes(
        db_path=db, use_real_price_evidence=True, now_utc=_NOW, write=True,
    )
    assert summary["outcomes_attached"] == 1
    rf = extract_datasets(db)["real_forward"]
    assert rf and rf[0]["y"] == 0


# --- 3. unelapsed horizon stays pending ----------------------------------- #

def test_unelapsed_horizon_remains_pending(tmp_path):
    db = tmp_path / "mvp.db"
    persistence.init_schema(db)
    # Decision "now" + 30d horizon -> not elapsed at _NOW.
    _seed_snapshot(db, "EARLY", ts=_NOW, horizon=30.0)
    _seed_spy_window(db, entry=100.0, exit_=110.0)
    summary = attach_due_outcomes(
        db_path=db, use_real_price_evidence=True, now_utc=_NOW, write=True,
    )
    assert summary["due_decisions"] == 0
    assert summary["pending_horizon"] == 1
    assert summary["outcomes_attached"] == 0
    assert summary["n_real_forward_after"] == 0


# --- 4. missing price bars excluded --------------------------------------- #

def test_missing_price_evidence_excluded(tmp_path):
    db = tmp_path / "mvp.db"
    persistence.init_schema(db)
    _seed_snapshot(db, "NOBARS", ticker="SPY")
    # No market_data bars seeded -> no real price evidence.
    summary = attach_due_outcomes(
        db_path=db, use_real_price_evidence=True, now_utc=_NOW, write=True,
    )
    assert summary["due_decisions"] == 1
    assert summary["excluded_missing_price"] == 1
    assert summary["outcomes_attached"] == 0
    reasons = [d.get("reason") for d in summary["details"]]
    assert REASON_NO_PRICE_EVIDENCE in reasons


# --- 5. missing target definition excluded -------------------------------- #

def test_missing_target_definition_excluded(tmp_path):
    db = tmp_path / "mvp.db"
    persistence.init_schema(db)
    _seed_snapshot(db, "NOTGT", target="")
    _seed_spy_window(db, entry=100.0, exit_=110.0)
    summary = attach_due_outcomes(
        db_path=db, use_real_price_evidence=True, now_utc=_NOW, write=True,
    )
    assert summary["excluded_missing_target_definition"] == 1
    assert summary["outcomes_attached"] == 0
    reasons = [d.get("reason") for d in summary["details"]]
    assert REASON_MISSING_TARGET_DEFINITION in reasons


# --- 6. missing probability counted but never gate-eligible --------------- #

def test_missing_probability_excluded(tmp_path):
    db = tmp_path / "mvp.db"
    persistence.init_schema(db)
    # No axes -> model_probability is None (NO_SCORE_VECTOR_AT_DECISION).
    _seed_snapshot(db, "NOP", axes={})
    _seed_spy_window(db, entry=100.0, exit_=110.0)
    summary = attach_due_outcomes(
        db_path=db, use_real_price_evidence=True, now_utc=_NOW, write=True,
    )
    assert summary["excluded_missing_probability"] == 1
    # The outcome is recorded but it is NOT calibration-eligible (no p).
    assert extract_datasets(db)["real_forward"] == []
    assert summary["n_real_forward_after"] == 0


# --- 7. mock / fabricated outcome rejected -------------------------------- #

def test_mock_or_fabricated_outcome_rejected(tmp_path):
    db = tmp_path / "mvp.db"
    persistence.init_schema(db)
    sid = _seed_snapshot(db, "MOCK")
    # A provider returning a fabricated (non-real) outcome must not become a
    # real-forward pair.
    fabricated = {sid: {"entry_price": 100.0, "exit_price": 110.0,
                        "is_real_outcome": False, "outcome_kind": "real_forward"}}
    summary = attach_due_outcomes(
        db_path=db, evidence_by_id=fabricated, now_utc=_NOW, write=True,
    )
    assert summary["n_real_forward_after"] == 0
    assert extract_datasets(db)["real_forward"] == []


# --- 8. open / unresolved trade not labelled ------------------------------ #

def test_open_unresolved_trade_not_labelled(tmp_path):
    db = tmp_path / "mvp.db"
    persistence.init_schema(db)
    sid = _seed_snapshot(db, "OPEN")
    evidence = {sid: {"entry_price": 100.0, "exit_price": 130.0, "trade_open": True}}
    summary = attach_due_outcomes(
        db_path=db, evidence_by_id=evidence, now_utc=_NOW, write=True,
    )
    assert summary["outcomes_attached"] == 0
    assert summary["pending"] == 1
    reasons = [d.get("reason") for d in summary["details"]]
    assert REASON_OPEN_TRADE in reasons
    assert extract_datasets(db)["real_forward"] == []


# --- 9. N_real_forward grows only for eligible pairs ---------------------- #

def test_n_real_forward_increments_only_for_eligible_pairs(tmp_path):
    db = tmp_path / "mvp.db"
    persistence.init_schema(db)
    win = _seed_snapshot(db, "W")            # real, priceable -> +1
    nop = _seed_snapshot(db, "NP", axes={})  # no probability -> not eligible
    _seed_snapshot(db, "NOBARS2", ticker="QQQ")  # no bars -> excluded
    _seed_spy_window(db, entry=100.0, exit_=110.0)
    summary = attach_due_outcomes(
        db_path=db, use_real_price_evidence=True, now_utc=_NOW, write=True,
    )
    assert summary["n_real_forward_before"] == 0
    assert summary["n_real_forward_after"] == 1
    assert summary["excluded_missing_probability"] == 1
    assert summary["excluded_missing_price"] == 1


# --- 10. advisory safety preserved ---------------------------------------- #

def test_advisory_safety_stamps_preserved(tmp_path):
    db = tmp_path / "mvp.db"
    persistence.init_schema(db)
    _seed_snapshot(db, "SAFE")
    _seed_spy_window(db, entry=100.0, exit_=110.0)
    summary = attach_due_outcomes(
        db_path=db, use_real_price_evidence=True, now_utc=_NOW, write=True,
    )
    _assert_locked(summary)
    assert summary["human_execution_required"] is True


# --- provider unit -------------------------------------------------------- #

def test_real_price_provider_returns_none_when_horizon_open(tmp_path):
    db = tmp_path / "mvp.db"
    persistence.init_schema(db)
    sid = _seed_snapshot(db, "FUT", ts=_NOW, horizon=30.0)
    _seed_spy_window(db, entry=100.0, exit_=110.0)
    provider = make_real_price_evidence_provider(db, now_utc=_NOW)
    assert provider(sid) is None  # horizon close is in the future


def test_real_price_evidence_never_fabricates(tmp_path):
    db = tmp_path / "mvp.db"
    persistence.init_schema(db)
    snap = {"ticker": "SPY", "timestamp_utc": _DECISION_TS,
            "prediction_horizon_days": 5.0}
    series = load_price_series(db)  # empty — no bars seeded
    assert build_real_price_evidence(snap, series, now_utc=_parse_now()) is None


def _parse_now():
    from datetime import datetime, timezone
    return datetime(2026, 5, 31, tzinfo=timezone.utc)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
