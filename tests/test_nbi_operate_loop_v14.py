"""nbi-v1.4 operate-and-close-real-loop sprint — regression tests.

Covers: scheduler doctor + v1.4 health model, event activation flow,
real-fetcher wiring (offline fail-closed + injected LIVE rows + recency +
adapter-status alpha zero), worklist/batch workshop operations, calibration
CASE_ACCUMULATION band, corpus operating board, and frontend-surface
doctrine checks.
"""
from __future__ import annotations

import json

from scripts.advisory_contract import FORBIDDEN_EXECUTION_TOKENS
from scripts import nbi_calibration_report as cal
from scripts import nbi_evidence_factory as factory
from scripts import nbi_prediction_market_bridge as pm
from scripts import nbi_scheduler as sched
from scripts import nbi_store as store
from scripts import nbi_template_workshop as workshop

_NOW_ISO = "2026-07-03T10:00:00+00:00"


def _definition(**overrides) -> dict:
    base = {
        "event_id": "ev-v14",
        "event_name": "V14 operating summit",
        "name": "V14 operating summit",
        "category": "summit",
        "status": "WATCH_ONLY",
        "country_scope": ["JP", "IN"],
        "query_terms": ["summit"],
        "official_sources": ["mofa.go.jp"],
        "prediction_market_queries": ["summit"],
        "benchmark_tickers": ["SPY"],
        "decision_jurisdictions": ["JP"],
        "priors": {"core_event": 0.6},
        "exposures": [{
            "ticker": "MACRO1", "channel": "BROAD_THEMATIC",
            "base_relevance": 8.0, "evidence_confidence": 0.9,
            "evidence_refs": ["https://e/filing"], "filing_confirmed": True,
            "liquidity_ok": True, "days_since_last_verified": 0.5,
            "model_probability": 0.6, "market_implied_probability": 0.5,
            "realized_move_zscore": 1.0,
        }],
        "is_fixture": False,
    }
    base.update(overrides)
    return base


def _rows() -> list[dict]:
    return [{
        "title": "Summit planned for early next week says government",
        "url": "https://www.reuters.com/summit-planned",
        "provider": "NEWSAPI", "publishedAt": "2026-07-02T06:00:00Z",
    }]


# ---------------------------------------------------------------------------
# Objective 1: scheduler doctor + v1.4 health
# ---------------------------------------------------------------------------


def test_doctor_reports_cleanly_without_installed_task():
    def absent_runner(args, **kwargs):
        class Proc:
            returncode = 0 if args[:2] == ["schtasks", "/Query"] and len(args) == 2 else 1
            stderr = ""
            stdout = ""
        return Proc()
    report = sched.doctor(absent_runner)
    assert report["task_installed"] is False
    assert report["checks"]["task_installed"]["note"].startswith(
        "installable helper verified"
    )
    assert report["checks"]["scheduled_action_safety"]["ok"] is True
    assert report["checks"]["evidence_factory_import"]["ok"] is True
    assert report["checks"]["advisory_only_strings"]["ok"] is True


def test_doctor_action_safety_scan_blocks_forbidden_tokens():
    assert sched._safety_check_action("python -m scripts.nbi_scheduler run-once")
    assert not sched._safety_check_action("cmd /c broker place_order")


def test_run_once_v14_health_components(tmp_path, monkeypatch):
    monkeypatch.setattr(
        factory, "load_event_definitions", lambda path=None: [_definition(
            status="ACTIVE"
        )]
    )
    monkeypatch.setattr(factory, "load_feed_rows", lambda path=None: _rows())
    monkeypatch.setattr(sched, "SCORE_REPORT_ARTIFACT_PATH",
                        tmp_path / "score.json")
    record = sched.run_once(
        db_path=tmp_path / "s.db", last_run_path=tmp_path / "last.json",
        log_path=tmp_path / "run.log", now_iso=_NOW_ISO,
    )
    assert record["status"] == sched.STATUS_HEALTHY
    assert record["SchedulerHealth10"] == 10
    assert record["components"]["score_report_written"] == 1
    assert record["components"]["safety_check_passed"] == 1
    assert (tmp_path / "score.json").exists()


def test_run_once_degraded_when_feeds_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(factory, "load_event_definitions",
                        lambda path=None: None)
    monkeypatch.setattr(factory, "load_feed_rows", lambda path=None: None)
    monkeypatch.setattr(sched, "SCORE_REPORT_ARTIFACT_PATH",
                        tmp_path / "score.json")
    record = sched.run_once(
        db_path=tmp_path / "s.db", last_run_path=tmp_path / "last.json",
        log_path=tmp_path / "run.log", now_iso=_NOW_ISO,
    )
    assert record["status"] == sched.STATUS_DEGRADED_BUT_SAFE
    assert record["SchedulerHealth10"] == 0          # strict health
    assert record["SafeOperationalHealth10"] == 10   # clean fail-closed


