"""nbi-v1.5 live-ops-autopilot sprint — regression tests.

Covers: cockpit health model + autopilot dry-run safety, scheduler
install finisher (PS1 generation, verify-install truth, fix-plan), feed
bridge discovery/wiring, prediction-market query expansion + diagnostics,
template evidence packs, first-case readiness, score-report v1.5 caps and
subfields, and the frontend cockpit doctrine checks.
"""
from __future__ import annotations

import json

from scripts.advisory_contract import FORBIDDEN_EXECUTION_TOKENS
from scripts import nbi_evidence_factory as factory
from scripts import nbi_feed_bridge as feed
from scripts import nbi_live_ops_cockpit as cockpit
from scripts import nbi_prediction_market_bridge as pm
from scripts import nbi_scheduler as sched
from scripts import nbi_template_workshop as workshop

_NOW_ISO = "2026-07-03T12:00:00+00:00"


# ---------------------------------------------------------------------------
# Objective 1: cockpit + autopilot
# ---------------------------------------------------------------------------


def test_cockpit_status_works_on_empty_state(tmp_path):
    state = cockpit.gather_cockpit_state(tmp_path / "c.db", now_iso=_NOW_ISO)
    health = cockpit.compute_live_ops_health(state)
    assert 0.0 <= health["LiveOpsHealth10"] <= 10.0
    assert health["status"] in (
        cockpit.STATUS_BLOCKED_OPERATOR, cockpit.STATUS_DEGRADED_BUT_SAFE,
        cockpit.STATUS_READY_RUNNING,
    )
    # Capability-conditional: S is capped only while the OS task is absent.
    if not state["scheduler"]["task_installed"]:
        assert health["components"]["S_scheduler"] <= cockpit.S_HELPER_ONLY_CAP
        actions = cockpit.build_next_actions(state)
        assert actions and any("install" in a for a in actions)
    assert health["components"]["corpus_maturity"] == \
        cockpit.CORPUS_MATURITY_CAP  # empty tmp DB has no eligible cases


def test_cockpit_health_caps_follow_spec():
    state = {
        "scheduler": {"task_installed": False, "doctor_ok": True,
                      "install_command": "", "note": ""},
        "events": {"definitions": 1, "valid": 1, "active": ["e1"]},
        "feed": {"feed_usability": 0.0, "status": "FEED_NOT_WIRED"},
        "market": {"live_rows": 0},
        "corpus": {"events_total": 1,
                   "surface_status": {"cards_json_artifact": True},
                   "edge_claim_allowed": False,
                   "next_required_operator_actions": []},
        "calibration": {"n_calibration_eligible": 0,
                        "n_closed_real_cases": 0, "status": "X"},
        "first_case": {"recommended_first_three": [], "top_candidates": []},
        "worklist_count": 0,
        "safety_check_passed": True,
    }
    health = cockpit.compute_live_ops_health(state)
    c = health["components"]
    assert c["S_scheduler"] == cockpit.S_HELPER_ONLY_CAP
    assert c["F_feed_effective"] == cockpit.F_FAIL_CLOSED_CAP
    assert c["M_market_effective"] == cockpit.M_NO_MATCH_CAP
    assert c["corpus_maturity"] == cockpit.CORPUS_MATURITY_CAP
    # Safety failure dominates everything.
    unsafe = cockpit.compute_live_ops_health(
        {**state, "safety_check_passed": False}
    )
    assert unsafe["status"] == cockpit.STATUS_BROKEN_UNSAFE
    assert unsafe["LiveOpsHealth10"] == 0


def test_autopilot_dry_run_mutates_nothing(tmp_path, monkeypatch):
    db = tmp_path / "c.db"
    payload = cockpit.run_autopilot(
        db_path=db, dry_run=True, now_iso=_NOW_ISO,
    )
    assert payload["dry_run"] is True
    assert payload["steps_executed"] == []
    assert "artifacts" not in payload
    assert payload["edge_claim_allowed"] is False


