"""nbi-v1.1 live-wiring sprint — ingestion / store / calibration / graph /
price / daily-bridge regression tests.

Each section maps to a sprint objective:
  Ingestion  — rows -> claims, cluster derivation, layer auto-classifier
  Store      — idempotent migration, save/load round-trip, fixture guard
  Backtest   — corpus persistence + honest readiness census
  Calibration— Brier/logloss/ECE with insufficient-evidence refusal
  ValueChain — evidence-gated graph exposure + rotation via graph
  Price      — z-move validation, WATCH_ONLY / illiquidity fail-closed
  DailyBridge— demote-only min() composition + NO_ACTIVE_NBI_EVENTS
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone

from scripts import narrative_branch_engine as nbi
from scripts import nbi_calibration_report as cal
from scripts import nbi_claim_ingestion as ingest
from scripts import nbi_daily_bridge as bridge
from scripts import nbi_price_validation_adapter as pva
from scripts import nbi_store as store
from scripts import nbi_value_chain_mapper as vcg

_NOW = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)


def demo_report() -> dict:
    return nbi.build_event_report(copy.deepcopy(nbi.DEMO_EVENT))


# ---------------------------------------------------------------------------
# Objective 1/2: ingestion + cluster derivation
# ---------------------------------------------------------------------------


def _row(**overrides) -> dict:
    base = {
        "title": "Japan-India summit planned in Guwahati for early July",
        "url": "https://www.reuters.com/world/some-article",
        "provider": "NEWSAPI",
        "publishedAt": "2026-07-02T06:00:00Z",
    }
    base.update(overrides)
    return base


def test_raw_news_row_becomes_valid_verified_claim():
    claims = ingest.ingest_rows_to_normalized_claims([_row()], "ev1", now=_NOW)
    assert len(claims) == 1
    c = claims[0]
    assert c["verification"] == "VERIFIED"
    assert c["source_class"] == "CREDIBLE_MEDIA"
    assert c["layer"] == "CORE_FACT"
    assert c["branch"] == "core_event"
    assert c["evidence_refs"] == ["https://www.reuters.com/world/some-article"]
    assert c["age_hours"] == 6.0


def test_row_without_url_is_unverified():
    claims = ingest.ingest_rows_to_normalized_claims(
        [_row(url=None)], "ev1", now=_NOW
    )
    assert claims[0]["verification"] == "UNVERIFIED"
    assert claims[0]["evidence_refs"] == []


def test_same_article_five_times_is_one_cluster():
    claims = ingest.ingest_rows_to_normalized_claims([_row()] * 5, "ev1", now=_NOW)
    assert len({c["source_cluster"] for c in claims}) == 1
    branches = nbi.evaluate_event_branches(claims, None, [])
    assert branches["core_event"]["n_clusters"] == 1


def test_syndicated_copy_across_domains_is_one_cluster():
    rows = [
        _row(),
        _row(url="https://www.livemint.com/syndicated/copy-of-article"),
    ]
    claims = ingest.ingest_rows_to_normalized_claims(rows, "ev1", now=_NOW)
    assert len({c["source_cluster"] for c in claims}) == 1


def test_distinct_stories_on_distinct_domains_are_distinct_clusters():
    rows = [
        _row(title="Summit planned in Guwahati says government official"),
        _row(title="Japanese delegation of fifty companies expected at talks",
             url="https://asia.nikkei.com/delegation-story"),
        _row(title="MOFA officially confirmed the summit preparations today",
             url="https://www.mofa.go.jp/press/release-1"),
    ]
    claims = ingest.ingest_rows_to_normalized_claims(rows, "ev1", now=_NOW)
    assert len({c["source_cluster"] for c in claims}) == 3
    classes = {c["source_class"] for c in claims}
    assert "OFFICIAL_GOVERNMENT" in classes and "CREDIBLE_MEDIA" in classes


def test_social_cancellation_language_becomes_rumor_never_death():
    layered = ingest.classify_layer(
        "visit has been cancelled after chaos", "SOCIAL_MEDIA"
    )
    assert layered["layer"] == "RUMOR"
    assert layered["claim_magnitude"] >= 8.0


def test_official_cancellation_maps_to_narrative_death():
    layered = ingest.classify_layer(
        "the visit has been cancelled", "OFFICIAL_GOVERNMENT"
    )
    assert layered["layer"] == "NARRATIVE_DEATH"
    assert layered["direction"] == "REFUTES"


def test_credible_media_cancellation_still_downgrades_to_rumor():
    layered = ingest.classify_layer(
        "the visit has been cancelled", "CREDIBLE_MEDIA"
    )
    assert layered["layer"] == "RUMOR"  # NARRATIVE_DEATH needs official source


def test_venue_shift_maps_to_partial_resolution_refuting_venue():
    layered = ingest.classify_layer(
        "summit venue shifted to New Delhi", "CREDIBLE_MEDIA"
    )
    assert layered["layer"] == "PARTIAL_RESOLUTION"
    assert layered["branch"] == "venue_specific"
    assert layered["direction"] == "REFUTES"


def test_unclassifiable_text_fails_closed_to_unknown_layer():
    layered = ingest.classify_layer("lorem ipsum dolor sit amet", "CREDIBLE_MEDIA")
    assert layered["layer"] == ingest.UNKNOWN_LAYER
    claims = ingest.ingest_rows_to_normalized_claims(
        [_row(title="lorem ipsum dolor sit amet")], "ev1", now=_NOW
    )
    assert claims[0]["verification"] == "UNVERIFIED"  # excluded from truth


def test_demo_rows_flow_into_event_report():
    raw = ingest.build_nbi_claims_from_news_rows(ingest.DEMO_ROWS, "ev1", now=_NOW)
    report = nbi.build_event_report({
        "event_id": "ev1", "event_name": "ingested", "claims": raw,
    })
    assert report["claims_total"] == len(ingest.DEMO_ROWS)
    assert report["claims_verified"] >= 4
    assert report["branches"]["core_event"]["n_clusters"] >= 2


# ---------------------------------------------------------------------------
# Objective 6: SQLite persistence
# ---------------------------------------------------------------------------


def test_init_schema_is_idempotent(tmp_path):
    db = tmp_path / "nbi.db"
    store.init_nbi_schema(db)
    store.init_nbi_schema(db)  # second run must be a no-op, not an error


def test_save_and_load_report_round_trip(tmp_path):
    db = tmp_path / "nbi.db"
    report = demo_report()
    receipt = store.save_nbi_report(report, db_path=db, now_iso="2026-07-02T12:00:00+00:00")
    assert receipt["saved"] is True
    loaded = store.load_latest_report(report["event_id"], db)
    assert loaded is not None
    for b in nbi.BRANCHES:
        assert abs(loaded["branches"][b]["p"] - report["branches"][b]["p"]) < 1e-9
    event = store.load_nbi_event(report["event_id"], db)
    assert event["state"] == report["EVENT_STATE"]
    assert event["core_probability"] == report["branches"]["core_event"]["p"]


def test_fixture_reports_never_reach_active_surface(tmp_path):
    db = tmp_path / "nbi.db"
    store.save_nbi_report(demo_report(), db_path=db, is_fixture=True,
                          now_iso="2026-07-02T12:00:00+00:00")
    assert store.load_active_nbi_reports(db) == []
    assert len(store.load_active_nbi_reports(db, include_fixtures=True)) == 1


def test_dead_events_excluded_from_active(tmp_path):
    db = tmp_path / "nbi.db"
    report = demo_report()
    report["EVENT_STATE"] = "DEAD"
    store.save_nbi_report(report, db_path=db, now_iso="2026-07-02T12:00:00+00:00")
    assert store.load_active_nbi_reports(db) == []


# ---------------------------------------------------------------------------
# Objective 8: backtest corpus seed + readiness honesty
# ---------------------------------------------------------------------------


def _persist_case(db, case_id, *, is_fixture=False, resolved=True):
    case = store.create_nbi_backtest_case(
        demo_report(), category="DIPLOMATIC_SUMMIT",
        resolution_labels={"core": "HAPPENED"},
        outcome_label="CORE_HELD_SUB_BRANCH_COLLAPSED",
    )
    return store.persist_nbi_backtest_case(
        case, db_path=db, is_fixture=is_fixture, case_id=case_id,
        resolution_timestamp="2026-07-10T00:00:00+00:00" if resolved else None,
    )


def test_backtest_case_persist_and_load_round_trip(tmp_path):
    db = tmp_path / "nbi.db"
    _persist_case(db, "case-1", is_fixture=True)
    cases = store.load_nbi_backtest_cases(db, include_fixtures=True)
    assert len(cases) == 1
    case = cases[0]
    assert case["branch_probabilities"]["core_event"] > 0
    assert case["resolution_labels"]["outcome_label"] == \
        "CORE_HELD_SUB_BRANCH_COLLAPSED"
    assert store.load_nbi_backtest_cases(db) == []  # fixtures excluded


def test_readiness_census_is_honest(tmp_path):
    db = tmp_path / "nbi.db"
    summary = store.summarize_nbi_backtest_readiness(db)
    assert summary["cases_real_closed"] == 0
    assert summary["calibration_status"] == store.READINESS_INSUFFICIENT
    assert summary["edge_claim_permitted"] is False
    _persist_case(db, "fix-1", is_fixture=True)
    _persist_case(db, "real-1", is_fixture=False)
    summary = store.summarize_nbi_backtest_readiness(db)
    assert summary["cases_total"] == 2
    assert summary["cases_fixture"] == 1
    assert summary["cases_real_closed"] == 1
    assert summary["calibration_status"] == store.READINESS_INSUFFICIENT


# ---------------------------------------------------------------------------
# Objective 9: calibration report honesty
# ---------------------------------------------------------------------------


def _synthetic_case(i: int, p: float, outcome: str) -> dict:
    return {
        "case_id": f"synth-{i}", "event_id": f"ev-{i}", "is_fixture": False,
        "resolution_timestamp": "2026-07-10T00:00:00+00:00",
        "resolution_labels": {"outcome_label": outcome},
        "branch_probabilities": {"core_event": p},
    }


def test_calibration_refuses_zero_cases():
    report = cal.build_nbi_calibration_report(cases=[])
    assert report["status"] == cal.STATUS_INSUFFICIENT
    assert report["metrics"]["brier"] is None
    assert report["fitted_weights"] is None
    assert report["heuristic_weights_in_use"] == nbi.CLASS_LLR


def test_calibration_excludes_fixture_cases():
    fixtures = [dict(_synthetic_case(i, 0.8, "CORE_HELD_INTACT"),
                     is_fixture=True) for i in range(20)]
    report = cal.build_nbi_calibration_report(cases=fixtures)
    assert report["status"] == cal.STATUS_INSUFFICIENT
    assert report["n_closed_real_cases"] == 0
    assert report["n_fixture_cases_excluded"] == 20


def test_calibration_descriptive_band_computes_metrics_but_never_fits():
    cases = [
        _synthetic_case(i, 0.8 if i % 2 == 0 else 0.3,
                        "CORE_HELD_INTACT" if i % 2 == 0 else "CORE_DIED")
        for i in range(12)
    ]
    report = cal.build_nbi_calibration_report(cases=cases)
    assert report["status"] == cal.STATUS_DESCRIPTIVE
    assert report["metrics"]["brier"] is not None
    assert report["metrics"]["log_loss"] is not None
    assert report["fitted_weights"] is None
    assert "DESCRIPTIVE_ONLY" in report["fitted_weights_blocked_reason"]


def test_calibration_metrics_math_sanity():
    perfect = [_synthetic_case(i, 1.0, "CORE_HELD_INTACT") for i in range(30)]
    report = cal.build_nbi_calibration_report(cases=perfect)
    assert report["status"] == cal.STATUS_POSSIBLE
    assert report["metrics"]["brier"] == 0.0
    assert report["metrics"]["ece"] == 0.0
    assert report["fitted_weights"] is None  # fitting is NEVER automatic


# ---------------------------------------------------------------------------
# Objective 7: value-chain graph v1
# ---------------------------------------------------------------------------


def test_uncited_edge_contributes_zero_exposure():
    graph = {
        "nodes": [
            {"id": "EV", "kind": "EVENT"}, {"id": "T1", "kind": "TICKER"},
        ],
        "edges": [
            {"src": "EV", "dst": "T1", "weight": 0.9,
             "exposure_type": "DIRECT", "evidence_ref": ""},
        ],
    }
    assert vcg.compute_vce(graph, "EV") == {}
    normalized = vcg.normalize_graph(graph)
    assert any("no evidence_ref" in d for d in normalized["dropped_edges"])


def test_graph_cycle_does_not_hang():
    graph = {
        "nodes": [
            {"id": "EV", "kind": "EVENT"}, {"id": "A", "kind": "SECTOR"},
            {"id": "B", "kind": "SECTOR"}, {"id": "T1", "kind": "TICKER"},
        ],
        "edges": [
            {"src": "EV", "dst": "A", "weight": 1.0,
             "exposure_type": "BROAD_THEMATIC", "evidence_ref": "https://e/1"},
            {"src": "A", "dst": "B", "weight": 1.0,
             "exposure_type": "BROAD_THEMATIC", "evidence_ref": "https://e/2"},
            {"src": "B", "dst": "A", "weight": 1.0,
             "exposure_type": "BROAD_THEMATIC", "evidence_ref": "https://e/3"},
            {"src": "B", "dst": "T1", "weight": 0.5,
             "exposure_type": "DIRECT", "evidence_ref": "https://e/4"},
        ],
    }
    vce = vcg.compute_vce(graph, "EV")
    assert "T1" in vce and vce["T1"]["channels"]["DIRECT_COMPANY"] == 0.5


def test_guwahati_rotation_happens_via_graph_not_hardcoded_lists():
    """The acceptance test: graph-built exposures rotate the basket."""
    metadata = {
        "JPMACH": {"filing_confirmed": True, "liquidity_ok": True,
                   "days_since_last_verified": 0.5,
                   "model_probability": 0.62,
                   "market_implied_probability": 0.50,
                   "realized_move_zscore": 1.2},
        "INDAUTO": {"filing_confirmed": True, "liquidity_ok": True,
                    "days_since_last_verified": 0.5,
                    "model_probability": 0.58,
                    "market_implied_probability": 0.52,
                    "realized_move_zscore": 0.9},
        "ASSAMINFRA": {"liquidity_ok": True},
        "NE_CEMENT": {"liquidity_ok": True},
        "TATAELEC_PROXY": {"liquidity_ok": True},
    }
    exposures = vcg.build_exposures_from_graph(
        vcg.DEMO_GRAPH, "EV:JP-IN-SUMMIT", ticker_metadata=metadata
    )
    assert exposures, "graph produced no exposures"
    event = copy.deepcopy(nbi.DEMO_EVENT)
    event["exposures"] = exposures  # replaces hand-tagged lists entirely
    report = nbi.build_event_report(event)
    assert report["EVENT_STATE"] == "TRANSFORMED"
    assert set(report["downgraded_tickers"]) >= {"ASSAMINFRA", "NE_CEMENT"}
    by_ticker = {t["ticker"]: t for t in report["tickers"]}
    assert by_ticker["JPMACH"]["downgraded"] is False
    assert report["hedge"]["status"] == "COMPUTED"
    assert set(report["hedge"]["underweight_basket"]) >= {"ASSAMINFRA", "NE_CEMENT"}
    assert report["ACTION"] == "ROTATE"
    # Every graph exposure carries edge-evidence provenance.
    for e in exposures:
        assert e["evidence_refs"], f"{e['ticker']} exposure lost evidence refs"


def test_hedge_pair_and_benchmark_paths_are_metadata_only():
    graph = {
        "nodes": [
            {"id": "EV", "kind": "EVENT"}, {"id": "T1", "kind": "TICKER"},
        ],
        "edges": [
            {"src": "EV", "dst": "T1", "weight": 1.0,
             "exposure_type": "HEDGE_PAIR", "evidence_ref": "https://e/h"},
        ],
    }
    assert vcg.build_exposures_from_graph(graph, "EV") == []


# ---------------------------------------------------------------------------
# Objective 4: price adapter wiring
# ---------------------------------------------------------------------------


def _series(base: float, drift: float, days: int = 30) -> dict[int, float]:
    return {d: base * (1 + drift) ** d for d in range(days)}


def test_valid_price_series_produces_zscore_and_dislocation():
    prices = _series(100.0, 0.001)
    prices[29] = prices[28] * 1.08  # 8% pop on the event window close
    validation = pva.build_price_validation(
        "JPMACH", prices=prices, benchmark_prices=_series(400.0, 0.0005),
        event_day=25, as_of_day=29, implied_probability=0.5,
    )
    assert validation["price_valid"] is True
    assert validation["implied_probability_source"] == "MARKET"
    assert abs(validation["realized_move_zscore"]) > 1.0
    exposure = pva.attach_price_validation(
        {"ticker": "JPMACH", "channel": "BROAD_THEMATIC", "base_relevance": 8.0,
         "evidence_refs": ["https://e/1"], "filing_confirmed": True,
         "liquidity_ok": True, "days_since_last_verified": 0.0},
        validation, model_probability=0.65,
    )
    price = nbi.evaluate_price_validation(exposure)
    assert price["status"] == "COMPUTED"
    assert price["dislocation"] > 0


def test_missing_price_series_forces_watch_only():
    validation = pva.build_price_validation(
        "X", prices=None, benchmark_prices=None, event_day=0, as_of_day=5,
    )
    assert validation["price_valid"] is False
    exposure = pva.attach_price_validation(
        {"ticker": "X", "channel": "BROAD_THEMATIC", "base_relevance": 8.0,
         "evidence_refs": ["https://e/1"], "filing_confirmed": True,
         "liquidity_ok": True, "days_since_last_verified": 0.0},
        validation,
    )
    report = nbi.build_event_report({
        "event_id": "px", "claims": [{
            "claim_id": "c", "layer": "CORE_FACT", "claim_text": "x",
            "source_cluster": "a", "source_class": "CREDIBLE_MEDIA",
            "direction": "SUPPORTS", "branch": "core_event", "strength": 0.8,
            "age_hours": 4, "evidence_refs": ["https://e/c"],
        }], "exposures": [exposure],
    })
    assert report["tickers"][0]["status"] == "WATCH_ONLY"
    assert report["ACTION"] != "ACT"


def test_illiquid_ticker_forces_no_actionable_exposure():
    validation = pva.build_price_validation(
        "TINY", prices=_series(10, 0.001), benchmark_prices=_series(400, 0.0005),
        event_day=25, as_of_day=29, average_daily_volume_usd=50_000.0,
    )
    assert validation["liquidity_ok"] is False
    exposure = pva.attach_price_validation(
        {"ticker": "TINY", "channel": "BROAD_THEMATIC", "base_relevance": 9.0,
         "evidence_refs": ["https://e/1"], "filing_confirmed": True,
         "days_since_last_verified": 0.0},
        validation, model_probability=0.7,
    )
    assert exposure["liquidity_ok"] is False
    report = nbi.build_event_report({
        "event_id": "liq", "claims": [], "exposures": [exposure],
    })
    assert report["tickers"][0]["FINAL_TICKER_SCORE"] == 0.0
    assert report["ACTION"] == "NO_ACTIONABLE_EXPOSURE"


def test_weak_proxy_implied_probability_is_disclosed():
    validation = pva.build_price_validation(
        "X", prices=_series(100, 0.001), benchmark_prices=_series(400, 0.0005),
        event_day=25, as_of_day=29,
    )
    assert validation["implied_probability_source"] == "WEAK_PROXY"
    assert any("WEAK_PROXY" in n for n in validation["notes"])


def test_price_bonus_is_capped_and_never_exceeds_merit():
    exposure = {
        "ticker": "BIG", "channel": "BROAD_THEMATIC", "base_relevance": 9.0,
        "evidence_confidence": 1.0, "evidence_refs": ["https://e/1"],
        "filing_confirmed": True, "liquidity_ok": True,
        "days_since_last_verified": 0.0,
        "model_probability": 0.95, "market_implied_probability": 0.05,
        "realized_move_zscore": 5.0,  # dislocation 4.5 -> uncapped bonus 3.25
    }
    branches = nbi.evaluate_event_branches([], {"core_event": 0.9}, [])
    rumor = nbi.evaluate_rumor_risk([])
    row = nbi.score_exposure(exposure, branches, rumor)
    assert row["price_bonus_capped"] == nbi.PRICE_BONUS_CAP
    assert row["FINAL_TICKER_SCORE"] <= row["VALIDATED_RELEVANCE"] + 1e-9


# ---------------------------------------------------------------------------
# Objective 5: daily bridge — demote-only, quiet when empty
# ---------------------------------------------------------------------------


def _integration_fixture() -> dict:
    return {
        "mode": "CHICKEN_GATE_ENABLED",
        "rows": [
            {"TICKER": "JPMACH", "INTEGRATED_FINAL_SCORE": 9.0,
             "FINAL_ACTION_GATE": "BUY_ALLOWED", "FINAL_EXECUTABLE": True},
            {"TICKER": "UNRELATED", "INTEGRATED_FINAL_SCORE": 7.0,
             "FINAL_ACTION_GATE": "BUY_LIMITED", "FINAL_EXECUTABLE": False},
        ],
        "demotions": [],
    }


def test_no_reports_yields_clean_no_active_block_and_untouched_rows():
    integration = _integration_fixture()
    out = bridge.attach_nbi_to_integration(integration, [])
    assert out["nbi"]["status"] == bridge.NO_ACTIVE_NBI_EVENTS
    assert out["rows"] == integration["rows"]


def test_nbi_demotes_known_ticker_and_flips_executable():
    out = bridge.attach_nbi_to_integration(_integration_fixture(), [demo_report()])
    row = next(r for r in out["rows"] if r["TICKER"] == "JPMACH")
    assert row["INTEGRATED_FINAL_SCORE"] < 9.0
    assert bridge._GATE_RANK[row["FINAL_ACTION_GATE"]] < \
        bridge._GATE_RANK["BUY_ALLOWED"]
    assert row["FINAL_EXECUTABLE"] is False
    assert "NBI_DEMOTION" in row
    assert "JPMACH" in out["nbi_demotions"]


def test_nbi_never_touches_unknown_tickers_and_never_upgrades():
    integration = _integration_fixture()
    integration["rows"][0]["INTEGRATED_FINAL_SCORE"] = 0.5
    integration["rows"][0]["FINAL_ACTION_GATE"] = "BUY_BLOCKED"
    integration["rows"][0]["FINAL_EXECUTABLE"] = False
    out = bridge.attach_nbi_to_integration(integration, [demo_report()])
    row = next(r for r in out["rows"] if r["TICKER"] == "JPMACH")
    assert row["INTEGRATED_FINAL_SCORE"] <= 0.5      # never upgraded
    assert row["FINAL_ACTION_GATE"] == "BUY_BLOCKED"
    untouched = next(r for r in out["rows"] if r["TICKER"] == "UNRELATED")
    assert untouched["INTEGRATED_FINAL_SCORE"] == 7.0
    assert untouched["FINAL_ACTION_GATE"] == "BUY_LIMITED"


def test_build_nbi_daily_fails_closed_on_store_error(tmp_path):
    # A directory path as db file makes sqlite explode -> disclosed degrade.
    bad_db = tmp_path  # a directory, not a file
    integration = _integration_fixture()
    out = bridge.build_nbi_daily(integration, db_path=bad_db)
    assert out["nbi"]["status"] == bridge.NO_ACTIVE_NBI_EVENTS
    assert "load_error" in out["nbi"]
    assert out["rows"] == integration["rows"]


def test_build_nbi_daily_from_persisted_store(tmp_path):
    db = tmp_path / "nbi.db"
    store.save_nbi_report(demo_report(), db_path=db,
                          now_iso="2026-07-02T12:00:00+00:00")
    out = bridge.build_nbi_daily(_integration_fixture(), db_path=db)
    assert out["nbi"]["status"] == "ACTIVE"
    assert len(out["nbi"]["events"]) == 1
    assert out["nbi"]["events"][0]["state"] == "TRANSFORMED"
    assert "JPMACH" in out.get("nbi_demotions", [])


def test_daily_section_is_json_serializable():
    section = bridge.build_nbi_daily_section([demo_report()])
    json.dumps(section, default=str)
    assert section["events"][0]["downgraded_tickers"]
