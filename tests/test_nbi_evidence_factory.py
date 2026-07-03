"""nbi-v1.2 evidence-factory sprint — closed-loop regression tests.

Objectives covered: ingestion runner, event closeout, template import,
prediction-market matching, card export, edge-claim gate, evidence quality
score, track record ledger, calibration readiness extension, score reporter,
and the fixture/template quarantine doctrine.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from scripts import narrative_branch_engine as nbi
from scripts import nbi_calibration_report as cal
from scripts import nbi_evidence_factory as factory
from scripts import nbi_prediction_market_bridge as pm
from scripts import nbi_store as store
from scripts import nbi_track_record_ledger as ledger

_NOW = datetime(2026, 7, 3, 6, 0, tzinfo=timezone.utc)
_NOW_ISO = "2026-07-03T06:00:00+00:00"


def _definition(event_id: str = "ev-summit") -> dict:
    return {
        "event_id": event_id,
        "event_name": "Test summit: venue vs capital",
        "category": "DIPLOMATIC_SUMMIT",
        "keywords": ["summit"],
        "decision_jurisdictions": ["JP", "IN"],
        "priors": {"core_event": 0.6, "venue_specific": 0.5},
        "exposures": [{
            "ticker": "MACRO1", "channel": "BROAD_THEMATIC",
            "base_relevance": 8.0, "evidence_confidence": 0.9,
            "evidence_refs": ["https://e/filing"], "filing_confirmed": True,
            "liquidity_ok": True, "days_since_last_verified": 0.5,
            "model_probability": 0.6, "market_implied_probability": 0.5,
            "realized_move_zscore": 1.0,
        }],
    }


def _rows() -> list[dict]:
    return [
        {
            "title": "Summit planned for early next week says government",
            "url": "https://www.reuters.com/summit-planned",
            "provider": "NEWSAPI", "publishedAt": "2026-07-02T06:00:00Z",
        },
        {
            "title": "Officials confirm summit preparations announced by ministry",
            "url": "https://www.mofa.go.jp/press/summit-prep",
            "provider": "OFFICIAL", "published_at": "2026-07-02T09:00:00Z",
        },
        {
            "title": "unrelated market chatter about breakfast cereals",
            "url": "https://www.example-blog.com/cereal",
            "provider": "RSS",
        },
    ]


def _run(db, *, is_fixture: bool = False, event_id: str = "ev-summit") -> dict:
    return factory.run_daily(
        definitions=[_definition(event_id)], rows=_rows(),
        db_path=db, now=_NOW, now_iso=_NOW_ISO, is_fixture=is_fixture,
    )


# ---------------------------------------------------------------------------
# Objective 1: ingestion runner
# ---------------------------------------------------------------------------


def test_run_daily_without_definitions_is_clean(tmp_path):
    out = factory.run_daily(definitions=[], rows=[], db_path=tmp_path / "f.db")
    assert out["status"] == factory.STATUS_NO_EVENT_DEFINITIONS
    assert out["nbi_daily"]["status"] == "NO_ACTIVE_NBI_EVENTS"
    assert out["edge_claim"]["edge_claim_allowed"] is False


def test_run_daily_feeds_unavailable_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(factory, "FEED_ROWS_PATH", tmp_path / "missing.json")
    out = factory.run_daily(
        definitions=[_definition()], rows=None, db_path=tmp_path / "f.db",
    )
    assert out["status"] == factory.STATUS_FEEDS_UNAVAILABLE
    assert out["ingested_events"] == []


def test_run_daily_ingests_and_persists_one_event(tmp_path):
    db = tmp_path / "f.db"
    out = _run(db)
    assert out["status"] == factory.STATUS_OK
    assert len(out["ingested_events"]) == 1
    assert out["ingested_events"][0]["saved"] is True
    assert out["rows_unmatched"] == 1  # the cereal row was never guessed in
    report = store.load_latest_report("ev-summit", db)
    assert report is not None
    assert report["claims_total"] == 2  # only summit-matched rows ingested
    assert out["nbi_daily"]["status"] == "ACTIVE"


def test_run_daily_fixture_runs_stay_off_production_surface(tmp_path):
    db = tmp_path / "f.db"
    out = _run(db, is_fixture=True)
    assert out["status"] == factory.STATUS_OK
    assert store.load_active_nbi_reports(db) == []  # fixtures quarantined
    assert len(store.load_active_nbi_reports(db, include_fixtures=True)) == 1


def test_repeated_runs_append_snapshots_not_duplicate_events(tmp_path):
    db = tmp_path / "f.db"
    _run(db)
    _run(db)
    conn = sqlite3.connect(str(db))
    try:
        n_events = conn.execute("SELECT COUNT(*) FROM nbi_events").fetchone()[0]
        n_snapshots = conn.execute(
            "SELECT COUNT(*) FROM nbi_branch_snapshots"
        ).fetchone()[0]
    finally:
        conn.close()
    assert n_events == 1        # upsert, not duplication
    assert n_snapshots == 2     # auditable time series appends


# ---------------------------------------------------------------------------
# Objective 2: case-closing operator flow
# ---------------------------------------------------------------------------


def test_close_event_creates_real_case_and_updates_readiness(tmp_path):
    db = tmp_path / "f.db"
    _run(db)
    before = store.summarize_nbi_backtest_readiness(db)
    assert before["cases_real_closed"] == 0
    out = factory.close_event(
        "ev-summit",
        branch_outcomes={"core": 1, "venue": 0, "delegation": 1, "deals": 0},
        notes="venue shifted; core held",
        benchmark="NIFTY50",
        realized_return=0.04, benchmark_return=0.01, initial_risk=0.02,
        db_path=db, now_iso=_NOW_ISO,
    )
    assert out["closed"] is True
    assert out["case_kind"] == store.CASE_KIND_REAL
    assert out["outcome_label"] == "CORE_HELD_SUB_BRANCH_COLLAPSED"
    assert out["return_vs_benchmark"] == 0.03
    assert out["r_multiple"] == 0.04 / (0.02 + 1e-9)
    assert "core" in out["prediction_errors"]
    assert out["readiness_after"]["cases_real_closed"] == 1
    # Event leaves the active surface.
    assert store.load_active_nbi_reports(db) == []
    # Closing twice refuses.
    again = factory.close_event(
        "ev-summit", branch_outcomes={"core": 1}, db_path=db,
    )
    assert again["closed"] is False and "RESOLVED" in again["error"]


def test_close_event_requires_core_outcome_and_known_event(tmp_path):
    db = tmp_path / "f.db"
    missing = factory.close_event("ghost", branch_outcomes={"core": 1}, db_path=db)
    assert missing["closed"] is False
    _run(db)
    bad = factory.close_event("ev-summit", branch_outcomes={}, db_path=db)
    assert bad["closed"] is False and "core" in bad["error"]


def test_fixture_event_closeout_can_never_create_real_case(tmp_path):
    db = tmp_path / "f.db"
    _run(db, is_fixture=True)
    out = factory.close_event(
        "ev-summit", branch_outcomes={"core": 1, "venue": 0},
        realized_return=0.1, benchmark_return=0.0, initial_risk=0.05,
        db_path=db, now_iso=_NOW_ISO,
    )
    assert out["closed"] is True
    assert out["is_fixture"] is True
    assert out["case_kind"] == store.CASE_KIND_FIXTURE
    assert out["calibration_eligible"] is False
    assert out["readiness_after"]["cases_real_closed"] == 0


# ---------------------------------------------------------------------------
# Objective 3: retro-label template pack
# ---------------------------------------------------------------------------


def test_template_pack_has_twenty_templates():
    payload = json.loads(factory.TEMPLATES_PATH.read_text(encoding="utf-8"))
    assert len(payload["templates"]) == 20
    assert payload["calibration_eligible"] is False


def test_import_templates_never_counts_as_real(tmp_path):
    db = tmp_path / "f.db"
    out = factory.import_templates(db_path=db)
    assert out["imported"] == 20
    readiness = out["readiness_after"]
    assert readiness["cases_template_seed_inventory"] == 20
    assert readiness["cases_real_closed"] == 0
    assert readiness["calibration_status"] == store.READINESS_INSUFFICIENT
    report = cal.build_nbi_calibration_report(db_path=db)
    assert report["status"] == cal.STATUS_INSUFFICIENT
    assert report["n_template_cases_excluded"] == 20
    cases = store.load_nbi_backtest_cases(db, include_fixtures=True)
    edge = ledger.compute_edge_claim_permission(cases, report)
    assert edge["edge_claim_allowed"] is False


# ---------------------------------------------------------------------------
# Objective 4: prediction-market wiring
# ---------------------------------------------------------------------------


def _demo_report() -> dict:
    return nbi.build_event_report(json.loads(json.dumps(nbi.DEMO_EVENT)))


def test_no_contracts_means_model_only():
    match = pm.match_prediction_markets_to_nbi_event(_demo_report(), [])
    assert match["any_market_signal"] is False
    for b in nbi.BRANCHES:
        blend = match["blended_branches"][b]
        assert blend["source"] == "MODEL_ONLY"
        assert blend["p_blend"] == blend["p_model"]


def test_weak_and_strong_matches_classified(tmp_path):
    report = _demo_report()
    contracts = [
        {  # strong: liquid, well-phrased, cited
            "market": "kalshi", "contract_id": "K1",
            "title": "Will the Japan-India summit take place?",
            "yes_probability": 0.9, "volume_usd": 50_000,
            "url": "https://kalshi.example/k1",
        },
        {  # weak: tiny volume
            "market": "polymarket", "contract_id": "P1",
            "title": "Summit venue held in Guwahati?",
            "yes_probability": 0.2, "volume_usd": 500,
            "url": "https://polymarket.example/p1",
        },
        {  # uncited -> alpha 0
            "market": "kalshi", "contract_id": "K2",
            "title": "Will the summit happen this month?",
            "yes_probability": 0.8, "volume_usd": 50_000,
        },
    ]
    match = pm.match_prediction_markets_to_nbi_event(report, contracts)
    by_id = {m["contract_id"]: m for m in match["matches"]}
    assert by_id["K1"]["classification"] == pm.MATCH_OK
    assert by_id["K1"]["branch"] == "core_event"
    assert by_id["P1"]["classification"] == pm.MATCH_WEAK
    assert by_id["P1"]["branch"] == "venue_specific"  # venue, not core
    assert by_id["K2"]["alpha"] == 0.0
    assert any("UNCITED" in n for n in by_id["K2"]["notes"])
    core = match["blended_branches"]["core_event"]
    assert core["source"] == pm.MATCH_OK
    assert core["p_model"] < core["p_blend"] <= 1.0  # market pulled it up


def test_market_cannot_push_venue_above_core():
    report = _demo_report()
    contracts = [{
        "market": "kalshi", "contract_id": "V1",
        "title": "Summit venue held in Guwahati city?",
        "yes_probability": 0.99, "volume_usd": 500_000,
        "liquidity_score": 1.0, "url": "https://kalshi.example/v1",
    }]
    match = pm.match_prediction_markets_to_nbi_event(report, contracts)
    blended = match["blended_branches"]
    assert blended["venue_specific"]["p_blend"] <= \
        blended["core_event"]["p_blend"] + 1e-9


def test_official_evidence_caps_market_alpha():
    # Build a report whose core branch carries official evidence.
    event = {
        "event_id": "off", "event_name": "official summit event",
        "claims": [{
            "claim_id": "o1", "layer": "CORE_FACT", "claim_text": "confirmed",
            "source_cluster": "mofa", "source_class": "OFFICIAL_GOVERNMENT",
            "direction": "SUPPORTS", "branch": "core_event", "strength": 1.0,
            "age_hours": 2, "evidence_refs": ["https://mofa/e"],
        }],
    }
    report = nbi.build_event_report(event)
    contracts = [{
        "market": "kalshi", "contract_id": "C1",
        "title": "official summit event happen?", "yes_probability": 0.1,
        "volume_usd": 10**6, "liquidity_score": 1.0,
        "url": "https://kalshi.example/c1",
    }]
    match = pm.match_prediction_markets_to_nbi_event(report, contracts)
    m = match["matches"][0]
    assert m["alpha"] <= pm.OFFICIAL_OVERRIDE_ALPHA_CAP + 1e-9
    assert any("OFFICIAL_FACT_GUARD" in n for n in m["notes"])


def test_run_daily_attaches_market_section(tmp_path):
    db = tmp_path / "f.db"
    out = factory.run_daily(
        definitions=[_definition()], rows=_rows(),
        contracts_by_event={"ev-summit": [{
            "market": "kalshi", "contract_id": "K9",
            "title": "Test summit take place next week?",
            "yes_probability": 0.7, "volume_usd": 40_000,
            "url": "https://kalshi.example/k9",
        }]},
        db_path=db, now=_NOW, now_iso=_NOW_ISO,
    )
    assert out["ingested_events"][0]["market_signal"] is True
    report = store.load_latest_report("ev-summit", db)
    assert report["market"]["any_market_signal"] is True


# ---------------------------------------------------------------------------
# Objective 5: operator card export
# ---------------------------------------------------------------------------


def test_export_cards_empty_state(tmp_path):
    db = tmp_path / "f.db"
    out = factory.export_cards(
        db, out_html=tmp_path / "cards.html", out_md=tmp_path / "cards.md",
    )
    assert out["exported"] is True
    assert "NO_ACTIVE_NBI_EVENTS" in out["html"]
    assert out["edge_claim_allowed"] is False
    assert "No performance edge is claimed" in out["html"]


def test_export_cards_with_event_includes_evidence_and_labels(tmp_path):
    db = tmp_path / "f.db"
    _run(db, is_fixture=True)
    out = factory.export_cards(
        db, out_html=tmp_path / "cards.html", out_md=tmp_path / "cards.md",
        include_fixtures=True,
    )
    assert out["active_events"] == 1
    assert "[FIXTURE]" in out["html"]           # fixtures clearly labeled
    assert "https://e/filing" in out["markdown"]  # evidence refs included
    assert "edge claim permitted" in out["markdown"].lower()
    # Excluded by default:
    quiet = factory.export_cards(
        db, out_html=tmp_path / "c2.html", out_md=tmp_path / "c2.md",
    )
    assert quiet["active_events"] == 0


# ---------------------------------------------------------------------------
# Objectives 6+7: edge-claim gate + evidence quality score
# ---------------------------------------------------------------------------


def _eligible_case(i: int, p: float, outcome: str, r: float = 1.0) -> dict:
    return {
        "case_id": f"e{i}", "event_id": f"ev{i}", "is_fixture": 0,
        "case_kind": store.CASE_KIND_REAL,
        "resolution_timestamp": "2026-07-01T00:00:00+00:00",
        "resolution_labels": {
            "outcome_label": outcome, "label_confidence": 1.0,
            "branch_outcomes": {"core": 1, "venue": 0, "delegation": 1,
                                "deals": 0},
            "operator_actions": ["ROTATE"],
        },
        "branch_probabilities": {"core_event": p},
        "return_vs_benchmark": 0.02, "r_multiple": r,
        "evidence_refs": ["https://e/1"],
    }


def test_eqs_components_lower_quality_as_specified():
    full = _eligible_case(0, 0.9, "CORE_HELD_INTACT")
    assert ledger.compute_case_quality(full)["EQS10"] == 10.0
    no_price = dict(full, return_vs_benchmark=None)
    assert ledger.compute_case_quality(no_price)["EQS10"] < 7
    no_refs = dict(full, evidence_refs=[])
    assert ledger.compute_case_quality(no_refs)["EQS10"] < 7
    unclear = dict(full)
    unclear["resolution_labels"] = dict(
        full["resolution_labels"], outcome_label="UNRESOLVED"
    )
    assert ledger.compute_case_quality(unclear)["EQS10"] == 0.0
    fixture = dict(full, is_fixture=1, case_kind=store.CASE_KIND_FIXTURE)
    assert ledger.compute_case_quality(fixture)["calibration_eligible"] is False
    assert ledger.compute_case_quality(full)["calibration_eligible"] is True


def test_edge_gate_false_on_empty_fixture_or_priceless_corpora():
    assert ledger.compute_edge_claim_permission([], None)[
        "edge_claim_allowed"] is False
    fixtures = [
        dict(_eligible_case(i, 0.9, "CORE_HELD_INTACT"),
             is_fixture=1, case_kind=store.CASE_KIND_FIXTURE)
        for i in range(40)
    ]
    assert ledger.compute_edge_claim_permission(fixtures, None)[
        "edge_claim_allowed"] is False
    priceless = [
        dict(_eligible_case(i, 0.9, "CORE_HELD_INTACT"),
             return_vs_benchmark=None, r_multiple=None)
        for i in range(40)
    ]
    gate = ledger.compute_edge_claim_permission(priceless, None)
    assert gate["edge_claim_allowed"] is False


def test_edge_gate_opens_only_with_full_measured_evidence():
    cases = (
        [_eligible_case(i, 0.95, "CORE_HELD_INTACT") for i in range(20)]
        + [_eligible_case(100 + i, 0.05, "CORE_DIED") for i in range(10)]
    )
    calibration = cal.build_nbi_calibration_report(cases=cases)
    assert calibration["status"] == cal.STATUS_POSSIBLE
    gate = ledger.compute_edge_claim_permission(cases, calibration)
    assert gate["edge_claim_allowed"] is True
    assert "human calibration review" in gate["reason"]
    # Remove one requirement (mean R) and the gate closes again.
    losing = [dict(c, r_multiple=-1.0) for c in cases]
    gate2 = ledger.compute_edge_claim_permission(losing, calibration)
    assert gate2["edge_claim_allowed"] is False


# ---------------------------------------------------------------------------
# Objective 8: track record ledger
# ---------------------------------------------------------------------------


def test_track_record_lifecycle_and_honest_refusal(tmp_path):
    db = tmp_path / "f.db"
    ledger.create_track_record_entry(
        recommendation_id="r1", event_id="ev1", operator_action="LOGGED",
        action_class="ROTATE", ticker_basket=["A", "B"], initial_score=5.0,
        initial_branch_probabilities={"core_event": 0.8},
        initial_rumor_risk=6.0, initial_hedge_need=5.0,
        invalidation_condition="official cancellation", db_path=db,
        now_iso=_NOW_ISO,
    )
    ledger.create_track_record_entry(
        recommendation_id="fx1", event_id="evfx", operator_action="LOGGED",
        action_class="ACT", ticker_basket=["Z"], initial_score=9.0,
        initial_branch_probabilities={}, initial_rumor_risk=0.0,
        initial_hedge_need=0.0, invalidation_condition="", is_fixture=True,
        db_path=db, now_iso=_NOW_ISO,
    )
    closed = ledger.close_track_record_entry(
        "r1", close_reason="resolved", realized_return=0.05,
        benchmark_return=0.02, r_multiple=1.5, db_path=db, now_iso=_NOW_ISO,
    )
    assert closed["closed"] is True
    assert abs(closed["return_vs_benchmark"] - 0.03) < 1e-12
    entries = ledger.load_track_record(db)
    assert [e["recommendation_id"] for e in entries] == ["r1"]  # fixture out
    summary = ledger.summarize_track_record(db)
    assert summary["status"] == ledger.TRACK_RECORD_INSUFFICIENT
    assert summary["performance"] is None
    assert summary["entries_closed"] == 1


# ---------------------------------------------------------------------------
# Objective 10: score reporter
# ---------------------------------------------------------------------------


def test_score_report_includes_all_segments_with_honesty_caps(tmp_path):
    db = tmp_path / "f.db"
    report = factory.build_score_report(db)
    names = [r["segment"] for r in report["segments"]]
    assert len(names) == 20 and "Overall MVP Ceiling" in names
    by_name = {r["segment"]: r for r in report["segments"]}
    # v1.6 caps: not installed <= 8.3; installed w/ unusable feed <= 8.5
    # (capability-detected, machine-dependent).
    if not report["capabilities"]["scheduler_installed"]:
        assert by_name["Live Data Integration"]["current"] <= 8.3
    else:
        assert by_name["Live Data Integration"]["current"] <= 8.6
    if not report["capabilities"]["frontend_app_page"]:
        assert by_name["Frontend / Operator Surface"]["current"] <= 8
    assert by_name["Overall MVP Ceiling"]["current"] <= 8.8  # no real cases
    assert report["edge_claim_allowed"] is False
    assert any("8.8" in c for c in report["constraint_caps_applied"])
    text = factory.render_score_report(report)
    assert "| Segment |" in text and "edge_claim_allowed=False" in text


def test_full_loop_end_to_end(tmp_path):
    """ingest -> card -> closeout -> case -> readiness -> score report."""
    db = tmp_path / "f.db"
    run = _run(db)
    assert run["status"] == factory.STATUS_OK
    status = factory.factory_status(db)
    assert status["active_event_count"] == 1
    closed = factory.close_event(
        "ev-summit", branch_outcomes={"core": 1, "venue": 0},
        realized_return=0.03, benchmark_return=0.01, initial_risk=0.02,
        db_path=db, now_iso=_NOW_ISO,
    )
    assert closed["closed"] is True
    after = factory.factory_status(db)
    assert after["active_event_count"] == 0
    assert after["backtest_readiness"]["cases_real_closed"] == 1
    assert after["track_record"]["entries_closed"] == 1
    assert after["edge_claim"]["edge_claim_allowed"] is False  # 1 << 30
    report = factory.build_score_report(db)
    assert report["real_closed_cases"] == 1
