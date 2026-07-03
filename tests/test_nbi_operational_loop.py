"""nbi-v1.3 operational-alpha-loop sprint — regression tests.

Covers: scheduler helper (dry-run safety, DEGRADED_BUT_SAFE health),
active-event definitions + readiness, market auto-fetch + alpha caps,
template workshop (audited TEMPLATE -> REAL promotion), closeout quality
gate, corpus-status dashboard, score report v1.3 caps, API/JSON operator
surface, and the no-execution-controls doctrine.
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

_NOW_ISO = "2026-07-03T08:00:00+00:00"


def _definition(**overrides) -> dict:
    base = {
        "event_id": "ev-loop",
        "event_name": "Loop summit event",
        "name": "Loop summit event",
        "category": "summit",
        "status": "ACTIVE",
        "query_terms": ["summit"],
        "official_sources": ["mofa.go.jp"],
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
# Objective 1: scheduler
# ---------------------------------------------------------------------------


def test_scheduler_install_dry_run_renders_safe_command():
    out = sched.install("08:30", dry_run=True)
    assert out["dry_run"] is True and out["installed"] is False
    joined = " ".join(out["schtasks_command"]).lower()
    assert sched.TASK_NAME.lower() in joined
    assert "run-once" in joined
    for token in FORBIDDEN_EXECUTION_TOKENS:
        assert token not in joined
    assert "run-once" in out["cron_equivalent"]


def test_scheduler_rejects_invalid_time():
    assert "error" in sched.install("25:99", dry_run=True)


def test_scheduler_status_when_task_absent():
    def fake_runner(args, **kwargs):
        class Proc:
            returncode = 1
            stderr = "ERROR: task not found"
            stdout = ""
        return Proc()
    assert sched.task_installed(fake_runner) is False
    status = sched.scheduler_status(fake_runner)
    assert status["install_status"] == sched.STATUS_NOT_INSTALLED


def test_scheduler_run_once_dry_run_never_mutates(tmp_path, monkeypatch):
    monkeypatch.setattr(factory, "EVENT_DEFINITIONS_PATH",
                        tmp_path / "none.json")
    monkeypatch.setattr(factory, "FEED_ROWS_PATH", tmp_path / "none2.json")
    db = tmp_path / "sched.db"
    out = sched.run_once(dry_run=True, db_path=db)
    assert out["dry_run"] is True and out["db_mutated"] is False
    assert not db.exists()  # dry-run touched nothing


def test_scheduler_run_once_degraded_but_safe_on_missing_feeds(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(
        factory, "load_event_definitions", lambda path=None: None
    )
    monkeypatch.setattr(factory, "load_feed_rows", lambda path=None: None)
    record = sched.run_once(
        db_path=tmp_path / "sched.db",
        last_run_path=tmp_path / "last.json", log_path=tmp_path / "run.log",
        now_iso=_NOW_ISO,
    )
    assert record["status"] == sched.STATUS_DEGRADED_BUT_SAFE
    assert record["SchedulerHealth10"] == 0
    assert (tmp_path / "last.json").exists()
    assert (tmp_path / "run.log").read_text(encoding="utf-8").strip()


def test_scheduler_run_once_healthy_cycle(tmp_path, monkeypatch):
    monkeypatch.setattr(
        factory, "load_event_definitions", lambda path=None: [_definition()]
    )
    monkeypatch.setattr(factory, "load_feed_rows", lambda path=None: _rows())
    record = sched.run_once(
        db_path=tmp_path / "sched.db",
        last_run_path=tmp_path / "last.json", log_path=tmp_path / "run.log",
        now_iso=_NOW_ISO,
    )
    assert record["status"] == sched.STATUS_HEALTHY
    assert record["SchedulerHealth10"] == 10
    assert record["components"]["report_persisted"] == 1
    assert record["edge_claim"]["edge_claim_allowed"] is False


# ---------------------------------------------------------------------------
# Objective 2: active-event definitions
# ---------------------------------------------------------------------------


def test_valid_definition_passes_and_scores_readiness():
    check = factory.validate_event_definition(_definition())
    assert check["valid"] is True
    assert check["EventReadiness10"] == 10.0


def test_missing_query_terms_fails_validation():
    check = factory.validate_event_definition(
        _definition(query_terms=[], keywords=[])
    )
    assert check["valid"] is False
    assert any("query_terms" in e for e in check["errors"])


def test_missing_benchmarks_and_sources_warn_and_cap_readiness():
    check = factory.validate_event_definition(
        _definition(official_sources=[], benchmark_tickers=[])
    )
    assert check["valid"] is True
    # v1.4 floors: 1 (query) x 0.25 (source floor) x 0.5 (bench)
    #            x 1 (chain) x 0.5 (no official) = 0.0625 -> 0.625
    assert check["EventReadiness10"] == 0.625
    assert check["activation_eligible"] is False  # below the 5.0 bar
    assert any("official_sources" in w for w in check["warnings"])
    assert any("benchmark" in w for w in check["warnings"])
    assert check["confidence_cap"] == factory.EVENT_CONFIDENCE_CAP_NO_OFFICIAL


def test_add_event_definition_writes_and_validates(tmp_path):
    path = tmp_path / "events.json"
    out = factory.add_event_definition(_definition(), path=path,
                                       now_iso=_NOW_ISO)
    assert out["added"] is True
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["events"][0]["event_id"] == "ev-loop"
    bad = factory.add_event_definition(
        _definition(event_id="x", query_terms=[], keywords=[]), path=path,
    )
    assert bad["added"] is False


def test_closed_definitions_do_not_run_and_event_id_filter_works(tmp_path):
    db = tmp_path / "f.db"
    closed = _definition(event_id="ev-closed", status="CLOSED")
    out = factory.run_daily(
        definitions=[closed], rows=_rows(), db_path=db, now_iso=_NOW_ISO,
    )
    assert out["status"] == factory.STATUS_NO_EVENT_DEFINITIONS
    both = [
        _definition(event_id="ev-a"), _definition(event_id="ev-b"),
    ]
    out = factory.run_daily(
        definitions=both, rows=_rows(), db_path=db, now_iso=_NOW_ISO,
        event_id="ev-b",
    )
    assert [e["event_id"] for e in out["ingested_events"]] == ["ev-b"]


def test_watch_event_pack_is_operator_ready_not_evidence(tmp_path):
    payload = json.loads(
        (factory.REPO_ROOT / "data" / "nbi_watch_event_definitions.json")
        .read_text(encoding="utf-8")
    )
    events = payload["events"]
    assert len(events) == 3
    for definition in events:
        check = factory.validate_event_definition(definition)
        assert check["valid"] is True
        assert definition["status"] == "WATCH_ONLY"
        assert definition["is_fixture"] is False
        assert definition["calibration_eligible"] is False
    # Defining events creates no cases and never moves the edge gate.
    db = tmp_path / "f.db"
    readiness = store.summarize_nbi_backtest_readiness(db)
    assert readiness["cases_real_closed"] == 0


# ---------------------------------------------------------------------------
# Objective 3: market auto-fetch + alpha caps
# ---------------------------------------------------------------------------


def test_fetch_no_queries_and_adapter_unavailable_fail_closed():
    assert pm.fetch_prediction_market_contracts({})["status"] == \
        pm.FETCH_NO_QUERIES
    out = pm.fetch_prediction_market_contracts({"query_terms": ["summit"]})
    assert out["status"] == pm.FETCH_ADAPTER_UNAVAILABLE
    assert out["contracts"] == []


def test_fetch_with_injectable_fetcher_normalizes_rows():
    def fetcher(queries):
        return [
            {"id": "K1", "title": "Will the summit happen?",
             "yes_price": 62, "volume": 30_000, "market": "kalshi",
             "url": "https://kalshi.example/k1"},
            {"id": "BAD", "title": "no probability row"},
        ]
    out = pm.fetch_prediction_market_contracts(
        {"query_terms": ["summit"]}, fetcher=fetcher, now_iso=_NOW_ISO,
    )
    assert out["status"] == pm.FETCH_OK
    assert len(out["contracts"]) == 1
    row = out["contracts"][0]
    assert row["yes_probability"] == 0.62  # cents normalized
    assert row["fetched_at"] == _NOW_ISO
    assert row["url"]


def test_fetcher_exception_fails_closed():
    def bomb(queries):
        raise RuntimeError("network down")
    out = pm.fetch_prediction_market_contracts(
        {"query_terms": ["x"]}, fetcher=bomb,
    )
    assert out["status"] == pm.FETCH_ADAPTER_UNAVAILABLE


def test_refresh_all_writes_contract_and_raw_files(tmp_path):
    def fetcher(queries):
        return [{"id": "C1", "title": "summit happen?", "yes_probability": 0.6,
                 "volume": 30_000, "url": "https://m.example/c1"}]
    out = pm.refresh_all_contracts(
        [_definition()], fetcher=fetcher,
        out_path=tmp_path / "contracts.json", raw_path=tmp_path / "raw.json",
        now_iso=_NOW_ISO,
    )
    assert out["written"] is True
    contracts = json.loads((tmp_path / "contracts.json").read_text("utf-8"))
    assert "ev-loop" in contracts
    assert (tmp_path / "raw.json").exists()  # raw payload traceable


def test_illiquid_alpha_cap_applies():
    report = {"event_name": "grand summit of nations", "branches": {}}
    contracts = [{
        "market": "polymarket", "contract_id": "P1",
        "title": "grand summit of nations happen", "yes_probability": 0.5,
        "volume_usd": 500, "liquidity_score": 1.0,
        "url": "https://p.example/p1",
    }]
    match = pm.match_prediction_markets_to_nbi_event(report, contracts)
    m = match["matches"][0]
    assert m["alpha"] <= pm.ILLIQUID_ALPHA_CAP + 1e-9
    assert any("ILLIQUID" in n for n in m["notes"])


def test_weak_phrasing_alpha_cap_applies():
    report = {"event_name": "big summit gathering here", "branches": {}}
    contracts = [{
        "market": "kalshi", "contract_id": "K1",
        "title": "summit resolves yes", "yes_probability": 0.5,
        "volume_usd": 10**6, "liquidity_score": 1.0,
        "url": "https://k.example/k1",
    }]
    match = pm.match_prediction_markets_to_nbi_event(report, contracts)
    m = match["matches"][0]
    assert m["phrasing_match_score"] < pm.WEAK_PHRASING_FLOOR
    assert m["alpha"] <= pm.WEAK_PHRASING_ALPHA_CAP + 1e-9
    assert any("WEAK_PHRASING" in n for n in m["notes"])


# ---------------------------------------------------------------------------
# Objective 4: template workshop
# ---------------------------------------------------------------------------


def _import_pack(db) -> None:
    assert factory.import_templates(db_path=db)["imported"] == 20


def test_workshop_list_and_incomplete_promotion_refusal(tmp_path):
    db = tmp_path / "w.db"
    _import_pack(db)
    templates = workshop.list_templates(db)
    assert len(templates) == 20
    tpl = "tpl-2019-caa-japan-summit-guwahati"
    refused = workshop.promote_template(
        tpl, to_real=True, operator_confirmed=True, db_path=db,
    )
    assert refused["promoted"] is False and refused["blockers"]
    no_flag = workshop.promote_template(tpl, db_path=db)
    assert no_flag["promoted"] is False


def test_workshop_rejects_invalid_evidence_url(tmp_path):
    db = tmp_path / "w.db"
    _import_pack(db)
    out = workshop.attach_evidence(
        "tpl-2016-brexit-referendum", url="notaurl", db_path=db,
    )
    assert out["attached"] is False


def test_workshop_full_promotion_path_and_audit_trail(tmp_path):
    db = tmp_path / "w.db"
    _import_pack(db)
    tpl = "tpl-2019-caa-japan-summit-guwahati"
    assert workshop.attach_evidence(
        tpl, url="https://mea.gov.in/statement-dec-2019",
        source_type="OFFICIAL_GOVERNMENT", db_path=db, now_iso=_NOW_ISO,
    )["attached"]
    assert workshop.attach_outcome(
        tpl, branch_outcomes={"core": 1, "venue": 0, "delegation": 1,
                              "deals": 0},
        label_confidence=1.0, db_path=db, now_iso=_NOW_ISO,
    )["attached"]
    assert workshop.attach_price(
        tpl, realized_return=0.02, benchmark_return=0.01,
        ticker="NIFTYBEES", initial_risk=0.02, db_path=db, now_iso=_NOW_ISO,
    )["attached"]
    no_basis = workshop.attach_probabilities(
        tpl, probabilities={"core": 0.7}, basis="", db_path=db,
    )
    assert no_basis["attached"] is False  # reconstructions need a basis
    assert workshop.attach_probabilities(
        tpl, probabilities={"core": 0.7, "venue": 0.6},
        basis="contemporaneous dated reporting, Dec 2019", db_path=db,
        now_iso=_NOW_ISO,
    )["attached"]
    check = workshop.validate_template(tpl, db)
    assert check["valid"] is True
    assert check["calibration_would_be_eligible"] is True

    before = store.summarize_nbi_backtest_readiness(db)["cases_real_closed"]
    promoted = workshop.promote_template(
        tpl, to_real=True, operator_confirmed=True, db_path=db,
        now_iso=_NOW_ISO,
    )
    assert promoted["promoted"] is True
    assert promoted["case_kind"] == store.CASE_KIND_REAL
    after = promoted["readiness_after"]
    assert after["cases_real_closed"] == before + 1
    # One promoted case never opens the edge gate (accumulation band).
    calibration = cal.build_nbi_calibration_report(db_path=db)
    assert calibration["status"] == cal.STATUS_ACCUMULATION
    assert calibration["metrics"]["brier"] is None
    trail = workshop.load_audit_trail(tpl, db)
    actions = [t["action"] for t in trail]
    assert actions[-1] == "PROMOTE_TO_REAL"
    assert len(trail) >= 4


def test_fixture_case_cannot_be_promoted(tmp_path):
    db = tmp_path / "w.db"
    case = store.create_nbi_backtest_case(
        __import__("copy").deepcopy(
            __import__("scripts.narrative_branch_engine",
                       fromlist=["x"]).build_event_report(
                json.loads(json.dumps(
                    __import__("scripts.narrative_branch_engine",
                               fromlist=["x"]).DEMO_EVENT
                ))
            )
        ),
        category="X", resolution_labels={},
        outcome_label="CORE_HELD_INTACT",
    )
    store.persist_nbi_backtest_case(
        case, db_path=db, is_fixture=True, case_id="fx::case",
    )
    out = workshop.promote_template("fx::case", to_real=True,
                                    operator_confirmed=True, db_path=db)
    assert out["promoted"] is False
    assert "not TEMPLATE" in out["error"]


# ---------------------------------------------------------------------------
# Objective 6: closeout quality
# ---------------------------------------------------------------------------


def _run(db, **kwargs):
    return factory.run_daily(
        definitions=[_definition()], rows=_rows(), db_path=db,
        now_iso=_NOW_ISO, **kwargs,
    )


def test_low_quality_closeout_refused_without_force(tmp_path):
    db = tmp_path / "c.db"
    _run(db)
    out = factory.close_event(
        "ev-loop", branch_outcomes={"core": 1}, db_path=db,
        now_iso=_NOW_ISO,
    )
    assert out["closed"] is False
    assert "closeout quality" in out["error"]


def test_forced_noncalibration_close_is_marked_and_ineligible(tmp_path):
    db = tmp_path / "c.db"
    _run(db)
    out = factory.close_event(
        "ev-loop", branch_outcomes={"core": 1},
        force_noncalibration=True, db_path=db, now_iso=_NOW_ISO,
    )
    assert out["closed"] is True
    assert out["closeout_class"] == factory.CLOSEOUT_CLASS_NON_CALIBRATION
    assert out["calibration_eligible"] is False
    cases = store.load_nbi_backtest_cases(db)
    assert cases[0]["resolution_labels"]["closeout_class"] == \
        factory.CLOSEOUT_CLASS_NON_CALIBRATION
    assert cases[0]["resolution_labels"]["label_confidence"] <= 0.3


def test_calibration_close_persists_brier_and_squared_errors(tmp_path):
    db = tmp_path / "c.db"
    _run(db)
    out = factory.close_event(
        "ev-loop",
        branch_outcomes={"core": 1, "venue": 0, "delegation": 1, "deals": 0},
        realized_return=0.03, benchmark_return=0.01, initial_risk=0.02,
        db_path=db, now_iso=_NOW_ISO,
    )
    assert out["closed"] is True
    assert out["closeout_class"] == factory.CLOSEOUT_CLASS_CALIBRATION
    assert out["case_brier"] is not None and 0 <= out["case_brier"] <= 1
    labels = store.load_nbi_backtest_cases(db)[0]["resolution_labels"]
    assert set(labels["squared_errors"]) == {"core", "venue", "delegation",
                                             "deals"}
    assert labels["case_brier"] == out["case_brier"]


# ---------------------------------------------------------------------------
# Objective 7: corpus-status
# ---------------------------------------------------------------------------


def test_corpus_status_empty_db(tmp_path):
    out = factory.corpus_status(tmp_path / "e.db", now_iso=_NOW_ISO)
    assert out["cases_real_closed"] == 0
    assert out["cases_remaining_for_calibration"] == 30
    assert out["calibration_progress10"] == 0.0
    assert out["edge_claim_allowed"] is False


def test_corpus_status_counts_and_stale_detection(tmp_path):
    db = tmp_path / "c.db"
    _import_pack(db)
    # A real event last touched a month ago -> stale.
    factory.run_daily(
        definitions=[_definition(event_id="ev-old")], rows=_rows(),
        db_path=db, now_iso="2026-06-01T00:00:00+00:00",
    )
    out = factory.corpus_status(db, now_iso=_NOW_ISO)
    assert out["cases_template"] == 20
    assert out["cases_real_closed"] == 0
    assert "ev-old" in out["stale_active_events"]
    assert len(out["easiest_templates_to_promote"]) == 3
    assert out["edge_claim_allowed"] is False


# ---------------------------------------------------------------------------
# Objective 8: score report v1.3
# ---------------------------------------------------------------------------


def test_score_report_weighted_with_caps(tmp_path):
    report = factory.build_score_report(tmp_path / "s.db")
    names = [r["segment"] for r in report["segments"]]
    assert len(names) == 20 and "Overall MVP Ceiling" in names
    assert report["overall_raw_weighted"] > 0
    overall = report["segments"][-1]["current"]
    assert overall <= 8.8  # no eligible cases on an empty DB
    assert overall <= report["overall_raw_weighted"] + 1e-9
    caps = " ".join(report["constraint_caps_applied"])
    assert "eligible" in caps and "edge claim" in caps
    assert report["edge_claim_allowed"] is False
    by_name = {r["segment"]: r for r in report["segments"]}
    capabilities = report["capabilities"]
    # v1.4 segment caps follow live capability detection.
    # v1.5 cap values.
    if not capabilities["scheduler_installed"]:
        assert by_name["Live Data Integration"]["current"] <= 8.3
    if not capabilities["frontend_app_page"]:
        assert by_name["Frontend / Operator Surface"]["current"] <= 8.0
    if not capabilities["market_auto_fetched"]:
        assert by_name["Prediction-Market Integration"]["current"] <= 8.1
    if not capabilities["real_active_events"]:
        assert by_name["Track Record / Evidence Factory"]["current"] <= 8.0
    else:
        assert by_name["Track Record / Evidence Factory"]["current"] <= 8.4
    assert by_name["Calibration Readiness"]["current"] <= 8.0  # eligible = 0


def test_score_report_responds_to_capability_changes(tmp_path, monkeypatch):
    import scripts.nbi_scheduler as sched_mod
    monkeypatch.setattr(sched_mod, "task_installed", lambda runner=None: True)
    report = factory.build_score_report(tmp_path / "s.db")
    assert report["capabilities"]["scheduler_installed"] is True
    by_name = {r["segment"]: r for r in report["segments"]}
    # Installed lifts the install cap; the feed cap may still bind, so
    # current lands at 8.5 (feed unusable) or 8.6 (feed usable).
    assert by_name["Live Data Integration"]["current"] in (8.5, 8.6)


# ---------------------------------------------------------------------------
# Objective 5 + safety: operator surface without execution controls
# ---------------------------------------------------------------------------


def test_export_cards_json_artifact_is_api_ready(tmp_path):
    db = tmp_path / "x.db"
    _run(db, is_fixture=True)
    out = factory.export_cards(
        db, out_html=tmp_path / "c.html", out_md=tmp_path / "c.md",
        out_json=tmp_path / "c.json", include_fixtures=True,
        now_iso=_NOW_ISO,
    )
    payload = json.loads((tmp_path / "c.json").read_text("utf-8"))
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    assert payload["execution_gate"] == "LOCKED"
    assert payload["edge_claim"]["edge_claim_allowed"] is False
    assert payload["section"]["events"][0]["is_fixture"] is True
    lowered = out["html"].lower()
    for token in FORBIDDEN_EXECUTION_TOKENS:
        assert token not in lowered
    assert "advisory_only" in lowered


def test_api_route_serves_clean_envelope():
    from scripts.api_server import get_nbi_operator_cards
    payload = get_nbi_operator_cards()
    assert isinstance(payload, dict)
    if payload.get("artifact_present"):
        assert payload["advisory_status"] == "ADVISORY_ONLY"
    else:
        assert payload["status"] == "NO_ACTIVE_NBI_EVENTS"
        assert payload["edge_claim"]["edge_claim_allowed"] is False
    text = json.dumps(payload).lower()
    for token in FORBIDDEN_EXECUTION_TOKENS:
        assert token not in text
