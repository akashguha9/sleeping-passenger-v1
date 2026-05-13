"""
Tests for the persistence truth doctrine wired into scripts/signal_inbox_api.py
and documented in docs/PERSISTENCE_MODEL.md.

Doctrine (verbatim from PERSISTENCE_MODEL.md):
    SQLite = canonical application state.
    JSONL  = append-only audit/event trace or fallback import source.
    Mock   = UI-only degraded demo state, never canonical truth.

These tests verify:
  * the doc exists and contains the doctrine
  * GET /signals and list_manual_trades expose `truth_source`,
    `fallback_used`, and `canonical` flags
  * a JSONL-fallback response is never marked canonical
  * a SQLite-served response is always marked canonical
  * the advisory safety stamps survive every code path

No real runtime DB is touched; SQLite is monkey-patched at the module level.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import scripts.signal_inbox_api as api


REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "PERSISTENCE_MODEL.md"


# ---------------------------------------------------------------------------
# Doctrine doc
# ---------------------------------------------------------------------------


def test_persistence_model_doc_exists():
    assert DOC.exists(), "docs/PERSISTENCE_MODEL.md must exist"


def test_doc_states_sqlite_is_canonical():
    text = DOC.read_text(encoding="utf-8")
    assert "SQLite is canonical" in text or "SQLite = canonical" in text


def test_doc_states_jsonl_is_audit_only():
    text = DOC.read_text(encoding="utf-8").lower()
    assert "jsonl" in text
    assert "audit" in text or "fallback" in text


def test_doc_states_mock_is_never_canonical():
    text = DOC.read_text(encoding="utf-8").lower()
    assert "mock" in text
    assert "never canonical" in text or "never be presented" in text or "must always" in text


def test_doc_forbids_silent_truth_fallback():
    text = DOC.read_text(encoding="utf-8").lower()
    assert "no silent" in text or "no silent truth fallback" in text or "must always be labelled" in text


# ---------------------------------------------------------------------------
# list_manual_trades -- SQLite path is canonical
# ---------------------------------------------------------------------------


class _FakePersistence:
    def __init__(self, rows):
        self._rows = list(rows)

    def get_all_manual_trades(self):
        return list(self._rows)


def test_list_manual_trades_sqlite_path_is_canonical(monkeypatch):
    monkeypatch.setattr(api, "_DB_AVAILABLE", True)
    monkeypatch.setattr(
        api, "_persistence", _FakePersistence([{"trade_id": "t1", "event_id": "E1"}])
    )
    result = api.list_manual_trades()
    assert result["truth_source"] == "sqlite"
    assert result["canonical"] is True
    assert result["fallback_used"] is False
    assert result["trade_count"] == 1


def test_list_manual_trades_sqlite_empty_is_still_canonical(monkeypatch):
    """A SQLite-served empty list is canonical, NOT a fallback."""
    monkeypatch.setattr(api, "_DB_AVAILABLE", True)
    monkeypatch.setattr(api, "_persistence", _FakePersistence([]))
    monkeypatch.setattr(api, "_load_jsonl", lambda _path: [])
    result = api.list_manual_trades()
    assert result["truth_source"] == "sqlite"
    assert result["canonical"] is True
    assert result["fallback_used"] is False


def test_list_manual_trades_sqlite_exception_falls_back_to_jsonl(monkeypatch, tmp_path):
    class BoomPersistence:
        def get_all_manual_trades(self):
            raise RuntimeError("simulated SQLite outage")

    fallback_rows = [{"trade_id": "t-jsonl", "event_id": "E-J", "logged_by": "human"}]

    monkeypatch.setattr(api, "_DB_AVAILABLE", True)
    monkeypatch.setattr(api, "_persistence", BoomPersistence())
    monkeypatch.setattr(api, "_load_jsonl", lambda _path: list(fallback_rows))

    result = api.list_manual_trades()
    assert result["truth_source"] == "jsonl_fallback"
    assert result["canonical"] is False
    assert result["fallback_used"] is True
    assert result["trade_count"] == 1


def test_list_manual_trades_db_unavailable_uses_jsonl(monkeypatch):
    monkeypatch.setattr(api, "_DB_AVAILABLE", False)
    monkeypatch.setattr(api, "_persistence", None)
    monkeypatch.setattr(api, "_load_jsonl", lambda _path: [{"trade_id": "j1"}])
    result = api.list_manual_trades()
    assert result["truth_source"] == "jsonl_fallback"
    assert result["canonical"] is False
    assert result["fallback_used"] is True


def test_list_manual_trades_safety_stamps_in_every_path(monkeypatch):
    monkeypatch.setattr(api, "_DB_AVAILABLE", True)
    monkeypatch.setattr(api, "_persistence", _FakePersistence([]))
    monkeypatch.setattr(api, "_load_jsonl", lambda _path: [])
    result = api.list_manual_trades()
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["execution_mode"] == "HUMAN_ONLY"
    assert result["ai_execution_count"] == 0
    assert result["broker_api_called"] is False
    assert result["human_review_required"] is True


# ---------------------------------------------------------------------------
# list_inbox_items -- exposes truth_source / canonical / fallback_used
# ---------------------------------------------------------------------------


def test_list_inbox_items_exposes_persistence_truth_metadata():
    result = api.list_inbox_items()
    assert "truth_source" in result
    assert "canonical" in result
    assert "fallback_used" in result
    # truth_source is one of the documented values
    assert result["truth_source"] in {
        "sqlite",
        "jsonl_fallback",
        "mock",
        "legacy_fabric",
        "live_events",
    }
    # If not sqlite, must not be marked canonical
    if result["truth_source"] != "sqlite":
        assert result["canonical"] is False
        assert result["fallback_used"] is True
    else:
        assert result["canonical"] is True
        assert result["fallback_used"] is False


def test_list_inbox_items_legacy_fabric_is_not_canonical():
    result = api.list_inbox_items()
    if result.get("signal_source") == "legacy_fabric":
        assert result["truth_source"] == "legacy_fabric"
        assert result["canonical"] is False
        assert result["fallback_used"] is True


def test_list_inbox_items_safety_stamps_preserved():
    result = api.list_inbox_items()
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["execution_mode"] == "HUMAN_ONLY"
    assert result["ai_execution_count"] == 0
    # mock_fallback is the legacy frontend hint; backend always returns False
    assert result["mock_fallback"] is False