# ---------------------------------------------------------------------------
# Objective 2: activation flow
# ---------------------------------------------------------------------------


def test_activation_lifecycle_and_gates(tmp_path):
    path = tmp_path / "events.json"
    factory.add_event_definition(_definition(), path=path, now_iso=_NOW_ISO)
    out = factory.activate_event("ev-v14", path=path, now_iso=_NOW_ISO)
    assert out["changed"] is True and out["status"] == "ACTIVE"
    saved = json.loads(path.read_text("utf-8"))
    assert saved["events"][0]["status"] == "ACTIVE"
    assert saved["events"][0]["activated_at"] == _NOW_ISO
    # Deactivate back to watch.
    out = factory.deactivate_event("ev-v14", path=path, now_iso=_NOW_ISO)
    assert out["changed"] is True and out["status"] == "WATCH_ONLY"


def test_activation_refused_below_readiness_or_missing_scope(tmp_path):
    path = tmp_path / "events.json"
    weak = _definition(event_id="weak", official_sources=[],
                       prediction_market_queries=[], benchmark_tickers=[],
                       exposures=[])
    factory.add_event_definition(weak, path=path, now_iso=_NOW_ISO)
    out = factory.activate_event("weak", path=path)
    assert out["changed"] is False
    assert "activation requirements not met" in out["error"]
    no_scope = _definition(event_id="noscope", country_scope=[])
    factory.add_event_definition(no_scope, path=path, now_iso=_NOW_ISO)
    out = factory.activate_event("noscope", path=path)
    assert out["changed"] is False
    # Fixture events can never activate.
    fx = _definition(event_id="fx", is_fixture=True)
    factory.add_event_definition(fx, path=path, now_iso=_NOW_ISO)
    assert factory.activate_event("fx", path=path)["changed"] is False


def test_activation_from_watch_pack_and_no_case_created(tmp_path, monkeypatch):
    path = tmp_path / "events.json"
    monkeypatch.setattr(factory, "EVENT_DEFINITIONS_PATH", path)
    out = factory.activate_event(
        "watch-semiconductor-export-controls", path=path, now_iso=_NOW_ISO,
    )
    assert out["changed"] is True and out["origin"] == "watch_pack"
    # Activation is configuration, never evidence.
    db = tmp_path / "a.db"
    readiness = store.summarize_nbi_backtest_readiness(db)
    assert readiness["cases_real_closed"] == 0
    status = factory.event_status(
        "watch-semiconductor-export-controls", path=path, db_path=db,
    )
    assert status["found"] is True
    assert status["definition_status"] == "ACTIVE"
    assert status["store_state"] is None  # no run yet, honestly reported


def test_active_event_runs_and_appears_on_board(tmp_path, monkeypatch):
    path = tmp_path / "events.json"
    monkeypatch.setattr(factory, "EVENT_DEFINITIONS_PATH", path)
    factory.add_event_definition(_definition(), path=path, now_iso=_NOW_ISO)
    factory.activate_event("ev-v14", path=path, now_iso=_NOW_ISO)
    db = tmp_path / "a.db"
    out = factory.run_daily(
        definitions=None, rows=_rows(), db_path=db, now_iso=_NOW_ISO,
    )
    assert out["status"] == factory.STATUS_OK
    assert out["ingested_events"][0]["event_id"] == "ev-v14"
    board = factory.corpus_status(db, now_iso=_NOW_ISO)
    assert "ev-v14" in board["event_definitions"]["active"]
    assert board["edge_claim_allowed"] is False


# ---------------------------------------------------------------------------
# Objective 3: real fetcher wiring
# ---------------------------------------------------------------------------


def test_default_fetch_does_no_network_and_fails_closed():
    out = pm.fetch_prediction_market_contracts(_definition())
    assert out["status"] == pm.FETCH_ADAPTER_UNAVAILABLE
    assert "kalshi" in out["note"]


def test_kalshi_fetcher_offline_reports_adapter_unavailable(monkeypatch):
    def offline_fetcher(queries):
        raise ConnectionError("no network")
    monkeypatch.setattr(pm, "_default_adapter_fetcher",
                        lambda source="": offline_fetcher
                        if source == "kalshi" else None)
    out = pm.fetch_prediction_market_contracts(
        _definition(), source="kalshi",
    )
    assert out["status"] == pm.FETCH_ADAPTER_UNAVAILABLE
    assert out["error_message"] == "ConnectionError"