def test_autopilot_real_run_writes_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(
        factory, "load_event_definitions", lambda path=None: None
    )
    monkeypatch.setattr(factory, "load_feed_rows", lambda path=None: None)
    payload = cockpit.run_autopilot(
        db_path=tmp_path / "c.db", now_iso=_NOW_ISO,
        out_json=tmp_path / "cockpit.json", out_md=tmp_path / "cockpit.md",
    )
    assert payload["artifacts"]["json"].endswith("cockpit.json")
    saved = json.loads((tmp_path / "cockpit.json").read_text("utf-8"))
    assert saved["edge_claim_allowed"] is False
    md = (tmp_path / "cockpit.md").read_text("utf-8")
    assert "ADVISORY_ONLY" in md and "Next required operator actions" in md
    lowered = md.lower()
    for token in FORBIDDEN_EXECUTION_TOKENS:
        assert token not in lowered
    steps = {s["step"]: s for s in payload["steps_executed"]}
    assert steps["run_daily"]["ok"] is True  # fail-closed run, no crash


# ---------------------------------------------------------------------------
# Objective 2: scheduler install finisher
# ---------------------------------------------------------------------------


def test_print_install_command_and_scripts_generation(tmp_path):
    command = sched.print_install_command("08:30")
    assert "schtasks" in command and sched.TASK_NAME in command
    out = sched.generate_install_scripts(
        "08:30", out_install=tmp_path / "install.ps1",
        out_uninstall=tmp_path / "uninstall.ps1",
    )
    assert out["generated"] is True and out["safety_check_passed"] is True
    install_text = (tmp_path / "install.ps1").read_text("utf-8")
    assert sched.TASK_NAME in install_text
    assert "run-once" in install_text
    assert "ADVISORY-ONLY" in install_text
    lowered = install_text.lower()
    for token in FORBIDDEN_EXECUTION_TOKENS:
        assert token not in lowered
    assert "schtasks /Delete" in (tmp_path / "uninstall.ps1").read_text("utf-8")


def test_verify_install_truth_and_fix_plan():
    def absent(args, **kwargs):
        class Proc:
            returncode = 1
            stderr = ""
            stdout = ""
        return Proc()
    out = sched.verify_install(absent)
    assert out["task_installed"] is False
    assert out["truth_source"] == "schtasks /Query"
    assert "not installed" in out["note"]
    doc = sched.doctor(absent)
    plan = sched.build_fix_plan(doc)
    assert any("install" in step for step in plan)


# ---------------------------------------------------------------------------
# Objective 3: feed bridge
# ---------------------------------------------------------------------------


def _feed_file(tmp_path, rows, name="feed.json"):
    path = tmp_path / name
    path.write_text(json.dumps({"events": rows}), encoding="utf-8")
    return path


def test_feed_discover_handles_empty_root(tmp_path):
    assert feed.discover_feed_sources(repo_root=tmp_path) == []


def test_feed_candidate_scoring_and_cite_or_drop(tmp_path):
    good = _feed_file(tmp_path, [
        {"headline": "summit planned", "url": "https://e/1",
         "provider": "NEWSAPI", "timestamp_utc": "2026-07-03T10:00:00Z"},
    ] * 5)
    scored = feed.score_feed_candidate(good, now_iso=_NOW_ISO)
    assert scored["usable_for_nbi"] is True
    assert scored["schema_guess"]["schema_score"] == 1.0
    no_urls = _feed_file(tmp_path, [
        {"headline": "summit planned", "provider": "RSS"},
    ], name="nourls.json")
    scored2 = feed.score_feed_candidate(no_urls, now_iso=_NOW_ISO)
    assert "url" in scored2["missing_fields"]
    assert scored2["feed_usability"] == 0.0  # zero cited rows
    wired = feed.wire_feed_source(no_urls, config_path=tmp_path / "cfg.json")
    assert wired["wired"] is False and "cite-or-drop" in wired["error"]


def test_feed_staleness_lowers_usability(tmp_path):
    path = _feed_file(tmp_path, [
        {"headline": "x", "url": "https://e/1", "provider": "P",
         "timestamp_utc": "2026-07-01T00:00:00Z"},
    ])
    fresh = feed.score_feed_candidate(path, now_iso=_NOW_ISO)
    aged = feed.score_feed_candidate(path, now_iso="2026-07-20T12:00:00+00:00")
    assert aged["feed_usability"] < fresh["feed_usability"]


