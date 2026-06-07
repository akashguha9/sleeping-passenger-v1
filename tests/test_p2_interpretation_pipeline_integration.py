"""Integration tests: P2 interpretation expansion wired through the pipeline."""
from __future__ import annotations

from pathlib import Path

from daily_payload_factory import holding, write_daily_payload

import scripts.daily_synthesis_pipeline as dsp
from scripts.daily_synthesis_pipeline import (
    assert_no_candidate_invention,
    compact_status_lines,
    run_daily_synthesis,
    write_isolated_run_artifacts,
)
from scripts.isolated_model_lanes import (
    IGNORED_P2_DEFENSE_VIOLATION,
    validate_model_lane_output,
)

SESSION = "2026-06-07"
_FUND = {"PLTR": {"debt_to_equity": 0.3, "gross_margin": 0.8, "current_ratio": 2.4,
                  "earnings_stability": 0.7, "interest_coverage": 8,
                  "earnings_growth": 0.3, "revenue_growth": 0.25, "filing_materiality": 0.7}}


def _live_mover(ticker="PLTR"):
    return {"ticker": ticker, "is_live": True, "source_health": "VERIFIED_LIVE",
            "provider": "yahoo_live", "freshness": "FRESH_TODAY",
            "timestamp_utc": f"{SESSION}T13:00:00Z", "why_today": "8-K contract award filed today",
            "sector": "Software", "country": "United States", "theme": "Govt analytics"}


def _static(ticker="NVDA"):
    return {"ticker": ticker, "is_live": False, "source_health": "UNVERIFIED",
            "provider": "STATIC_UNIVERSE_FALLBACK", "freshness": "UNVERIFIED"}


def test_pipeline_has_p2_expansion(tmp_path: Path):
    base = write_daily_payload(tmp_path / "p", run_date=SESSION,
                               movers=[_live_mover(), _static()], source_health="OK")
    r = run_daily_synthesis(payload_dir=base, fundamentals_by_ticker=_FUND)
    assert r["interpretation_expansion"]["status"] == "P2_INTERPRETATION_EXPANSION_COMPLETED"
    p2b = r["final_synthesis"]["p2_interpretation_expansion_board"]
    assert [row["ticker"] for row in p2b["board"]] == ["PLTR"]
    # Each candidate carries a compact expanded IDS.
    for c in r["clean_fresh_discovery_payload"]["candidates"]:
        assert "expanded_interpretation_defense" in c
    status = compact_status_lines(r)
    assert any("p2_interpretation_expansion" in line for line in status)


def test_static_never_in_p2_board(tmp_path: Path):
    base = write_daily_payload(tmp_path / "p", run_date=SESSION,
                               movers=[_live_mover(), _static("NVDA")], source_health="OK")
    r = run_daily_synthesis(payload_dir=base, fundamentals_by_ticker=_FUND)
    assert "NVDA" not in {b["ticker"] for b in r["interpretation_expansion"]["board"]}
    assert "NVDA" in r["fresh_discovery_contract"]["blocked_fallback_names"]


def test_no_fresh_discovery_skips_p2(tmp_path: Path):
    base = write_daily_payload(tmp_path / "p", run_date=SESSION, movers=[],
                               source_health="MISSING_OR_UNVERIFIED")
    r = run_daily_synthesis(payload_dir=base)
    assert r["interpretation_expansion"]["status"] == "SKIPPED_NO_FRESH_DISCOVERY"
    assert r["final_synthesis"]["p2_interpretation_expansion_board"]["skipped"] is True
    assert "p2_interpretation_expansion: SKIPPED" in compact_status_lines(r)