def test_injected_live_rows_carry_adapter_metadata():
    def fetcher(queries):
        return [{
            "id": "KX1", "title": "Will the summit take place?",
            "yes_price": 55, "volume": 40_000, "market": "kalshi",
            "url": "https://kalshi.com/markets/KX1",
            "adapter_status": "LIVE", "query_used": "summit",
        }]
    out = pm.fetch_prediction_market_contracts(
        _definition(), fetcher=fetcher, now_iso=_NOW_ISO,
    )
    row = out["contracts"][0]
    assert row["adapter_status"] == "LIVE"
    assert row["query_used"] == "summit"
    assert row["yes_probability"] == 0.55
    assert row["fetched_at"] == _NOW_ISO


def test_non_live_adapter_status_zeroes_alpha():
    report = {"event_name": "grand summit of nations", "branches": {}}
    contracts = [{
        "market": "kalshi", "contract_id": "STALE1",
        "title": "grand summit of nations take place",
        "yes_probability": 0.9, "volume_usd": 10**6, "liquidity_score": 1.0,
        "url": "https://k.example/s1", "adapter_status": "CACHED",
    }]
    match = pm.match_prediction_markets_to_nbi_event(report, contracts)
    m = match["matches"][0]
    assert m["alpha"] == 0.0
    assert any("ADAPTER_NOT_LIVE" in n for n in m["notes"])


def test_recency_decay_reduces_alpha_for_stale_quotes():
    report = {"event_name": "grand summit of nations", "branches": {}}
    def contract(fetched_at):
        return [{
            "market": "kalshi", "contract_id": "R1",
            "title": "grand summit of nations take place",
            "yes_probability": 0.7, "volume_usd": 10**6,
            "liquidity_score": 1.0, "url": "https://k.example/r1",
            "adapter_status": "LIVE", "fetched_at": fetched_at,
        }]
    fresh = pm.match_prediction_markets_to_nbi_event(
        report, contract("2026-07-03T09:00:00+00:00"), now_iso=_NOW_ISO,
    )["matches"][0]["alpha"]
    stale = pm.match_prediction_markets_to_nbi_event(
        report, contract("2026-06-26T09:00:00+00:00"), now_iso=_NOW_ISO,
    )["matches"][0]["alpha"]
    assert stale < fresh


def test_bridge_status_census(tmp_path):
    empty = pm.bridge_status(tmp_path / "none.json")
    assert empty["contracts_file_present"] is False
    assert empty["adapter_health"] == "NO_FETCH_RECORDED"
    contracts_path = tmp_path / "contracts.json"
    contracts_path.write_text(json.dumps({
        "ev-v14": [{"adapter_status": "LIVE",
                    "fetched_at": _NOW_ISO}],
    }), encoding="utf-8")
    status = pm.bridge_status(contracts_path)
    assert status["live_rows"] == 1
    assert status["adapter_health"] == "LIVE_ROWS_PRESENT"
    assert status["last_fetched_at"] == _NOW_ISO


# ---------------------------------------------------------------------------
# Objective 4: worklist + batch operations
# ---------------------------------------------------------------------------


def test_worklist_export_and_gap_reporting(tmp_path):
    db = tmp_path / "w.db"
    assert factory.import_templates(db_path=db)["imported"] == 20
    items = workshop.template_worklist(db, limit=10)
    assert len(items) == 10
    first = items[0]
    for key in ("missing_evidence", "missing_outcomes", "missing_price",
                "missing_branch_probabilities", "estimated_minutes_to_promote",
                "EQS10_current", "priority"):
        assert key in first
    assert first["calibration_eligible"] is False  # untouched templates
    out = workshop.export_worklist(
        db, out_path=tmp_path / "worklist.json", now_iso=_NOW_ISO,
    )
    payload = json.loads((tmp_path / "worklist.json").read_text("utf-8"))
    assert out["items"] == 10
    assert "none counts as a case" in payload["doctrine"]