def test_wire_and_factory_consumption(tmp_path, monkeypatch):
    good = _feed_file(tmp_path, [
        {"headline": "summit planned for next week", "url": f"https://e/{i}",
         "provider": "NEWSAPI", "timestamp_utc": "2026-07-03T10:00:00Z"}
        for i in range(5)
    ])
    config = tmp_path / "cfg.json"
    out = feed.wire_feed_source(good, config_path=config, now_iso=_NOW_ISO)
    assert out["wired"] is True
    monkeypatch.setattr(feed, "FEED_CONFIG_PATH", config)
    rows = factory.load_feed_rows()
    assert rows and rows[0]["headline"] == "summit planned for next week"
    status = feed.feed_bridge_status(config_path=config, now_iso=_NOW_ISO)
    assert status["status"] == feed.STATUS_READY
    assert status["feed_usability"] > 0


# ---------------------------------------------------------------------------
# Objective 4: prediction-market matching upgrade
# ---------------------------------------------------------------------------


def _definition() -> dict:
    return {
        "event_id": "ev15",
        "event_name": "Semiconductor export controls arena",
        "query_terms": ["chip export restrictions"],
        "prediction_market_queries": ["chip export restrictions"],
        "country_scope": ["US", "CN"],
        "sector_tags": ["semiconductors", "semicap_equipment"],
        "official_sources": ["bis.doc.gov", "meti.go.jp"],
    }


def test_query_expansion_is_deterministic_and_broad():
    expansion = pm.expand_event_queries(_definition())
    combined = expansion["combined"]
    assert "chip export restrictions" in combined
    assert "china" in combined            # country expansion
    assert "semiconductors" in combined   # sector expansion
    assert "semiconductor ban" in expansion["synonyms"]  # synonym family
    assert "bis" in expansion["entities"]  # official-source stem
    assert combined == pm.expand_event_queries(_definition())["combined"]


def test_broad_fetch_uses_expanded_queryset():
    captured: dict = {}
    def fetcher(queries):
        captured["queries"] = list(queries)
        return []
    pm.fetch_prediction_market_contracts(
        _definition(), fetcher=fetcher, broad=True, now_iso=_NOW_ISO,
    )
    assert "china" in captured["queries"]
    assert len(captured["queries"]) > 5


def test_diagnose_explains_zero_matches_honestly():
    diagnosis = pm.diagnose_event_matching(_definition(), [])
    assert diagnosis["contracts_examined"] == 0
    assert diagnosis["matched"] == []
    assert any("no contracts" in r for r in diagnosis["reasons"])
    assert "zero matches is a finding" in diagnosis["honest_zero_note"]


def test_match_score_components_and_relevant_contract_wins():
    relevant = {
        "title": "Will the US impose new chip export restrictions on China?",
        "fetched_at": _NOW_ISO,
    }
    unrelated = {"title": "Will it rain in Paris tomorrow?"}
    good = pm.compute_match_score(relevant, _definition(), now_iso=_NOW_ISO)
    bad = pm.compute_match_score(unrelated, _definition(), now_iso=_NOW_ISO)
    assert good["match_score"] > bad["match_score"]
    assert set(good["components"]) == {
        "token", "entity", "sector", "branch_specificity", "recency",
    }
    diagnosis = pm.diagnose_event_matching(
        _definition(), [relevant, unrelated], now_iso=_NOW_ISO,
    )
    assert diagnosis["matched"]
    assert diagnosis["matched"][0]["contract_title"] == relevant["title"]


# ---------------------------------------------------------------------------
# Objective 5: evidence packs
# ---------------------------------------------------------------------------


def test_evidence_pack_generation_and_validation(tmp_path):
    db = tmp_path / "w.db"
    assert factory.import_templates(db_path=db)["imported"] == 20
    out = workshop.make_evidence_pack(
        "tpl-2016-brexit-referendum", db_path=db,
        out_dir=tmp_path / "packs", now_iso=_NOW_ISO,
    )
    assert out["generated"] is True
    pack = json.loads(
        (tmp_path / "packs" / "tpl-2016-brexit-referendum.json")
        .read_text("utf-8")
    )
    assert pack["outcome_labels_needed"] is True
    assert pack["current_missing_fields"]
    assert "counts for nothing" in pack["doctrine"]
    check = workshop.validate_evidence_pack(
        "tpl-2016-brexit-referendum", db_path=db,
    )
    assert check["pack_complete"] is False and check["blockers"]
    assert workshop.make_evidence_pack("ghost", db_path=db)[
        "generated"] is False