def test_model_cannot_override_p2_defensive():
    clean = {
        "fresh_discovery_status": "FRESH_DISCOVERY_OK",
        "run_date": SESSION,
        "candidates": [
            {"ticker": "PLTR",
             "interpretation_defense": {"interpretation_defense_grade": "CAUTION"},
             "expanded_interpretation_defense": {"expanded_grade": "DEFENSIVE_REVIEW"}}
        ],
    }
    raw = {"manual_consideration": [{"ticker": "PLTR"}]}
    cleaned = validate_model_lane_output("gpt", raw, clean)
    assert all(i["ticker"] != "PLTR" for i in cleaned["manual_consideration"])
    assert any(i["ticker"] == "PLTR" for i in cleaned["wait"])
    codes = {v["code"] for v in cleaned["provenance_violations_detected"]}
    assert IGNORED_P2_DEFENSE_VIOLATION in codes


def test_model_cannot_override_p2_blocked():
    clean = {
        "fresh_discovery_status": "FRESH_DISCOVERY_OK",
        "run_date": SESSION,
        "candidates": [
            {"ticker": "PLTR",
             "interpretation_defense": {"interpretation_defense_grade": "DEFENSIVE_REVIEW"},
             "expanded_interpretation_defense": {"expanded_grade": "BLOCKED"}}
        ],
    }
    raw = {"watch": [{"ticker": "PLTR"}]}
    cleaned = validate_model_lane_output("grok", raw, clean)
    assert any(i["ticker"] == "PLTR" for i in cleaned["risk_blocks"])
    assert IGNORED_P2_DEFENSE_VIOLATION in {v["code"] for v in cleaned["provenance_violations_detected"]}


def test_holdings_and_moltbook_stay_separate(tmp_path: Path):
    base = write_daily_payload(tmp_path / "p", run_date=SESSION,
                               verified=[holding("MSFT"), holding("ASML")],
                               movers=[_live_mover()], source_health="OK")
    r = run_daily_synthesis(payload_dir=base, fundamentals_by_ticker=_FUND)
    assert {b["ticker"] for b in r["interpretation_expansion"]["board"]} == {"PLTR"}
    assert set(r["existing_holding_review"]["verified_open_holdings"]) == {"MSFT", "ASML"}
    assert "p2_interpretation_lessons" in r["moltbook_learning_review"]


def test_final_synthesis_remains_auditor_only(tmp_path: Path):
    base = write_daily_payload(tmp_path / "p", run_date=SESSION,
                               movers=[_live_mover()], source_health="OK")
    r = run_daily_synthesis(payload_dir=base, fundamentals_by_ticker=_FUND)
    fs = r["final_synthesis"]
    assert fs["role"] == "FINAL_AUDITOR" and fs["generates_candidates"] is False
    assert_no_candidate_invention(fs, r["clean_fresh_discovery_payload"])


def test_runtime_p2_artifacts_written(tmp_path: Path, monkeypatch):
    base = write_daily_payload(tmp_path / "p", run_date=SESSION,
                               movers=[_live_mover()], source_health="OK")
    r = run_daily_synthesis(payload_dir=base, fundamentals_by_ticker=_FUND)
    monkeypatch.setattr(dsp, "REPO_ROOT", tmp_path)
    run_dir = write_isolated_run_artifacts(r)
    p2 = run_dir / "interpretation_defense" / "p2"
    for name in ("distribution_amplification.json", "narrative_substance_gap.json",
                 "incentive_who_benefits.json", "audience_misinterpretation_risk.json",
                 "expanded_interpretation_defense_board.json"):
        assert (p2 / name).exists()
    import json
    report = json.loads((run_dir / "capability_upgrade_report.json").read_text(encoding="utf-8"))
    assert report["expanded_ids_enabled"] is True
    assert "p2_modules_added" in report


def test_advisory_only_preserved(tmp_path: Path):
    base = write_daily_payload(tmp_path / "p", run_date=SESSION,
                               movers=[_live_mover()], source_health="OK")
    r = run_daily_synthesis(payload_dir=base, fundamentals_by_ticker=_FUND)
    for row in r["interpretation_expansion"]["board"]:
        assert row["advisory_only"] is True
    assert r["interpretation_expansion"]["safety"]["execution_gate"] == "LOCKED"
