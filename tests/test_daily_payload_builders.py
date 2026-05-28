"""Tests for the daily payload builders (Phase 1)."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.build_daily_payloads import PRESERVED_FILES, build_all_daily_payloads
from scripts.build_today_filings_events import build_today_filings_events
from scripts.build_today_market_snapshot import build_today_market_snapshot
from scripts.build_today_news_events import build_today_news_events
from scripts.build_today_price_movers import build_today_price_movers
from scripts.build_yesterday_final_candidates import build_yesterday_final_candidates

RUN_DATE = "2026-05-22"


def test_market_snapshot_is_valid_and_honest() -> None:
    payload = build_today_market_snapshot(RUN_DATE)
    assert payload["run_date"] == RUN_DATE
    for key in ("generated_at_utc", "source_health", "provider", "is_live", "indices", "macro_proxies"):
        assert key in payload
    assert payload["is_live"] is False
    assert payload["source_health"] == "UNVERIFIED"
    assert payload["provider"] == "STATIC_UNIVERSE_FALLBACK"
    # Legacy loader keys preserved.
    for key in ("rates", "commodities", "fx", "regime_notes"):
        assert isinstance(payload[key], list)


def test_price_movers_every_record_has_why_today_and_required_fields() -> None:
    payload = build_today_price_movers(RUN_DATE)
    assert payload["is_live"] is False
    assert payload["movers"], "fallback movers must not be empty"
    assert payload["movers"] is payload["records"] or payload["movers"] == payload["records"]
    required = {
        "ticker", "bucket", "market", "freshness", "source_health",
        "provider", "is_live", "why_today", "data_quality",
    }
    for rec in payload["movers"]:
        assert required.issubset(set(rec)), f"mover missing fields: {required - set(rec)}"
        assert rec["why_today"], "every price mover must carry a non-empty why_today"
        assert rec["freshness"] == "UNVERIFIED"
        assert rec["is_live"] is False
        assert rec["price"] is None and rec["move_pct"] is None


def test_price_movers_rotation_changes_by_date() -> None:
    a = [m["ticker"] for m in build_today_price_movers("2026-05-22")["movers"]]
    b = [m["ticker"] for m in build_today_price_movers("2026-08-01")["movers"]]
    assert a != b, "static universe should rotate by run_date"


def test_news_events_empty_fallback_is_valid() -> None:
    payload = build_today_news_events(RUN_DATE)
    assert payload["events"] == []
    assert payload["is_live"] is False
    assert payload["provider"] == "STATIC_OR_EMPTY_FALLBACK"


def test_news_events_static_watch_is_unverified() -> None:
    payload = build_today_news_events(RUN_DATE, with_static_watch=True)
    assert payload["events"], "static watch should produce rows"
    for ev in payload["events"]:
        assert ev["freshness"] == "UNVERIFIED"
        assert ev["is_live"] is False
        assert ev["confidence"] == 0.0
        assert ev["why_today"]


def test_filings_events_empty_fallback_is_valid() -> None:
    payload = build_today_filings_events(RUN_DATE)
    assert payload["events"] == []
    assert payload["is_live"] is False
    assert payload["provider"] == "EMPTY_FALLBACK"


def test_yesterday_candidates_does_not_crash_when_missing(tmp_path: Path) -> None:
    payload = build_yesterday_final_candidates(
        RUN_DATE,
        synthesis_context_path=tmp_path / "no_ctx.json",
        existing_payload_path=tmp_path / "no_payload.json",
    )
    assert payload["source"] == "empty_fallback"
    assert payload["final_candidates"] == []


def test_orchestrator_writes_all_and_preserves_protected(tmp_path: Path) -> None:
    base = tmp_path / "payload"
    base.mkdir()
    # Seed protected files with sentinel content.
    verified = base / "verified_current_holdings.json"
    dnt = base / "do_not_treat_as_open.json"
    verified.write_text(json.dumps({"run_date": RUN_DATE, "positions": [{"ticker": "ANET"}]}), encoding="utf-8")
    dnt.write_text(json.dumps({"run_date": RUN_DATE, "not_owned_do_not_manage": ["UNG"]}), encoding="utf-8")
    verified_before = verified.read_text(encoding="utf-8")
    dnt_before = dnt.read_text(encoding="utf-8")

    # Point the live bridges at a non-existent DB so they deterministically
    # fall back to the static/empty builders (this test covers the fallback
    # path; the live bridge is covered by its own test module).
    summary = build_all_daily_payloads(
        run_date=RUN_DATE, payload_dir=base, db_path=tmp_path / "no_such.db"
    )

    assert set(summary["files_written"]) == {
        "today_market_snapshot.json", "today_price_movers.json",
        "today_news_events.json", "today_filings_events.json",
        "yesterday_final_candidates.json", "daily_payload_manifest.json",
    }
    # Protected files untouched.
    assert verified.read_text(encoding="utf-8") == verified_before
    assert dnt.read_text(encoding="utf-8") == dnt_before
    assert set(PRESERVED_FILES) >= {"verified_current_holdings.json", "do_not_treat_as_open.json"}
    # Honest status (no live provider wired).
    assert summary["discovery_live"] is False
    assert summary["discovery_status"] == "UNDERPOWERED_FALLBACK"
    # Each written file is valid JSON.
    for name in summary["files_written"]:
        json.loads((base / name).read_text(encoding="utf-8"))
    # Manifest records the honest fallback.
    manifest = json.loads((base / "daily_payload_manifest.json").read_text(encoding="utf-8"))
    assert manifest["signal_events_bridge_attempted"] is True
    assert manifest["signal_events_bridge_status"] == "FALLBACK"


def test_orchestrator_safety_intact(tmp_path: Path) -> None:
    base = tmp_path / "p"
    base.mkdir()
    summary = build_all_daily_payloads(run_date=RUN_DATE, payload_dir=base)
    assert summary["safety"]["execution_gate"] == "LOCKED"
    assert summary["safety"]["broker_api_called"] is False
    assert summary["safety"]["ai_execution_count"] == 0
    assert summary["safety"]["can_execute"] is False
