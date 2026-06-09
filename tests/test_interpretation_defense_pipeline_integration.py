"""Integration tests: interpretation defense wired through the daily pipeline."""
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
    IGNORED_DEFENSE_VIOLATION,
    validate_model_lane_output,
)

SESSION = "2026-06-07"
_FUND = {"PLTR": {"debt_to_equity": 0.3, "gross_margin": 0.8, "current_ratio": 2.4,
                  "earnings_stability": 0.7, "interest_coverage": 8}}


def _live_mover(ticker="PLTR"):
    return {
        "ticker": ticker, "is_live": True, "source_health": "VERIFIED_LIVE",
        "provider": "yahoo_live", "freshness": "FRESH_TODAY",
        "timestamp_utc": f"{SESSION}T13:00:00Z", "why_today": "Live gap + volume today",
        "sector": "Software", "country": "United States", "theme": "AI",
    }


def _static(ticker="NVDA"):
    return {"ticker": ticker, "is_live": False, "source_health": "UNVERIFIED",
            "provider": "STATIC_UNIVERSE_FALLBACK", "freshness": "UNVERIFIED"}


# --- Live candidate path -----------------------------------------------------

def test_pipeline_live_candidate_has_interpretation_defense(tmp_path: Path):
    base = write_daily_payload(tmp_path / "p", run_date=SESSION,
                               movers=[_live_mover(), _static()], source_health="OK")
    r = run_daily_synthesis(payload_dir=base, fundamentals_by_ticker=_FUND)

    defense = r["interpretation_defense"]
    assert defense["status"] == "INTERPRETATION_DEFENSE_COMPLETED"
    assert {b["ticker"] for b in defense["board"]} == {"PLTR"}

    idb = r["final_synthesis"]["interpretation_defense_board"]
    assert idb["status"] == "INTERPRETATION_DEFENSE_COMPLETED"
    assert [row["ticker"] for row in idb["board"]] == ["PLTR"]
    # Each clean-payload candidate carries a compact IDS.
    for c in r["clean_fresh_discovery_payload"]["candidates"]:
        assert "interpretation_defense" in c
    status = compact_status_lines(r)
    assert any("interpretation_defense" in line for line in status)


def test_static_name_never_in_interpretation_defense(tmp_path: Path):
    base = write_daily_payload(tmp_path / "p", run_date=SESSION,
                               movers=[_live_mover(), _static("NVDA")], source_health="OK")
    r = run_daily_synthesis(payload_dir=base, fundamentals_by_ticker=_FUND)
    board_tickers = {b["ticker"] for b in r["interpretation_defense"]["board"]}
    assert "NVDA" not in board_tickers
    # NVDA is still surfaced as blocked fallback (proving exclusion, not absence).
    assert "NVDA" in r["fresh_discovery_contract"]["blocked_fallback_names"]


# --- No fresh discovery ------------------------------------------------------

def test_no_fresh_discovery_skips_defense(tmp_path: Path):
    base = write_daily_payload(tmp_path / "p", run_date=SESSION, movers=[],
                               source_health="MISSING_OR_UNVERIFIED")
    r = run_daily_synthesis(payload_dir=base)
    assert r["interpretation_defense"]["status"] == "SKIPPED_NO_FRESH_DISCOVERY"
    assert r["interpretation_defense"]["board"] == []
    assert r["final_synthesis"]["interpretation_defense_board"]["skipped"] is True
    status = compact_status_lines(r)
    assert "p1_interpretation_defense: SKIPPED" in status
    assert "p2_interpretation_expansion: SKIPPED" in status


# --- Model cannot override a BLOCKED candidate -------------------------------