def test_batch_promote_refuses_incomplete_and_promotes_complete(tmp_path):
    db = tmp_path / "w.db"
    factory.import_templates(db_path=db)
    tpl = "tpl-2019-caa-japan-summit-guwahati"
    # Batch over one incomplete + prepare one complete.
    out = workshop.batch_promote(
        [tpl, "tpl-2016-brexit-referendum"],
        operator_confirmed=True, db_path=db, now_iso=_NOW_ISO,
    )
    assert out["promoted"] == 0 and out["refused"] == 2
    workshop.attach_evidence(tpl, url="https://mea.gov.in/2019-statement",
                             source_type="OFFICIAL_GOVERNMENT", db_path=db,
                             now_iso=_NOW_ISO)
    workshop.attach_outcome(tpl, branch_outcomes={"core": 1, "venue": 0,
                                                  "delegation": 1, "deals": 0},
                            label_confidence=1.0, db_path=db,
                            now_iso=_NOW_ISO)
    workshop.attach_price(tpl, realized_return=0.02, benchmark_return=0.01,
                          ticker="NIFTYBEES", db_path=db, now_iso=_NOW_ISO)
    workshop.attach_probabilities(
        tpl, probabilities={"core": 0.7, "venue": 0.6},
        basis="dated contemporaneous reporting", db_path=db, now_iso=_NOW_ISO,
    )
    out = workshop.batch_promote([tpl], operator_confirmed=True, db_path=db,
                                 now_iso=_NOW_ISO)
    assert out["promoted"] == 1
    assert out["readiness_after"]["cases_real_closed"] == 1
    # Calibration lands in the accumulation band; edge unchanged.
    report = cal.build_nbi_calibration_report(db_path=db)
    assert report["status"] == cal.STATUS_ACCUMULATION
    assert report["metrics"]["brier"] is None


# ---------------------------------------------------------------------------
# Objective 6: calibration bands
# ---------------------------------------------------------------------------


def test_calibration_band_progression():
    def case(i, p=0.9, outcome="CORE_HELD_INTACT"):
        return {
            "case_id": f"b{i}", "event_id": f"e{i}", "is_fixture": False,
            "resolution_timestamp": "2026-07-01T00:00:00+00:00",
            "resolution_labels": {"outcome_label": outcome},
            "branch_probabilities": {"core_event": p},
        }
    assert cal.build_nbi_calibration_report(cases=[])["status"] == \
        cal.STATUS_INSUFFICIENT
    five = cal.build_nbi_calibration_report(cases=[case(i) for i in range(5)])
    assert five["status"] == cal.STATUS_ACCUMULATION
    assert five["metrics"]["brier"] is None  # metrics withheld below 10
    twelve = cal.build_nbi_calibration_report(
        cases=[case(i, 0.8 if i % 2 else 0.3,
                    "CORE_HELD_INTACT" if i % 2 else "CORE_DIED")
               for i in range(12)]
    )
    assert twelve["status"] == cal.STATUS_DESCRIPTIVE
    assert twelve["metrics"]["brier"] is not None
    assert twelve["baseline_brier"] is not None


# ---------------------------------------------------------------------------
# Objective 7: operating board
# ---------------------------------------------------------------------------


def test_corpus_board_sections_and_next_actions(tmp_path):
    board = factory.corpus_status(tmp_path / "b.db", now_iso=_NOW_ISO)
    for key in ("scheduler", "event_definitions", "market_fetch_status",
                "surface_status", "live_ops_readiness",
                "next_required_operator_actions"):
        assert key in board
    actions = " ".join(board["next_required_operator_actions"])
    assert "eligible cases" in actions
    # Helper-only machines cap at 0.7; an installed task lifts the cap.
    ceiling = 1.0 if board["scheduler"]["installed"] else 0.7
    assert 0.0 <= board["live_ops_readiness"] <= ceiling


# ---------------------------------------------------------------------------
# Objective 5 + doctrine: frontend surface
# ---------------------------------------------------------------------------


def test_frontend_nbi_page_exists_and_is_execution_free():
    page = factory.REPO_ROOT / "frontend" / "src" / "app" / "nbi" / "page.tsx"
    assert page.exists()
    text = page.read_text(encoding="utf-8").lower()
    for token in FORBIDDEN_EXECUTION_TOKENS:
        assert token not in text
    for phrase in ("execute trade", "place order", "buy now", "sell now",
                   "auto trade", "connect brokerage"):
        assert phrase not in text
    assert "advisoryonlybadge" in text
    assert "edge claim" in text
    assert "getnbicards" in text  # consumes GET /nbi/cards


def test_frontend_capability_detected_in_score_report(tmp_path):
    report = factory.build_score_report(tmp_path / "s.db")
    assert report["capabilities"]["frontend_app_page"] is True
    by_name = {r["segment"]: r for r in report["segments"]}
    # v1.5: cockpit panels lift the frontend segment past the static cap.
    assert by_name["Frontend / Operator Surface"]["current"] == 8.5
