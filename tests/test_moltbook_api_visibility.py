"""
Tests for the Moltbook API default-visibility contract.

  - list_moltbook_entries() defaults to canonical visible-only rows.
  - It exposes raw_total_entries, visible_entries, hidden_ineligible,
    hidden_duplicates, hidden_test_demo, allowed_event_types.
  - include_raw=True returns the full row set including hidden ones.
  - Category distribution computed from visible rows excludes
    test/demo/hidden pollution.
  - Safety stamps preserved on every emitted row.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import scripts.persistence as persistence
import scripts.moltbook_api as moltbook_api
import scripts.moltbook_learning_bridge as bridge


@pytest.fixture(autouse=True)
def _isolate_log(monkeypatch, tmp_path):
    # Keep MOLTBOOK_LOG and _MOLTBOOK_LOG_ORIG aligned so the API's
    # "JSONL path is the production default" guard still passes and the
    # SQLite branch runs against the monkeypatched DB.
    target = tmp_path / "moltbook.jsonl"
    monkeypatch.setattr(moltbook_api, "MOLTBOOK_LOG", target)
    monkeypatch.setattr(moltbook_api, "_MOLTBOOK_LOG_ORIG", target)


@pytest.fixture
def db(monkeypatch, tmp_path: Path) -> Path:
    target = tmp_path / "api.db"
    persistence.init_schema(target)
    monkeypatch.setattr(persistence, "DB_PATH", target)
    return target


def _direct_insert(db: Path, **overrides) -> None:
    """Insert a raw moltbook_entries row, bypassing the bridge.

    Used to simulate legacy pollution (test-thesis rows, hidden duplicates)
    that the API must still classify and exclude from the default view.
    """
    conn = sqlite3.connect(str(db))
    try:
        cols = [d[1] for d in conn.execute("PRAGMA table_info(moltbook_entries)")]
        defaults: dict[str, object] = {
            "entry_id": "MB_FAKE",
            "event_id": "EV_X",
            "ticker": "AAPL",
            "original_signal_thesis": "Real thesis.",
            "ai_interpretation": "",
            "user_reflection": "",
            "final_human_decision": "",
            "manual_trade_log_id": "",
            "outcome": "",
            "mistake_type": "good_signal_good_execution",
            "lesson_learned": "n/a",
            "bias_detected": "",
            "recalibration_note": "",
            "future_rule_update": "",
            "logged_at": "2026-05-27T07:00:00+00:00",
            "advisory_status": "ADVISORY_ONLY",
            "human_review_required": 1,
            "execution_mode": "HUMAN_ONLY",
            "ai_execution_count": 0,
            "trade_id": "MT_X",
            "source_trade_state": "CLOSED_WIN",
            "event_type": "CLOSED_WIN",
            "outcome_quality": "GOOD_PROCESS_WIN",
            "entry_price": 100.0,
            "exit_price": 110.0,
            "exit_quantity": 1.0,
            "stop_loss_price": None,
            "take_profit_price": None,
            "realized_pl": 10.0,
            "booked_percent": None,
            "ride_percent": None,
            "mistake_tags": "",
            "success_tags": "",
            "lesson": "",
            "notes": "",
            "created_at": "2026-05-27T07:00:00+00:00",
            "updated_at": "2026-05-27T07:00:00+00:00",
            "idempotency_key": overrides.get("entry_id") or "MBK_FAKE",
            "learning_direction": "SUCCESS_PATTERN",
            "hidden_from_default_view": 0,
            "hidden_reason": "",
            "is_duplicate": 0,
            "duplicate_of": "",
            "eligibility_reason": "",
        }
        defaults.update(overrides)
        values = [defaults.get(c) for c in cols]
        conn.execute(
            f"INSERT INTO moltbook_entries ({','.join(cols)}) VALUES "
            f"({','.join('?' for _ in cols)})",
            values,
        )
        conn.commit()
    finally:
        conn.close()


def test_default_view_excludes_test_thesis_rows(db):
    _direct_insert(db, entry_id="MB_REAL", ticker="XOM", original_signal_thesis="Real XOM thesis",
                   event_type="STOP_LOSS_HIT", realized_pl=-10.0, exit_price=98.0,
                   mistake_type="stop_loss_breach")
    _direct_insert(db, entry_id="MB_TEST", ticker="SPY", original_signal_thesis="test",
                   event_type="CLOSED_WIN", realized_pl=2.0, exit_price=452.0)
    resp = moltbook_api.list_moltbook_entries()
    assert resp["raw_total_entries"] == 2
    assert resp["visible_entries"] == 1
    assert resp["hidden_test_demo"] == 1
    assert all(e.get("original_signal_thesis") != "test" for e in resp["items"])


def test_default_view_excludes_hidden_duplicates(db):
    _direct_insert(db, entry_id="MB_VIS", ticker="AAPL")
    _direct_insert(db, entry_id="MB_HIDDEN", ticker="AAPL",
                   hidden_from_default_view=1, is_duplicate=1,
                   hidden_reason="DUPLICATE_OF:MB_VIS")
    resp = moltbook_api.list_moltbook_entries()
    assert resp["raw_total_entries"] == 2
    assert resp["visible_entries"] == 1
    assert resp["hidden_duplicates"] == 1


def test_include_raw_returns_all_rows(db):
    _direct_insert(db, entry_id="MB_VIS", ticker="AAPL")
    _direct_insert(db, entry_id="MB_HIDDEN", ticker="AAPL",
                   hidden_from_default_view=1,
                   hidden_reason="SKIP_TEST_DEMO_FIXTURE")
    resp = moltbook_api.list_moltbook_entries(include_raw=True)
    assert resp["raw_total_entries"] == 2
    assert len(resp["items"]) == 2
    assert resp["include_raw"] is True


def test_response_reports_allowed_event_types(db):
    _direct_insert(db, entry_id="MB_VIS", ticker="AAPL")
    resp = moltbook_api.list_moltbook_entries()
    assert "STOP_LOSS_HIT" in resp["allowed_event_types"]
    assert "CLOSED_WIN" in resp["allowed_event_types"]
    assert "BREAKEVEN_EXIT" in resp["allowed_event_types"]
    assert "PRICE_MARK" not in resp["allowed_event_types"]


def test_safety_stamps_on_visible_rows(db):
    _direct_insert(db, entry_id="MB_VIS", ticker="AAPL")
    resp = moltbook_api.list_moltbook_entries()
    assert resp["advisory_status"] == "ADVISORY_ONLY"
    assert resp["ai_execution_count"] == 0
    for row in resp["items"]:
        assert row["advisory_status"] == "ADVISORY_ONLY"
        assert row["execution_mode"] == "HUMAN_ONLY"
        assert row["ai_execution_count"] == 0


def test_eligibility_helper_constants_exported():
    assert bridge.ELIGIBLE_STOP_LOSS_HIT in bridge.ELIGIBILITY_REASONS
    assert bridge.SKIP_TEST_DEMO_FIXTURE in bridge.ELIGIBILITY_REASONS