def test_model_cannot_override_blocked_candidate():
    clean = {
        "fresh_discovery_status": "FRESH_DISCOVERY_OK",
        "run_date": SESSION,
        "candidates": [
            {"ticker": "PLTR", "interpretation_defense": {"interpretation_defense_grade": "BLOCKED"}}
        ],
    }
    raw = {"manual_consideration": [{"ticker": "PLTR"}]}
    cleaned = validate_model_lane_output("gpt", raw, clean)
    assert all(i["ticker"] != "PLTR" for i in cleaned["manual_consideration"])
    assert any(i["ticker"] == "PLTR" for i in cleaned["risk_blocks"])
    codes = {v["code"] for v in cleaned["provenance_violations_detected"]}
    assert IGNORED_DEFENSE_VIOLATION in codes


# --- Channel separation ------------------------------------------------------

def test_holdings_and_moltbook_stay_separate(tmp_path: Path):
    base = write_daily_payload(tmp_path / "p", run_date=SESSION,
                               verified=[holding("MSFT"), holding("ASML")],
                               movers=[_live_mover()], source_health="OK")
    r = run_daily_synthesis(payload_dir=base, fundamentals_by_ticker=_FUND)
    board_tickers = {b["ticker"] for b in r["interpretation_defense"]["board"]}
    assert board_tickers == {"PLTR"}
    assert "MSFT" not in board_tickers and "ASML" not in board_tickers
    assert set(r["existing_holding_review"]["verified_open_holdings"]) == {"MSFT", "ASML"}
    # Moltbook learning carries interpretation-defense lessons (advisory).
    assert "interpretation_defense_lessons" in r["moltbook_learning_review"]


# --- Auditor discipline ------------------------------------------------------

def test_final_synthesis_remains_auditor_only(tmp_path: Path):
    base = write_daily_payload(tmp_path / "p", run_date=SESSION,
                               movers=[_live_mover()], source_health="OK")
    r = run_daily_synthesis(payload_dir=base, fundamentals_by_ticker=_FUND)
    fs = r["final_synthesis"]
    assert fs["role"] == "FINAL_AUDITOR"
    assert fs["generates_candidates"] is False
    # Invention guard still holds with the new board attached.
    assert_no_candidate_invention(fs, r["clean_fresh_discovery_payload"])


def test_advisory_only_preserved(tmp_path: Path):
    base = write_daily_payload(tmp_path / "p", run_date=SESSION,
                               movers=[_live_mover()], source_health="OK")
    r = run_daily_synthesis(payload_dir=base, fundamentals_by_ticker=_FUND)
    for row in r["final_synthesis"]["interpretation_defense_board"]["board"]:
        assert row["advisory_only"] is True
    assert r["interpretation_defense"]["safety"]["execution_gate"] == "LOCKED"


# --- Runtime artifacts -------------------------------------------------------

def test_runtime_artifacts_written(tmp_path: Path, monkeypatch):
    base = write_daily_payload(tmp_path / "p", run_date=SESSION,
                               movers=[_live_mover()], source_health="OK")
    r = run_daily_synthesis(payload_dir=base, fundamentals_by_ticker=_FUND)
    monkeypatch.setattr(dsp, "REPO_ROOT", tmp_path)
    run_dir = write_isolated_run_artifacts(r)
    idef = run_dir / "interpretation_defense"
    assert (idef / "interpretation_quality_scores.json").exists()
    assert (idef / "metric_regime_transfer_risk.json").exists()
    assert (idef / "adverse_regime_stress_tests.json").exists()
    assert (idef / "interpretation_defense_board.json").exists()
    assert (run_dir / "capability_upgrade_report.json").exists()


def test_runtime_artifacts_skipped_marker(tmp_path: Path, monkeypatch):
    base = write_daily_payload(tmp_path / "p", run_date=SESSION, movers=[],
                               source_health="MISSING_OR_UNVERIFIED")
    r = run_daily_synthesis(payload_dir=base)
    monkeypatch.setattr(dsp, "REPO_ROOT", tmp_path)
    run_dir = write_isolated_run_artifacts(r)
    assert (run_dir / "interpretation_defense" / "SKIPPED_NO_FRESH_DISCOVERY.json").exists()
