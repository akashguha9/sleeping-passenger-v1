"""Tests for the Narrative Cascade layer: observations, dedup, impulses,
linguistic features, narrative states, causal graph, resolver, and the
end-to-end cascade with leakage checks and API contract."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import scripts.persistence as persistence
from scripts.causal_event_graph import (
    event_nodes_with_triggers,
    load_causal_graph,
    propagate_shock,
)
from scripts.linguistic_state_engine import (
    classify_linguistic_inflection,
    extract_linguistic_features,
)
from scripts.narrative_cascade_engine import build_cascade_report
from scripts.narrative_observation import (
    build_observations_from_events,
    deduplicate_observations,
    normalize_observation,
)
from scripts.narrative_state_engine import (
    NARRATIVE_REGIMES,
    RESERVED_NARRATIVE_REGIMES,
    build_narrative_state,
    cluster_observations_into_narratives,
)
from scripts.prediction_market_impulse import (
    compute_market_impulse,
    log_odds,
)

NOW = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)


def _iso(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


# ---------------------------------------------------------------------------
# Prediction-market impulses
# ---------------------------------------------------------------------------


def _snap(hours_ago: float, prob, volume=50000, liquidity=20000):
    return {
        "market_id": "M1", "fetched_at": _iso(hours_ago), "probability": prob,
        "volume": volume, "liquidity": liquidity, "question": "Test market?",
    }


def test_log_odds_bounded_and_symmetric():
    assert log_odds(0.5) == 0.0
    assert log_odds(0.0) is not None and log_odds(0.0) < -9  # eps-bounded, finite
    assert log_odds(1.0) is not None and log_odds(1.0) > 9
    assert log_odds(float("nan")) is None
    assert log_odds("x") is None


def test_impulse_change_velocity_acceleration_reversal():
    result = compute_market_impulse([_snap(72, 0.35), _snap(48, 0.42), _snap(24, 0.55), _snap(2, 0.72)])
    assert result["impulse_available"] is True
    assert result["log_odds_change"] > 0
    assert result["velocity_per_hour"] > 0
    assert result["acceleration_per_hour2"] is not None
    assert result["reversal"] is False
    rev = compute_market_impulse([_snap(48, 0.4), _snap(24, 0.6), _snap(2, 0.45)])
    assert rev["reversal"] is True


def test_impulse_single_snapshot_refuses_change():
    result = compute_market_impulse([_snap(2, 0.6)])
    assert result["impulse_available"] is False
    assert result["reason"] == "insufficient_snapshots_for_change"
    assert result["latest_probability"] == 0.6


def test_impulse_duplicate_and_out_of_order_snapshots():
    ordered = compute_market_impulse([_snap(48, 0.4), _snap(2, 0.6)])
    shuffled = compute_market_impulse([_snap(2, 0.6), _snap(48, 0.4), _snap(2, 0.6)])
    assert ordered["log_odds_change"] == shuffled["log_odds_change"]


def test_impulse_missing_liquidity_floors_quality():
    result = compute_market_impulse([
        _snap(48, 0.4, volume=None, liquidity=None),
        _snap(2, 0.7, volume=None, liquidity=None),
    ])
    assert result["quality_factor"] == 0.25
    assert set(result["quality_missing_inputs"]) == {"volume", "liquidity"}
    assert result["impulse"] > 0


def test_impulse_shock_classes():
    small = compute_market_impulse([_snap(48, 0.50), _snap(2, 0.505)])
    big = compute_market_impulse([_snap(48, 0.30), _snap(2, 0.75)])
    assert small["shift_class"] == "NO_MATERIAL_SHIFT"
    assert big["shift_class"] == "SHOCK"


# ---------------------------------------------------------------------------
# Observation normalization + dedup
# ---------------------------------------------------------------------------


def _event(i, title, source="gdelt", hours_ago=5.0, url=None, **payload):
    body = {"title": title, "language": "English", **payload}
    if url:
        body["url"] = url
    return {
        "event_id": f"EV_{i}", "source_name": source,
        "fetched_at": _iso(hours_ago), "raw_payload": body,
    }


def test_normalize_observation_fields_and_missingness():
    obs = normalize_observation(_event(1, "Export controls confirmed on chips", url="https://x.co/a"))
    assert obs is not None
    assert obs["source_type"] == "news"
    assert obs["published_at_utc"] is None  # never fabricated from retrieval
    assert obs["feature_availability"]["published_at"] is False
    assert obs["retrieved_at_utc"].startswith("2026-07-10")
    assert obs["linguistic_features"]["available"] is True
    assert obs["author_id"] is None


def test_normalize_skips_market_data_and_empty():
    assert normalize_observation({"source_name": "market_data", "raw_payload": {"symbol": "A"}, "fetched_at": _iso(1)}) is None
    assert normalize_observation(_event(2, "")) is None


def test_dedup_exact_url_and_near_title():
    events = [
        _event(1, "Chip export controls announced today", url="https://a.com/1"),
        _event(2, "Chip export controls announced today", url="https://b.com/2"),  # exact title
        _event(3, "Different story about oil supply shock in the gulf", url="https://a.com/1"),  # same URL
        _event(4, "Chip export controls announced today by government officials", url="https://c.com/3"),  # near-dup
        _event(5, "Completely unrelated earnings beat for retailer", url="https://d.com/4"),
    ]
    result = build_observations_from_events(events)
    obs = result["observations"]
    clusters = {}
    for o in obs:
        clusters.setdefault(o["deduplication_cluster_id"], []).append(o)
    big = max(clusters.values(), key=len)
    assert len(big) >= 3  # 1,2,4 (and 3 via URL)
    for o in big:
        if o["duplicate_cluster_size"] > 1:
            assert o["independence_weight"] < 1.0
    singleton = [o for o in obs if o["duplicate_cluster_size"] == 1]
    assert all(o["independence_weight"] == 1.0 for o in singleton)
    assert result["duplicates_collapsed"] >= 2


def test_unicode_and_non_english_flagged_not_scored():
    obs = normalize_observation(_event(9, "対米輸出規制が強化される見通し 半導体業界に影響"))
    assert obs is not None
    assert obs["linguistic_features"]["available"] is False
    assert obs["linguistic_features"]["reason"] in ("non_english_or_non_text", "too_short")


# ---------------------------------------------------------------------------
# Linguistic features
# ---------------------------------------------------------------------------


def test_linguistic_certainty_and_urgency_and_frames():
    high = extract_linguistic_features(
        "Government confirms controls will take effect immediately amid shortage"
    )
    low = extract_linguistic_features(
        "Officials may possibly consider unverified rumoured restrictions someday"
    )
    assert high["certainty"] > 0 > low["certainty"]
    assert high["urgency"] > 0
    assert high["framing"]["scarcity_frame"] > 0
    assert high["framing"]["validation_status"] == "UNVALIDATED"
    assert high["feature_type"] == "LINGUISTIC_HEURISTIC"


def test_linguistic_null_and_short_text():
    assert extract_linguistic_features(None)["available"] is False
    assert extract_linguistic_features("")["reason"] == "empty_text"
    assert extract_linguistic_features("chip ban")["reason"] == "too_short"


def test_linguistic_inflection_labels():
    early = extract_linguistic_features("Officials say export controls may be considered; possible restrictions.")
    late = extract_linguistic_features("Controls confirmed and will take effect immediately; shortage worsening, systemic risk.")
    result = classify_linguistic_inflection(early, late)
    assert "CERTAINTY_RISING" in result["labels"]
    assert "ESCALATING" in result["labels"]
    insufficient = classify_linguistic_inflection(None, late)
    assert insufficient["labels"] == ["INSUFFICIENT_DATA"]


# ---------------------------------------------------------------------------
# Narrative clustering + state
# ---------------------------------------------------------------------------


def _mk_observations(titles_hours, source="gdelt"):
    events = [
        _event(i, title, source=source, hours_ago=h, url=f"https://s{i}.com/{i}")
        for i, (title, h) in enumerate(titles_hours)
    ]
    return build_observations_from_events(events)["observations"]


def test_clustering_groups_same_topic_separates_different():
    obs = _mk_observations([
        ("Chip export controls expanded on semiconductors", 30),
        ("Semiconductor export controls likely to expand", 20),
        ("Oil supply shock hits crude market after embargo", 10),
    ])
    narratives = cluster_observations_into_narratives(obs)
    assert len(narratives) == 2
    sizes = sorted(len(n["members"]) for n in narratives)
    assert sizes == [1, 2]


def test_narrative_state_accumulating_and_decaying():
    fresh = _mk_observations([
        ("Chip export controls story one on semiconductors", 40),
        ("Chip export controls story two on semiconductors", 6),
        ("Chip export controls story three on semiconductors", 1),
    ])
    narratives = cluster_observations_into_narratives(fresh)
    state = build_narrative_state(narratives[0], now=NOW, all_narratives=narratives)
    assert state["state"] in ("ACCUMULATING", "ACCELERATING", "EMERGING", "BREAKING")
    assert state["narrative_strength"] > 0
    assert state["half_life_source"] == "configured_prior"

    stale = _mk_observations([
        ("Old story about port closure disruption", 400),
        ("Old story again about port closure disruption", 380),
    ])
    old_narr = cluster_observations_into_narratives(stale)
    old_state = build_narrative_state(old_narr[0], now=NOW, all_narratives=old_narr)
    assert old_state["state"] == "DECAYING"


def test_narrative_state_breaking_on_market_impulse():
    obs = _mk_observations([
        ("Export controls market moves fast on semiconductors", 4),
        ("Export controls market shifts again on semiconductors", 2),
    ])
    narratives = cluster_observations_into_narratives(obs)
    state = build_narrative_state(
        narratives[0], now=NOW, all_narratives=narratives, market_impulse=0.9,
    )
    assert state["state"] == "BREAKING"
    assert state["prediction_market_impulse"] == 0.9


def test_narrative_contested_on_direction_conflict():
    obs = _mk_observations([
        ("Chip subsidy boost brings record growth and wins for sector", 6),
        ("Chip subsidy collapse warns of losses and bankruptcy risk", 4),
        ("Chip subsidy outcome uncertain as debate continues", 2),
    ])
    narratives = cluster_observations_into_narratives(obs)
    biggest = max(narratives, key=lambda n: len(n["members"]))
    state = build_narrative_state(biggest, now=NOW, all_narratives=narratives)
    if state["item_count"] >= 3:
        assert state["contradiction"] is not None
        assert state["contradiction_band"] in ("MODERATE", "HIGH", "EXTREME")


def test_reserved_regimes_never_assigned():
    obs = _mk_observations([("Some emerging topic on tariffs today", 5), ("Tariff topic again mentioned", 2)])
    narratives = cluster_observations_into_narratives(obs)
    state = build_narrative_state(narratives[0], now=NOW, all_narratives=narratives)
    assert state["state"] in NARRATIVE_REGIMES
    assert state["state"] not in RESERVED_NARRATIVE_REGIMES


def test_narrative_leakage_future_observations_do_not_count_backwards():
    from scripts.narrative_state_engine import _strength_at
    members = _mk_observations([
        ("Chip controls now on semiconductors", 10),
        ("Chip controls later on semiconductors", 1),
    ])
    past = NOW - timedelta(hours=5)
    s_past = _strength_at(members, past, 36.0)
    # Only the 10h-old event existed 5h ago; strength must exclude the 1h event.
    solo = _strength_at([members[0]], past, 36.0)
    assert abs(s_past - solo) < 1e-9


# ---------------------------------------------------------------------------
# Causal graph
# ---------------------------------------------------------------------------


def test_graph_loads_and_validates():
    graph = load_causal_graph()
    assert graph["status"] == "loaded"
    assert graph["problems"] == []
    assert len(graph["edges"]) > 20
    assert event_nodes_with_triggers(graph)


def test_graph_rejects_bad_edges(tmp_path):
    import json
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({
        "graph_version": "t",
        "nodes": [{"id": "a", "type": "EVENT"}, {"id": "b", "type": "INDUSTRY"}],
        "edges": [
            {"source": "a", "target": "missing", "relation": "INCREASES", "sign": 1, "strength": 0.5, "confidence": 0.5},
            {"source": "a", "target": "a", "relation": "INCREASES", "sign": 1, "strength": 0.5, "confidence": 0.5},
            {"source": "a", "target": "b", "relation": "INCREASES", "sign": 2, "strength": 0.5, "confidence": 0.5},
            {"source": "a", "target": "b", "relation": "CORRELATED_WITH", "sign": 1, "strength": 0.5, "confidence": 0.5},
            {"source": "a", "target": "b", "relation": "INCREASES", "sign": 1, "strength": 0.9, "confidence": 0.9, "lag_class": "FAST"},
        ],
        "exposures": {},
    }), encoding="utf-8")
    graph = load_causal_graph(bad)
    assert len(graph["edges"]) == 1
    assert len(graph["problems"]) == 4
    unreadable = load_causal_graph(tmp_path / "missing.json")
    assert unreadable["status"] == "unreadable_graph_file"


def test_propagation_signs_depth_pruning_and_bounds():
    graph = load_causal_graph()
    result = propagate_shock(graph, "chip_export_controls", 0.8)
    exposures = {r["ticker"]: r for r in result["security_exposures"]}
    assert exposures["ASML"]["latent_impact"] < 0  # constrained semicap
    assert exposures["ASML"]["depth_class"] in ("FIRST_ORDER", "SECOND_ORDER")
    for row in result["security_exposures"]:
        assert -1.0 <= row["latent_impact"] <= 1.0
        assert row["lag_class"] in ("IMMEDIATE", "FAST", "MEDIUM", "SLOW", "STRUCTURAL")
        assert row["strongest_path"][0] == "chip_export_controls"
    # deeper shocks decay: any SECOND_ORDER impact <= max FIRST_ORDER impact magnitude
    firsts = [abs(r["latent_impact"]) for r in result["security_exposures"] if r["depth_class"] == "FIRST_ORDER"]
    seconds = [abs(r["latent_impact"]) for r in result["security_exposures"] if r["depth_class"] == "SECOND_ORDER"]
    if firsts and seconds:
        assert max(seconds) <= max(firsts) + 1e-9


def test_propagation_cycle_protection_and_unknown_node():
    graph = load_causal_graph()
    result = propagate_shock(graph, "military_escalation", 1.0, max_depth=6)
    assert result["path_count"] < 500  # bounded despite depth
    unknown = propagate_shock(graph, "not_a_node", 0.5)
    assert unknown["status"] == "unknown_event_node"
    assert unknown["security_exposures"] == []


# ---------------------------------------------------------------------------
# Entity resolution
# ---------------------------------------------------------------------------


def test_entity_resolution_ladder(tmp_path, monkeypatch):
    db = tmp_path / "resolver.db"
    persistence.init_schema(db_path=db)
    persistence.upsert_global_security(
        canonical_symbol="ACMECORP", name="Acme Corporation",
        exchange_code="NYSE", country="US", db_path=db,
    )
    persistence.upsert_security_alias("ACME INC", "ACMECORP", source="test", db_path=db)
    monkeypatch.setattr(persistence, "DB_PATH", db, raising=False)
    import scripts.entity_security_resolver as resolver
    resolver.clear_cache()

    exact = resolver.resolve_entity("ACMECORP")
    assert exact["resolution_method"] == "EXACT_TICKER"
    assert exact["selected_ticker"] == "ACMECORP"

    alias = resolver.resolve_entity("Acme Inc")
    assert alias["resolution_method"] == "ALIAS"

    name = resolver.resolve_entity("Acme Corporation")
    assert name["resolution_method"] == "CURATED_NAME"

    fuzzy = resolver.resolve_entity("Acme Corporaton")  # typo
    assert fuzzy["resolution_method"] in ("FUZZY_NAME", "UNRESOLVED")

    nothing = resolver.resolve_entity("Completely Unknown Business")
    assert nothing["resolution_method"] == "UNRESOLVED"
    assert nothing["selected_ticker"] is None
    resolver.clear_cache()


# ---------------------------------------------------------------------------
# End-to-end cascade + persistence + API
# ---------------------------------------------------------------------------


def _seed_cascade_db(db: Path) -> None:
    persistence.init_schema(db_path=db)
    titles = [
        ("Officials consider chip export controls on semiconductors", 70),
        ("Chip export controls may be expanded, analysts caution", 52),
        ("Semiconductor export controls confirmed, effective immediately", 3),
    ]
    for i, (title, hours_ago) in enumerate(titles):
        persistence.insert_signal_event(
            f"EV_N{i}", "gdelt",
            {"title": title, "url": f"https://o{i}.com/{i}", "language": "English"},
            _iso(hours_ago), db_path=db,
        )
    persistence.insert_probability_snapshots([
        {"market_id": "PM_X", "fetched_at": _iso(h), "probability": p,
         "volume": 50000, "liquidity": 20000, "question": "Chip export controls expanded?"}
        for h, p in ((72, 0.35), (24, 0.55), (2, 0.72))
    ], db_path=db)
    persistence.insert_signal_event(
        "EV_PM", "polymarket",
        {"title": "Will chip export controls be expanded?", "market_id": "PM_X",
         "question": "Will chip export controls be expanded?", "implied_probability": 0.72},
        _iso(2), db_path=db,
    )


def test_probability_snapshot_persistence_bounds(tmp_path):
    db = tmp_path / "snaps.db"
    persistence.init_schema(db_path=db)
    inserted = persistence.insert_probability_snapshots([
        {"market_id": "M", "fetched_at": _iso(1), "probability": 0.5},
        {"market_id": "M", "fetched_at": _iso(1), "probability": 0.6},  # dup PK ignored
        {"market_id": "M", "fetched_at": _iso(2), "probability": 1.7},  # out of range -> NULL prob
        {"market_id": "", "fetched_at": _iso(3), "probability": 0.4},   # no market -> skipped
    ], db_path=db)
    assert inserted == 2
    rows = persistence.get_probability_snapshots(market_id="M", db_path=db)
    assert len(rows) == 2
    assert rows[0]["probability"] is None or 0 <= rows[0]["probability"] <= 1


def test_runner_normalizer_keeps_probability():
    from scripts.live_source_runner import _normalize_polymarket_record
    rec = {
        "market_id": "42", "title": "Will inflation rates rise this year?",
        "question": "Will inflation rates rise this year?",
        "implied_probability": 0.61, "implied_probability_source": "outcomePrices",
        "volume": 1000, "liquidity": 500,
    }
    normalized = _normalize_polymarket_record(rec)
    if normalized is not None:  # domain gate may reject; when kept, fields must survive
        assert normalized["implied_probability"] == 0.61
        assert normalized["implied_probability_source"] == "outcomePrices"
        assert normalized["question"]


def test_cascade_end_to_end_candidates_and_safety(tmp_path, monkeypatch):
    db = tmp_path / "cascade.db"
    _seed_cascade_db(db)
    monkeypatch.setattr(persistence, "DB_PATH", db, raising=False)
    report = build_cascade_report(db, now=NOW)
    assert report["observation_summary"]["observation_count"] >= 4
    assert report["narrative_count"] >= 1
    assert report["candidate_count"] >= 3
    tickers = {c["ticker"] for c in report["candidates"]}
    assert "ASML" in tickers or "NVDA" in tickers
    for cand in report["candidates"]:
        assert cand["operator_action"] in ("IGNORE", "WATCH", "RESEARCH", "PRIORITIZE", "NO_EDGE")
        assert cand["strongest_path"]
        assert cand["invalidation_conditions"]
        assert "HYPOTHESIS" in cand["counterfactuals"]["bull_path"]
        assert cand["narrative_recognition"]["missing_components"]
        assert "HUMAN REVIEW REQUIRED" in cand["status"]
    assert report["advisory_status"] == "ADVISORY_ONLY"
    assert report["can_execute"] is False
    assert "no_probability_claimed" in report["non_claims"]


def test_cascade_empty_db_honest_zeros(tmp_path, monkeypatch):
    db = tmp_path / "empty.db"
    persistence.init_schema(db_path=db)
    monkeypatch.setattr(persistence, "DB_PATH", db, raising=False)
    report = build_cascade_report(db, now=NOW)
    assert report["observation_summary"]["observation_count"] == 0
    assert report["narrative_count"] == 0
    assert report["candidate_count"] == 0
    assert report["probability_snapshot_count"] == 0


@pytest.fixture(scope="module")
def client():
    try:
        from fastapi.testclient import TestClient
    except ImportError:  # pragma: no cover
        pytest.skip("fastapi test client unavailable")
    import scripts.api_server as srv
    return TestClient(srv.app)


def test_cascade_api_contract(client):
    resp = client.get("/api/narrative/cascade")
    assert resp.status_code == 200
    body = resp.json()
    assert body["engine_version"] == "narrative_cascade_v1"
    assert body["advisory_status"] == "ADVISORY_ONLY"
    assert isinstance(body["candidates"], list)
    assert isinstance(body["narratives"], list)
    assert "cache_hit" in body
    # Second call within TTL is served from cache.
    resp2 = client.get("/api/narrative/cascade")
    assert resp2.json()["cache_hit"] is True
