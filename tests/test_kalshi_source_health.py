"""
Parent Kalshi source-health evidence tests.

Every run attempt — successful, filtered, or failed — must leave a
``runtime/release/kalshi_source_health.json`` artifact with the full
advisory-safety block and an honest record-counts breakdown.

Tests inject ``tmp_path`` so no real ``runtime/release/`` file is
touched.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.ingestion.base_loader import LoaderResult, SkipLoader
from scripts.ingestion.kalshi_loader import KalshiLoader
from scripts.kalshi_runner import run_kalshi_ingest, write_kalshi_source_health


@pytest.fixture()
def isolated_health(tmp_path: Path):
    return tmp_path / "kalshi_source_health.json", tmp_path / "kalshi_quarantine.jsonl"


def _stub_loader(records):
    class _StubLoader:
        source_name = "kalshi"
        last_event_lookup: dict = {}

        def safe_fetch(self):
            return LoaderResult(source_name="kalshi", records=list(records))

    return _StubLoader()


def test_successful_run_writes_full_health_summary(isolated_health):
    health_path, quarantine_path = isolated_health
    records = [
        {
            "source": "kalshi",
            "ticker": "BTCMAY-2026",
            "title": "How high will Bitcoin get in May?",
            "category": "Crypto",
            "close_time_utc": "2026-05-31T23:59:00Z",
        },
        {
            "source": "kalshi",
            "ticker": "KXMVESPORTSMULTIGAMEEXTENDED-S2026376EC71BC21-CAF0CE6479C",
            "title": "yes Taylor Fritz, yes Hamad Medjedovic",
            "category": "esports",
        },
    ]
    result = run_kalshi_ingest(
        dry_run=True,
        loader=_stub_loader(records),
        health_path=health_path,
        quarantine_path=quarantine_path,
    )
    assert result.fetched_count == 2
    assert result.accepted_count == 1
    assert result.quarantined_count == 1
    assert health_path.exists()

    summary = json.loads(health_path.read_text(encoding="utf-8"))
    assert summary["source_name"] == "kalshi"
    assert summary["records_seen_total"] == 2
    assert summary["records_allowed"] == 1
    assert summary["records_quarantined"] == 1
    assert summary["status"] == "OK"
    assert summary["allowed_categories"] == sorted(
        {"elections", "politics", "crypto", "commodities", "economics", "finance", "tech_science"}
    )
    # Per-category bucket present.
    assert summary["category_allowed_counts"].get("crypto") == 1
    # Safety invariants.
    assert summary["advisory_only"] is True
    assert summary["human_review_required"] is True
    assert summary["execution_locked"] is True
    assert summary["broker_api_called"] is False
    assert summary["ai_execution_count"] == 0


def test_failed_run_still_writes_health_with_safety_block(isolated_health):
    health_path, quarantine_path = isolated_health

    class _SkippingLoader:
        source_name = "kalshi"
        last_event_lookup: dict = {}

        def safe_fetch(self):
            return LoaderResult(source_name="kalshi", records=[], skipped=True, skip_reason="upstream 503")

    result = run_kalshi_ingest(
        dry_run=True,
        loader=_SkippingLoader(),
        health_path=health_path,
        quarantine_path=quarantine_path,
    )
    assert result.status == "skipped"
    assert health_path.exists()
    summary = json.loads(health_path.read_text(encoding="utf-8"))
    assert summary["status"] == "SKIPPED"
    assert summary["skipped_reason"] == "upstream 503"
    assert summary["records_seen_total"] == 0
    assert summary["advisory_only"] is True
    assert summary["broker_api_called"] is False
    assert summary["ai_execution_count"] == 0


def test_quarantine_jsonl_captures_kxmvesports_with_reason(isolated_health):
    health_path, quarantine_path = isolated_health
    records = [
        {
            "source": "kalshi",
            "ticker": "KXMVESPORTSMULTIGAMEEXTENDED-S2026376EC71BC21-CAF0CE6479C",
            "event_ticker": "KXMVESPORTS-2026",
            "title": "yes Taylor Fritz, yes Hamad Medjedovic",
            "category": "esports",
        }
    ]
    run_kalshi_ingest(
        dry_run=True,
        loader=_stub_loader(records),
        health_path=health_path,
        quarantine_path=quarantine_path,
    )
    assert quarantine_path.exists()
    lines = [
        json.loads(line)
        for line in quarantine_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 1
    row = lines[0]
    assert row["source_name"] == "kalshi"
    assert "MVESPORTS" in row["ticker"]
    assert row["visible_in_kalshi_feed"] is False
    assert row["category_allowed"] is False
    assert "ticker_pattern_rejected" in row["quarantine_reason"]
    assert row["advisory_only"] is True
    assert row["broker_api_called"] is False
    assert row["ai_execution_count"] == 0


def test_runtime_isolation_default_path_not_touched(tmp_path):
    # When write_health=False the in-memory result is still populated
    # but no runtime/release/ file gets created.  This proves tests can
    # opt out cleanly when they don't care about artifacts.
    result = run_kalshi_ingest(
        dry_run=True,
        loader=_stub_loader(
            [
                {
                    "source": "kalshi",
                    "ticker": "BTCMAY-2026",
                    "title": "How high will Bitcoin get in May?",
                    "category": "Crypto",
                }
            ]
        ),
        write_health=False,
    )
    assert result.accepted_count == 1
    assert result.health_path == ""
