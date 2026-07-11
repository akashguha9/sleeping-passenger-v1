"""Defensive degradation drills — adversarial inputs against the live
signal spine.  Every drill asserts the same doctrine: hostile or broken
input degrades into an honest, structured, advisory-stamped state.  It
never crashes and never fabricates.
"""
from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_NOW = _dt.datetime(2026, 7, 1, 12, 0, 0, tzinfo=_dt.timezone.utc)


# ---------------------------------------------------------------------------
# Drill 1 — corrupt signal_events payloads through the inbox bridge
# ---------------------------------------------------------------------------


def _corrupt_rows() -> list[dict]:
    ts = "2026-07-01T10:00:00Z"
    return [
        # Payload is invalid JSON text.
        {"event_id": "corrupt_json", "source_name": "newsapi",
         "fetched_at": ts, "raw_payload": "{not json at all"},
        # Payload is a bare scalar.
        {"event_id": "corrupt_scalar", "source_name": "newsapi",
         "fetched_at": ts, "raw_payload": 42},
        # Payload is None.
        {"event_id": "corrupt_none", "source_name": "gdelt",
         "fetched_at": ts, "raw_payload": None},
        # Missing fetched_at entirely.
        {"event_id": "corrupt_no_ts", "source_name": "gdelt",
         "raw_payload": {"headline": "x"}},
        # One legitimate row so the bridge has something real to keep.
        {"event_id": "legit_1", "source_name": "newsapi", "fetched_at": ts,
         "raw_payload": {"headline": "Real headline", "symbol": "ACME"}},
    ]


def test_bridge_survives_corrupt_payloads():
    from scripts.signal_inbox_bridge import promote_signal_events_to_inbox

    items = promote_signal_events_to_inbox(
        get_signal_events=lambda **kw: _corrupt_rows(),
        now=_NOW,
    )
    # No crash is the drill; the bridge may keep or drop corrupt rows,
    # but whatever it returns must be structured and stamped.
    assert isinstance(items, list)
    for item in items:
        assert item.get("advisory_status") == "ADVISORY_ONLY"
        assert item.get("ai_execution_count") == 0


def test_titration_engine_survives_hostile_item_shapes():
    from scripts.market_titration_engine import evaluate_market_titration

    hostile_items = [
        {},                                        # empty
        {"event_timestamps": "not-a-list"},        # wrong type
        {"event_timestamps": ["garbage", None, 7]},  # unparseable entries
        {"event_timestamps": ["2026-07-01T10:00:00Z"],
         "event_sources": None,
         "persistence_score": "NaN-ish",
         "contamination_score": -99,
         "chaos_sensitivity_score": 99},           # out-of-range scores
        None,                                      # not even a dict
    ]
    for item in hostile_items:
        payload = evaluate_market_titration(item, now=_NOW)  # type: ignore[arg-type]
        assert payload["titration_state"], f"no state for {item!r}"
        # Deterministic honest floor: garbage in → INSUFFICIENT_DATA-ish
        # states, never an exception, never a fabricated PRIMED.
        assert payload["titration_state"] != "PRIMED"


# ---------------------------------------------------------------------------
# Drill 2 — clock-skew: future-dated candles must not crash freshness
# ---------------------------------------------------------------------------


def test_freshness_survives_future_dated_candles():
    from scripts import market_data_freshness as m

    future = (_NOW + _dt.timedelta(days=2)).isoformat()
    out = m.evaluate(
        candles=[{"timestamp": future}],
        source_kind=m.CANONICAL_SQLITE,
        now=_NOW,
    )
    # Negative age is clock skew, not ancient data: must classify FRESH
    # (age below every threshold) and must never raise.
    assert out["data_freshness_status"] == m.FRESH
    assert out["freshness_gate"] == m.PASS


def test_freshness_survives_garbage_timestamps():
    from scripts import market_data_freshness as m

    out = m.evaluate(
        candles=[{"timestamp": "not-a-date"}, {"timestamp": None}, {}],
        source_kind=m.CANONICAL_SQLITE,
        now=_NOW,
    )
    assert out["data_freshness_status"] == m.MISSING
    assert out["freshness_gate"] == m.BLOCK


# ---------------------------------------------------------------------------
# Drill 3 — chart context survives a quote fetcher that raises
# ---------------------------------------------------------------------------


def test_price_truth_survives_raising_quote_fetcher():
    from scripts.chart_structure_price_truth import compute_price_truth

    def _exploding_fetcher(symbol):
        raise RuntimeError("provider melted down")

    out = compute_price_truth(
        symbol="ACME",
        daily_close=100.0,
        daily_candle_utc="2026-06-30T16:00:00Z",
        quote_fetcher=_exploding_fetcher,
        now=_NOW,
    )
    assert out["price_truth_status"] == "QUOTE_UNAVAILABLE"
    assert out["latest_daily_close"] == 100.0
    assert out["advisory_status"] == "ADVISORY_ONLY"


# ---------------------------------------------------------------------------
# Drill 4 — malformed causal-graph file degrades with a structured error
# ---------------------------------------------------------------------------


def test_malformed_causal_graph_degrades_to_empty_graph(tmp_path):
    """The graph loader never crashes: structurally wrong content yields
    an empty validated graph (nothing to propagate over), and unreadable
    JSON yields an explicit unreadable status with recorded problems."""
    from scripts.causal_event_graph import load_causal_graph

    wrong_shape = tmp_path / "wrong_shape.json"
    wrong_shape.write_text('{"nodes": "not-a-list"}', encoding="utf-8")
    graph = load_causal_graph(wrong_shape)
    assert graph["nodes"] == {} and graph["edges"] == []

    unreadable = tmp_path / "unreadable.json"
    unreadable.write_text("{definitely not json", encoding="utf-8")
    broken = load_causal_graph(unreadable)
    assert broken["status"] == "unreadable_graph_file"
    assert "graph_file_unreadable" in broken["problems"]


def test_probe_converts_config_explosion_to_fail(monkeypatch):
    """End-to-end: a config that explodes at load becomes a FAIL check
    inside the probe, never an unhandled exception."""
    import scripts.titration_outcome_contract as toc
    from scripts import system_integrity_probe as probe

    def _boom(path=None):
        raise OSError("disk sector unreadable")

    monkeypatch.setattr(toc, "load_outcome_config", _boom)
    result = probe.run_system_integrity_probe(now=_NOW)
    by_id = {c["check_id"]: c for c in result["checks"]}
    assert by_id["config_outcome_contract"]["status"] == probe.FAIL
    assert "OSError" in by_id["config_outcome_contract"]["reason"]
    assert result["overall_status"] == probe.FAIL