# ---------------------------------------------------------------------------
# Objective 7: first-case readiness
# ---------------------------------------------------------------------------


def test_first_case_readiness_ranks_without_creating_cases(tmp_path):
    db = tmp_path / "f.db"
    factory.import_templates(db_path=db)
    plan = factory.first_case_readiness(db, now_iso=_NOW_ISO)
    assert len(plan["recommended_first_three"]) == 3
    assert all(c["kind"] == "TEMPLATE" for c in plan["candidates"])
    assert plan["cases_remaining_for_calibration"] == 30
    from scripts.nbi_store import summarize_nbi_backtest_readiness
    assert summarize_nbi_backtest_readiness(db)["cases_real_closed"] == 0


# ---------------------------------------------------------------------------
# Objective 8: score report v1.5
# ---------------------------------------------------------------------------


def test_score_report_v15_fields_and_caps(tmp_path):
    report = factory.build_score_report(tmp_path / "s.db")
    v15 = report["v15"]
    assert v15["market_match_quality"] == "FETCH_WORKS_ZERO_MATCHES"
    assert v15["scheduler_install_truth"] in (True, False)
    assert v15["first_case_readiness_available"] is True
    assert "feed_bridge_usability" in v15
    by_name = {r["segment"]: r for r in report["segments"]}
    caps = report["capabilities"]
    if not caps["scheduler_installed"]:
        assert by_name["Live Data Integration"]["current"] <= 8.3
    elif caps["feed_usability"] == 0.0:
        assert by_name["Live Data Integration"]["current"] <= 8.5
    if not caps["market_auto_fetched"]:
        assert by_name["Prediction-Market Integration"]["current"] <= 8.1
    if caps["real_active_events"]:
        assert by_name["Track Record / Evidence Factory"]["current"] <= 8.4
    assert by_name["Overall MVP Ceiling"]["current"] <= 8.8


# ---------------------------------------------------------------------------
# Objective 6 + doctrine: frontend cockpit + API route
# ---------------------------------------------------------------------------


def test_frontend_cockpit_panel_exists_and_is_execution_free():
    page = factory.REPO_ROOT / "frontend" / "src" / "app" / "nbi" / "page.tsx"
    text = page.read_text(encoding="utf-8")
    assert "CockpitPanel" in text
    assert "getNbiCockpit" in text
    assert "Next operator actions" in text
    lowered = text.lower()
    for token in FORBIDDEN_EXECUTION_TOKENS:
        assert token not in lowered
    for phrase in ("execute trade", "place order", "buy now", "sell now",
                   "auto trade", "connect brokerage"):
        assert phrase not in lowered


def test_session_close_report_is_honest(tmp_path, monkeypatch):
    monkeypatch.setattr(cockpit, "SESSION_CLOSE_JSON_PATH",
                        tmp_path / "close.json")
    monkeypatch.setattr(cockpit, "SESSION_CLOSE_MD_PATH",
                        tmp_path / "close.md")
    payload = cockpit.build_session_close_report(
        tmp_path / "c.db", now_iso=_NOW_ISO, tests_summary="local run",
    )
    assert payload["edge_claim_allowed"] is False
    assert isinstance(payload["eligible_real_cases"], int)
    assert payload["overall_score"] <= 9.0
    md = (tmp_path / "close.md").read_text("utf-8")
    assert "ADVISORY_ONLY" in md and "Next 7-day operator checklist" in md
    lowered = md.lower()
    for token in FORBIDDEN_EXECUTION_TOKENS:
        assert token not in lowered


def test_api_cockpit_route_serves_clean_envelope():
    from scripts.api_server import get_nbi_live_ops_cockpit
    payload = get_nbi_live_ops_cockpit()
    assert isinstance(payload, dict)
    if not payload.get("artifact_present"):
        assert payload["status"] == "NO_COCKPIT_RUN_RECORDED"
        assert payload["edge_claim_allowed"] is False
    text = json.dumps(payload, default=str).lower()
    for token in FORBIDDEN_EXECUTION_TOKENS:
        assert token not in text
