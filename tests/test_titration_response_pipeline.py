"""End-to-end tests for the evidence→response pipeline and runtime store.

Uses a real temp SQLite DB through the actual persistence layer: inserts
signal_events + ohlcv_bars, runs the pipeline, and asserts observations,
susceptibility estimates, state transitions, leakage safety, and the
shadow-mode runtime injection path.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

import scripts.persistence as persistence
from scripts.titration_outcome_contract import MATURED, NOT_YET_MATURED
from scripts.titration_response_pipeline import (
    build_observations,
    build_susceptibility_estimates,
    run_pipeline,
)

BARS_START = date(2025, 12, 1)
BARS_END = date(2026, 3, 10)
EVENT_DAY_0 = date(2026, 1, 5)
N_EVENTS = 36


def _seed_bars(db: Path, ticker: str = "ACME") -> None:
    bars = []
    day = BARS_START
    price = 100.0
    i = 0
    while day <= BARS_END:
        # Oscillation + a genuine trend from Feb onward so labels vary.
        price *= 1.003 if i % 2 == 0 else 0.998
        if day >= date(2026, 2, 1):
            price *= 1.004
        bars.append({
            "ticker": ticker,
            "date": day.isoformat(),
            "open": price, "high": price * 1.01, "low": price * 0.99,
            "close": round(price, 4),
            "adjusted_close": None,
            "volume": 1000 + i,
            "source": "MANUAL_CSV_IMPORT",
        })
        day += timedelta(days=1)
        i += 1
    persistence.insert_ohlcv_bars(bars, db_path=db)


def _seed_events(db: Path, ticker: str = "ACME", n: int = N_EVENTS,
                 shuffle: bool = False) -> list[str]:
    ids = []
    order = list(range(n))
    if shuffle:
        order = order[::2] + order[1::2]  # deterministic out-of-order insert
    for i in order:
        ts = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc) + timedelta(days=i)
        event_id = f"EV_{ticker}_{i:03d}"
        persistence.insert_signal_event(
            event_id, "global_filings",
            {"ticker_or_identifier": ticker, "title": f"filing {i}"},
            ts.isoformat(), db_path=db,
        )
        ids.append(event_id)
    return ids


@pytest.fixture()
def seeded_db(tmp_path) -> Path:
    db = tmp_path / "response.db"
    persistence.init_schema(db_path=db)
    _seed_bars(db)
    _seed_events(db)
    return db


def test_pipeline_builds_matured_observations(seeded_db):
    summary = run_pipeline(db_path=seeded_db, write_runtime_summary=False)
    assert summary["observation_count"] > 0
    assert summary["matured_observation_count"] > 0
    assert summary["written"]["observations"] == summary["observation_count"]
    obs = persistence.get_titration_observations(db_path=seeded_db)
    assert obs, "observations must persist"
    # Every observation is entry-joined at/after its event date.
    for o in obs:
        if o["entry_bar_date"]:
            assert o["entry_bar_date"] >= str(o["event_ts"])[:10]


def test_maturity_gate_no_forward_labels_before_maturity(seeded_db):
    # Seed one event so close to the end of the bar history that h=20
    # cannot possibly have matured.
    persistence.insert_signal_event(
        "EV_ACME_LATE", "global_filings",
        {"ticker_or_identifier": "ACME", "title": "late filing"},
        "2026-03-05T10:00:00+00:00", db_path=seeded_db,
    )
    run_pipeline(db_path=seeded_db, write_runtime_summary=False)
    obs = persistence.get_titration_observations(db_path=seeded_db)
    late = [
        o for o in obs
        if o["event_id"] == "EV_ACME_LATE" and o["horizon"] == 20
    ]
    assert late, "expected a late event at h=20"
    for o in late:
        assert o["maturation"] == NOT_YET_MATURED
        assert o["z"] is None and o["y_absolute"] is None
    for o in obs:
        if o["maturation"] != MATURED:
            assert o["y_absolute"] is None, "labels only on matured rows"


def test_leakage_future_events_do_not_change_past_features(tmp_path):
    """Feature values at event k must be identical whether or not later
    events exist — the as-of join must never see the future."""
    db_a = tmp_path / "a.db"
    db_b = tmp_path / "b.db"
    for db, n in ((db_a, 10), (db_b, N_EVENTS)):
        persistence.init_schema(db_path=db)
        _seed_bars(db)
        _seed_events(db, n=n)
    obs_a = build_observations(db_path=db_a)["observations"]
    obs_b = build_observations(db_path=db_b)["observations"]

    def keyed(rows):
        return {
            (o["event_id"], o["horizon"]): (
                o["active_before"], o["active_after"], o["dose"],
                o["lrr"], o["pag"], o["titration_state"], o["geometry"],
            )
            for o in rows
        }
    a, b = keyed(obs_a), keyed(obs_b)
    shared = set(a) & set(b)
    assert shared, "first 10 events exist in both runs"
    for key in shared:
        assert a[key] == b[key], f"future events leaked into features for {key}"


def test_leakage_first_event_has_zero_prior_evidence(seeded_db):
    obs = build_observations(db_path=seeded_db)["observations"]
    first = [o for o in obs if o["event_id"] == "EV_ACME_000"]
    assert first
    for o in first:
        assert o["active_before"] == 0.0
        assert o["dose"] is not None and o["dose"] > 0


def test_out_of_order_and_duplicate_inserts_are_deterministic(tmp_path):
    db_sorted = tmp_path / "sorted.db"
    db_shuffled = tmp_path / "shuffled.db"
    for db, shuffle in ((db_sorted, False), (db_shuffled, True)):
        persistence.init_schema(db_path=db)
        _seed_bars(db)
        _seed_events(db, shuffle=shuffle)
        # Duplicate insert attempts are ignored (INSERT OR IGNORE on event_id).
        _seed_events(db, shuffle=shuffle)
    obs_1 = build_observations(db_path=db_sorted)["observations"]
    obs_2 = build_observations(db_path=db_shuffled)["observations"]
    ids_1 = sorted(o["obs_id"] for o in obs_1)
    ids_2 = sorted(o["obs_id"] for o in obs_2)
    assert ids_1 == ids_2
    assert len(ids_1) == len(set(ids_1)), "no duplicate observations"


def test_market_data_rows_are_not_evidence(seeded_db):
    persistence.insert_signal_event(
        "EV_CANDLE", "market_data",
        {"symbol": "ACME", "timestamp": "2026-01-20T00:00:00+00:00", "close": 101.0},
        "2026-01-20T00:05:00+00:00", db_path=seeded_db,
    )
    obs = build_observations(db_path=seeded_db)["observations"]
    assert not any(o["event_id"] == "EV_CANDLE" for o in obs)


def test_susceptibility_estimates_written_with_gates(seeded_db):
    summary = run_pipeline(db_path=seeded_db, write_runtime_summary=False)
    estimates = persistence.get_titration_susceptibility_estimates(db_path=seeded_db)
    assert summary["estimate_count"] == len(estimates)
    scopes = {(e["scope_type"], e["scope_key"]) for e in estimates}
    # 36 events with matured short horizons: GLOBAL + market pools pass the
    # 30 gate; ticker passes the 12 gate.
    assert ("GLOBAL", "GLOBAL") in scopes
    assert ("TICKER", "ACME") in scopes
    for e in estimates:
        assert e["n"] >= 12
        assert e["chi_norm"] is None or 0.0 <= e["chi_norm"] <= 1.0
        assert e["estimator"] == "chi_theil_sen_v1"


def test_state_transitions_recorded(seeded_db):
    run_pipeline(db_path=seeded_db, write_runtime_summary=False)
    transitions = persistence.get_titration_state_transitions(db_path=seeded_db)
    assert transitions, "state history should record at least one transition"
    for t in transitions:
        assert t["prev_state"] != t["new_state"]
        assert t["rule_trace"]


def test_dry_run_writes_nothing(seeded_db):
    summary = run_pipeline(db_path=seeded_db, dry_run=True, write_runtime_summary=False)
    assert summary["dry_run"] is True
    assert summary["written"] == {"observations": 0, "estimates": 0, "transitions": 0}
    assert persistence.get_titration_observations(db_path=seeded_db) == []


def test_runtime_store_serves_measured_susceptibility(seeded_db, monkeypatch):
    run_pipeline(db_path=seeded_db, write_runtime_summary=False)
    monkeypatch.setattr(persistence, "DB_PATH", seeded_db, raising=False)
    import scripts.titration_runtime_store as store
    store.clear_caches()
    measured = store.measured_susceptibility_for("ACME")
    assert measured is not None
    assert measured["source"] in {"MEASURED_TICKER", "MEASURED_MARKET", "MEASURED_GLOBAL"}
    assert measured["n"] >= 12
    assert measured["chi_norm"] is not None
    store.clear_caches()


def test_runtime_store_recognition_inputs(seeded_db, monkeypatch):
    monkeypatch.setattr(persistence, "DB_PATH", seeded_db, raising=False)
    import scripts.titration_runtime_store as store
    store.clear_caches()
    rec = store.recognition_inputs_for("ACME")
    assert rec is not None
    assert 0.0 <= rec["price_recognition"] <= 1.0
    assert rec["bars_used"] >= 10
    # Unknown ticker with data present degrades to None, not zeros.
    assert store.recognition_inputs_for("NO_SUCH") is None
    store.clear_caches()


def test_runtime_store_empty_db_short_circuits(tmp_path, monkeypatch):
    db = tmp_path / "empty.db"
    persistence.init_schema(db_path=db)
    monkeypatch.setattr(persistence, "DB_PATH", db, raising=False)
    import scripts.titration_runtime_store as store
    store.clear_caches()
    assert store.measured_susceptibility_for("ACME") is None
    assert store.recognition_inputs_for("ACME") is None
    store.clear_caches()


def test_decoration_consumes_measured_layer_end_to_end(seeded_db, monkeypatch):
    """Shadow-mode proof: after the pipeline runs, /signals decoration uses
    the measured susceptibility while retaining the heuristic proxy."""
    run_pipeline(db_path=seeded_db, write_runtime_summary=False)
    monkeypatch.setattr(persistence, "DB_PATH", seeded_db, raising=False)
    import scripts.titration_runtime_store as store
    store.clear_caches()
    from scripts.signal_inbox_api import _decorate_with_titration_state

    now = datetime(2026, 2, 10, 12, 0, tzinfo=timezone.utc)
    item = {
        "event_id": "EV_ACME_035",
        "ticker": "ACME",
        "event_timestamps": [
            (now - timedelta(hours=h)).isoformat() for h in (40.0, 20.0, 6.0, 1.0)
        ],
        "event_sources": ["global_filings"] * 4,
        "event_count": 4,
        "cross_source_support_count": 1,
        "duplicate_suppressed_count": 0,
        "persistence_score": 0.5,
        "observed_at": (now - timedelta(hours=1)).isoformat(),
    }
    out = _decorate_with_titration_state(item)
    t = out["titration"]
    assert t["susceptibility_source"] in {
        "MEASURED_TICKER", "MEASURED_MARKET", "MEASURED_GLOBAL", "SHRUNK_SECTOR",
    }
    assert t["susceptibility_sample_size"] >= 12
    assert t["buffer_status"] in {"MEASURED", "SHRUNK"}
    # Independent recognition components present -> PAG confidence upgraded.
    assert t["vmr_independent_components"] >= 1
    assert t["pre_alpha_gap_confidence"] in {"moderate", "low"}
    assert out["advisory_status"] == "ADVISORY_ONLY"
    assert out["can_execute"] is False
    store.clear_caches()


def test_all_numeric_outputs_finite(seeded_db):
    obs = build_observations(db_path=seeded_db)["observations"]
    ests = build_susceptibility_estimates(obs)
    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, float):
            assert math.isfinite(x)
    walk(obs)
    walk(ests)
