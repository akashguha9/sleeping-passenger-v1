"""H1 regression: secondary journal write paths fail loud, never silent.

Sprint 1 (F1/F2) fixed the manual-trade/reconcile/cancel hot paths but
deliberately left the audit's secondary swallows: ``add_user_reflection``,
``add_ai_discussion_summary``, ``mark_signal`` (signal_inbox_api) and
``log_moltbook_entry`` (moltbook_api) still returned success-shaped
responses when the SQLite insert raised.  A lost reflection/lesson/decision
corrupts the calibration dataset exactly like a lost trade.

Contract per site (same as F1):
* service returns ``status="error"`` / ``reason="db_write_failed"`` with
  the advisory stamps;
* the API surfaces a stamped HTTP 500;
* the journal write-failure counter increments so /health/full degrades.
"""
from __future__ import annotations

import sqlite3

import pytest

import scripts.moltbook_api as moltbook_api
import scripts.signal_inbox_api as sia


def _boom(*_a, **_k):
    raise sqlite3.OperationalError("database is locked")


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(sia, "REFLECTIONS_LOG", tmp_path / "ref.jsonl")
    monkeypatch.setattr(sia, "AI_SUMMARIES_LOG", tmp_path / "ai.jsonl")
    monkeypatch.setattr(sia, "INBOX_STATES_LOG", tmp_path / "inbox.jsonl")
    # Patch BOTH the live path and the sentinel so the DB branch (guarded
    # by MOLTBOOK_LOG == _MOLTBOOK_LOG_ORIG) still fires while the JSONL
    # write stays isolated in tmp.
    monkeypatch.setattr(moltbook_api, "MOLTBOOK_LOG", tmp_path / "molt.jsonl")
    monkeypatch.setattr(
        moltbook_api, "_MOLTBOOK_LOG_ORIG", tmp_path / "molt.jsonl"
    )
    sia._reset_db_write_failures()
    moltbook_api._reset_db_write_failures()
    yield
    sia._reset_db_write_failures()
    moltbook_api._reset_db_write_failures()


def _assert_error_shape(result, *, expect_gate=True):
    assert result["status"] == "error"
    assert result["reason"] == "db_write_failed"
    assert result["broker_api_called"] is False
    assert result["ai_execution_count"] == 0
    if expect_gate:
        assert result["execution_gate"] == "LOCKED"


# ---------------------------------------------------------------------------
# Service level
# ---------------------------------------------------------------------------


def test_add_user_reflection_db_failure_is_loud(monkeypatch):
    monkeypatch.setattr(sia._persistence, "insert_reflection", _boom)
    result = sia.add_user_reflection(
        "EVT_H1A", "lesson: do not revenge trade", author="human"
    )
    _assert_error_shape(result)
    assert sia.db_write_failure_count() == 1


def test_add_ai_summary_db_failure_is_loud(monkeypatch):
    monkeypatch.setattr(sia._persistence, "insert_ai_summary", _boom)
    result = sia.add_ai_discussion_summary(
        "EVT_H1B", "summary text", model_label="test-model"
    )
    _assert_error_shape(result)
    assert sia.db_write_failure_count() == 1


def test_mark_signal_db_failure_is_loud(monkeypatch):
    monkeypatch.setattr(sia._persistence, "insert_signal_decision", _boom)
    result = sia.mark_signal("EVT_H1C", "watchlist")
    _assert_error_shape(result)
    assert sia.db_write_failure_count() == 1


def test_log_moltbook_entry_db_failure_is_loud(monkeypatch):
    monkeypatch.setattr(
        moltbook_api._persistence, "insert_moltbook_entry", _boom
    )
    result = moltbook_api.log_moltbook_entry(
        event_id="EVT_H1D",
        ticker="BTC",
        original_signal_thesis="thesis",
        ai_interpretation="interp",
        user_reflection="reflection",
        final_human_decision="passed",
        outcome="UNKNOWN",
        mistake_type="trade_loss",
        lesson_learned="lesson",
    )
    _assert_error_shape(result, expect_gate=False)
    assert moltbook_api.db_write_failure_count() == 1


def test_success_paths_unchanged(monkeypatch):
    """Guard: with the DB unavailable-by-flag the JSONL fallback still works."""
    monkeypatch.setattr(sia, "_DB_AVAILABLE", False)
    r = sia.add_user_reflection("EVT_OK", "fine", author="human")
    assert r["status"] == "logged"
    assert sia.db_write_failure_count() == 0


# ---------------------------------------------------------------------------
# HTTP level
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    import scripts.api_server as srv

    return TestClient(srv.app, raise_server_exceptions=False)


def _assert_stamped_500(r):
    assert r.status_code == 500
    body = r.json()
    assert body["execution_gate"] == "LOCKED"
    assert body["broker_api_called"] is False
    assert (body.get("detail") or {}).get("reason") == "db_write_failed"


def test_post_reflection_db_failure_is_stamped_500(client, monkeypatch):
    monkeypatch.setattr(sia._persistence, "insert_reflection", _boom)
    r = client.post(
        "/signals/EVT_H1A/reflection",
        json={"reflection_text": "lesson", "author": "human"},
    )
    _assert_stamped_500(r)


def test_post_ai_summary_db_failure_is_stamped_500(client, monkeypatch):
    monkeypatch.setattr(sia._persistence, "insert_ai_summary", _boom)
    r = client.post(
        "/signals/EVT_H1B/ai-summary",
        json={"summary_text": "summary", "model_label": "m"},
    )
    _assert_stamped_500(r)


def test_post_decision_db_failure_is_stamped_500(client, monkeypatch):
    monkeypatch.setattr(sia._persistence, "insert_signal_decision", _boom)
    r = client.post("/signals/EVT_H1C/decision", json={"status": "watchlist"})
    _assert_stamped_500(r)


def test_post_moltbook_db_failure_is_stamped_500(client, monkeypatch):
    monkeypatch.setattr(
        moltbook_api._persistence, "insert_moltbook_entry", _boom
    )
    r = client.post(
        "/moltbook",
        json={
            "event_id": "EVT_H1D",
            "ticker": "BTC",
            "original_signal_thesis": "thesis",
            "ai_interpretation": "interp",
            "user_reflection": "reflection",
            "final_human_decision": "passed",
            "outcome": "UNKNOWN",
            "mistake_type": "trade_loss",
            "lesson_learned": "lesson",
        },
    )
    _assert_stamped_500(r)


def test_health_degrades_on_secondary_write_failure(client, monkeypatch):
    monkeypatch.setattr(sia._persistence, "insert_reflection", _boom)
    client.post(
        "/signals/EVT_H1E/reflection",
        json={"reflection_text": "x", "author": "human"},
    )
    h = client.get("/health/full").json()
    assert h["db_write_failures_total"] >= 1
    assert h["degraded"] is True
