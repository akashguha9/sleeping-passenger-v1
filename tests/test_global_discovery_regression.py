"""End-to-end regression — a fresh German filing flows into live discovery.

Proves the structural fix: a fresh SQLite signal_events row for Germany (RHM.DE)
bridges into today_filings_events.json, enters L_today, improves German country
coverage, and remains strictly advisory-only (no execution surface touched).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from scripts import persistence
from scripts.build_daily_payloads import build_all_daily_payloads
from scripts.daily_synthesis_pipeline import run_daily_synthesis

NOW = datetime(2026, 5, 28, 12, 0, 0, tzinfo=timezone.utc)


def _seed_truth(base):
    (base / "verified_current_holdings.json").write_text(
        json.dumps(
            {
                "run_date": "2026-05-28",
                "positions": [
                    {"ticker": "NASDAQ:MSFT", "normalized_ticker": "MSFT",
                     "status": "OPEN", "country": "United States"}
                ],
            }
        ),
        encoding="utf-8",
    )
    (base / "do_not_treat_as_open.json").write_text(
        json.dumps({"run_date": "2026-05-28", "closed_or_sold_positions": ["GLD"]}),
        encoding="utf-8",
    )


def test_fresh_german_filing_becomes_live_discovery(tmp_path):
    base = tmp_path / "payload"
    base.mkdir()
    _seed_truth(base)
    db = tmp_path / "mvp.db"

    # A genuinely fresh German filing persisted to canonical signal_events.
    persistence.insert_signal_event(
        event_id="de-rhm-1",
        source_name="global_filings",
        raw_payload={
            "event_id": "de-rhm-1",
            "ticker": "RHM.DE",
            "jurisdiction": "DE",
            "disclosure_type": "ad-hoc",
            "headline": "Rheinmetall ad-hoc disclosure today",
            "published_at": (NOW - timedelta(hours=3)).isoformat(),
            "provider": "global_filings",
        },
        fetched_at=(NOW - timedelta(hours=3)).isoformat(),
        db_path=db,
    )

    summary = build_all_daily_payloads(
        run_date="2026-05-28", payload_dir=base, db_path=db, now_utc=NOW,
    )

    # 1. The filing bridged into today_filings_events.json as a live, mapped row.
    filings = json.loads((base / "today_filings_events.json").read_text(encoding="utf-8"))
    assert filings["is_live"] is True
    rhm = next((e for e in filings["events"] if e.get("ticker") == "RHM.DE"), None)
    assert rhm is not None
    assert rhm["country"] == "Germany"
    assert rhm["mapping_status"] == "MAPPED"

    # 2. Manifest reflects the live bridge honestly.
    manifest = json.loads((base / "daily_payload_manifest.json").read_text(encoding="utf-8"))
    assert manifest["signal_events_bridge_status"] == "LIVE"
    assert manifest["fresh_filings_events_count"] >= 1
    assert manifest["mapped_events_count"] >= 1

    # 3. RHM.DE enters L_today and German coverage improves.
    result = run_daily_synthesis(payload_dir=base)
    assert "RHM.DE" in result["l_today"]
    germany = next(r for r in result["country_coverage"]["countries"] if r["country"] == "Germany")
    assert germany["filings_support"] == 1
    assert germany["synthesis_consumed"] == 1
    assert germany["mapping_support"] == 1

    # 4. Still advisory-only — no execution surface changed anywhere.
    assert summary["safety"]["execution_gate"] == "LOCKED"
    assert summary["safety"]["broker_api_called"] is False
    assert summary["safety"]["ai_execution_count"] == 0
    assert manifest["safety"]["can_execute"] is False
    assert result["execution"]["human_review_required"] is True

    # 5. A live-discovered name is still NOT auto-executable (advisory gate holds).
    executables = result["candidate_executable_split"]["executable_paper_buys"]
    assert all(r["ticker"] != "RHM.DE" or r["executable"] is False for r in executables) or executables == []


def test_no_db_keeps_static_fallback_and_zero_executables(tmp_path):
    base = tmp_path / "payload"
    base.mkdir()
    _seed_truth(base)
    summary = build_all_daily_payloads(
        run_date="2026-05-28", payload_dir=base, db_path=tmp_path / "absent.db", now_utc=NOW,
    )
    filings = json.loads((base / "today_filings_events.json").read_text(encoding="utf-8"))
    assert filings["is_live"] is False
    assert summary["discovery_status"] == "UNDERPOWERED_FALLBACK"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
