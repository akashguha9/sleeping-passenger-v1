"""Integration tests: Market Titration wiring into the Signal Inbox and API.

Covers: bridge per-event provenance (event_timestamps/event_sources),
inbox-item decoration, list-level aggregate counts, backward compatibility
for legacy items without per-event data, and the /api/titration/summary
endpoint contract.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scripts.signal_inbox_api import (
    _decorate_with_titration_state,
    _TITRATION_DEFAULT_FIELDS,
)
from scripts.signal_inbox_bridge import promote_signal_events_to_inbox
from scripts.market_titration_engine import TITRATION_STATES

NOW = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)


def _iso(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


def _fresh_now_iso(hours_ago: float) -> str:
    return (
        datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    ).isoformat()


# ---------------------------------------------------------------------------
# Bridge: per-event provenance
# ---------------------------------------------------------------------------


def test_bridge_emits_event_timestamps_and_sources(monkeypatch):
    import scripts.persistence as persistence

    rows = [
        {
            "event_id": f"EV_{i}",
            "source_name": "polymarket",
            "fetched_at": _fresh_now_iso(float(i) * 2.0 + 0.5),
            "raw_payload": {"title": f"Ticker ACME event {i}", "symbol": "ACME"},
        }
        for i in range(4)
    ]
    monkeypatch.setattr(
        persistence, "get_signal_events", lambda **kwargs: rows
    )
    items = promote_signal_events_to_inbox(hours=72, limit=50)
    assert items, "bridge should promote the stubbed events"
    grouped = max(items, key=lambda it: it.get("event_count", 0))
    assert "event_timestamps" in grouped
    assert "event_sources" in grouped
    assert len(grouped["event_timestamps"]) == grouped["event_count"]
    assert len(grouped["event_sources"]) == len(grouped["event_timestamps"])
    # Oldest-first ordering
    assert grouped["event_timestamps"] == sorted(grouped["event_timestamps"])
    assert set(grouped["event_sources"]) == {"polymarket"}


# ---------------------------------------------------------------------------
# Decoration
# ---------------------------------------------------------------------------


def _rich_item() -> dict:
    hours = [30.0, 20.0, 10.0, 4.0, 1.0]
    return {
        "event_id": "EVT_RICH",
        "ticker": "RICH",
        "event_timestamps": [_iso(h) for h in hours],
        "event_sources": ["news", "polymarket", "news", "official_filing", "news"],
        "event_count": len(hours),
        "cross_source_support_count": 3,
        "duplicate_suppressed_count": 0,
        "persistence_score": 0.6,
        "contamination_score": 0.1,
        "chaos_sensitivity_score": 0.2,
        "observed_at": _iso(1.0),
    }


def test_decoration_adds_titration_fields_and_safety():
    out = _decorate_with_titration_state(_rich_item())
    assert out["titration_state"] in TITRATION_STATES
    assert out["titration_available"] is True
    t = out["titration"]
    assert isinstance(t, dict)
    assert t["score_semantics"] == "heuristic_bounded_score_not_probability"
    assert t["scoring_version"] == "titration_v1"
    # Safety invariants re-stamped after enrichment.
    assert out["advisory_status"] == "ADVISORY_ONLY"
    assert out["execution_gate"] == "LOCKED"
    assert out["broker_api_called"] is False
    assert out["ai_execution_count"] == 0
    assert out["execution_permission"] is False
    assert out["can_execute"] is False


def test_decoration_backward_compatible_with_legacy_item():
    # Legacy inbox items (no per-event lists) must degrade, not crash.
    legacy = {
        "event_id": "EVT_LEGACY",
        "ticker": "LEG",
        "observed_at": _iso(2.0),
        "priority_score": 0.4,
    }
    out = _decorate_with_titration_state(legacy)
    assert out["titration_state"] in TITRATION_STATES
    # Single representative event -> low sufficiency, never PRIMED/LOADING.
    assert out["titration_state"] not in {"PRIMED", "LOADING"}
    assert out["titration"]["data_sufficiency"] in {"low", "moderate", "insufficient"}


def test_decoration_never_raises_on_garbage():
    out = _decorate_with_titration_state({"event_timestamps": object()})
    assert out["titration_state"] == "INSUFFICIENT_DATA"
    assert out["advisory_status"] == "ADVISORY_ONLY"


def test_default_fields_contract():
    assert _TITRATION_DEFAULT_FIELDS["titration_state"] == "INSUFFICIENT_DATA"
    assert _TITRATION_DEFAULT_FIELDS["titration_available"] is False
    assert _TITRATION_DEFAULT_FIELDS["titration"] is None


# ---------------------------------------------------------------------------
# List-level aggregates
# ---------------------------------------------------------------------------


def test_list_inbox_items_exposes_titration_counts(monkeypatch):
    import scripts.persistence as persistence

    rows = [
        {
            "event_id": f"EV_{i}",
            "source_name": "polymarket",
            "fetched_at": _fresh_now_iso(float(i) + 0.5),
            "raw_payload": {"title": f"Ticker ACME event {i}", "symbol": "ACME"},
        }
        for i in range(3)
    ]
    monkeypatch.setattr(persistence, "get_signal_events", lambda **kwargs: rows)
    from scripts.signal_inbox_api import list_inbox_items

    result = list_inbox_items(hours=72, limit=50)
    assert "titration_state_counts" in result
    assert "titration_unavailable_count" in result
    counts = result["titration_state_counts"]
    assert isinstance(counts, dict)
    assert sum(counts.values()) == result["item_count"]
    for state in counts:
        assert state in TITRATION_STATES
    for item in result["items"]:
        assert "titration_state" in item


# ---------------------------------------------------------------------------
# API endpoint contract
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    try:
        from fastapi.testclient import TestClient
    except ImportError:  # pragma: no cover
        pytest.skip("fastapi test client unavailable")
    import scripts.api_server as srv

    return TestClient(srv.app)


def test_titration_summary_endpoint_contract(client):
    resp = client.get("/api/titration/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["operation"] == "titration_summary"
    assert body["advisory_status"] == "ADVISORY_ONLY"
    assert body["human_review_required"] is True
    assert body["ai_execution_count"] == 0
    assert body["score_semantics"] == "heuristic_bounded_score_not_probability"
    assert body["schema_version"]
    assert body["scoring_version"] == "titration_v1"
    assert isinstance(body["titration_state_counts"], dict)
    assert isinstance(body["top_pre_alpha_gap_candidates"], list)
    assert len(body["top_pre_alpha_gap_candidates"]) <= 10
    assert set(body["operational_states"]) == set(TITRATION_STATES)
    # Reserved states are declared, and never appear in live counts.
    for reserved in body["reserved_states_not_operational"]:
        assert reserved not in body["titration_state_counts"]


def test_titration_summary_clamps_params(client):
    resp = client.get("/api/titration/summary?limit=999999&hours=999999")
    assert resp.status_code == 200
    assert resp.json()["freshness_window_hours"] <= 24 * 30


def test_signals_endpoint_carries_titration_fields(client):
    resp = client.get("/signals?limit=5")
    assert resp.status_code == 200
    body = resp.json()
    assert "titration_state_counts" in body
    for item in body.get("items", []):
        assert "titration_state" in item
        assert item["titration_state"] in TITRATION_STATES


# ---------------------------------------------------------------------------
# Titration-at-decision snapshot (outcome-feedback hook)
# ---------------------------------------------------------------------------


def test_titration_snapshot_explicit_values_win():
    from scripts.titration_snapshot_attach import (
        ATTACH_PROVIDED,
        maybe_attach_titration_snapshot,
    )

    source, fields = maybe_attach_titration_snapshot(
        {"titration_state_at_decision": "PRIMED"}, event_id="EVT_X"
    )
    assert source == ATTACH_PROVIDED
    assert fields == {}


def test_titration_snapshot_unavailable_refuses_to_fabricate():
    from scripts.titration_snapshot_attach import (
        ATTACH_UNAVAILABLE,
        maybe_attach_titration_snapshot,
    )

    source, fields = maybe_attach_titration_snapshot(
        {}, event_id="EVT_DOES_NOT_EXIST_ANYWHERE"
    )
    assert source == ATTACH_UNAVAILABLE
    assert fields == {}


def test_manual_trade_persists_titration_snapshot(tmp_path, monkeypatch):
    import scripts.persistence as persistence

    db = tmp_path / "titration_snapshot.db"
    monkeypatch.setattr(persistence, "DB_PATH", db, raising=False)
    persistence.init_schema(db_path=db)
    persistence.insert_manual_trade(
        "MT_TITR", "EVT_TITR", "TEST", "BUY", 1.0, 10.0,
        "2026-07-10T12:00:00+00:00", "thesis", "", "human", db_path=db,
        titration_state_at_decision="PRE_ALPHA_WATCH",
        titration_pre_alpha_gap_at_decision=0.31,
        titration_lrr_at_decision=0.72,
    )
    row = persistence.get_manual_trade("MT_TITR", db_path=db)
    assert row["titration_state_at_decision"] == "PRE_ALPHA_WATCH"
    assert row["titration_pre_alpha_gap_at_decision"] == 0.31
    assert row["titration_lrr_at_decision"] == 0.72


def test_manual_trade_titration_snapshot_rejects_out_of_range(tmp_path):
    import scripts.persistence as persistence

    db = tmp_path / "titration_bounds.db"
    persistence.init_schema(db_path=db)
    persistence.insert_manual_trade(
        "MT_BOUNDS", "EVT_B", "TEST", "SELL", 1.0, 10.0,
        "2026-07-10T12:00:00+00:00", "thesis", "", "human", db_path=db,
        titration_state_at_decision="X" * 500,          # length-capped
        titration_pre_alpha_gap_at_decision=-5.0,       # clamped to -1
        titration_lrr_at_decision=float("nan"),         # rejected -> NULL
    )
    row = persistence.get_manual_trade("MT_BOUNDS", db_path=db)
    assert len(row["titration_state_at_decision"]) <= 64
    assert row["titration_pre_alpha_gap_at_decision"] == -1.0
    assert row["titration_lrr_at_decision"] is None


def test_log_manual_trade_reports_titration_snapshot_source():
    from scripts.signal_inbox_api import log_manual_trade

    resp = log_manual_trade(
        event_id="EVT_NO_TITRATION_CONTEXT",
        ticker="ACME",
        side="BUY",
        quantity=1.0,
        price=10.0,
        thesis="filing momentum with improving margins",
        logged_by="human",
    )
    assert "titration_snapshot_source" in resp
    assert resp["titration_snapshot_source"] in {
        "provided_explicitly", "attached_from_signal", "unavailable"
    }
    # Safety invariants unchanged by the new fields.
    assert resp["broker_api_called"] is False
    assert resp["ai_execution_count"] == 0
