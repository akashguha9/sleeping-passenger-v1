"""Tests for the source-run ledger / live-source refresh discipline."""
from __future__ import annotations

import json

import pytest

from scripts import source_run_ledger as srl


def test_fixture_refresh_summary_writes(tmp_path):
    target = tmp_path / "live_source_refresh_summary.json"
    summary = srl.write_summary(target, mode="fixture")
    assert target.exists()
    assert summary["mode"] == "fixture"
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["lpq"] > 0.0
    assert on_disk["live_payload_quality_score"] >= 8.2
    assert on_disk["fixture_verified_provider_count"] == 4
    assert on_disk["verified_provider_count"] == 0


def test_live_mode_degrades_gracefully_offline(monkeypatch):
    monkeypatch.delenv("MVP_LIVE_REFRESH_OK", raising=False)
    summary = srl.refresh(mode="live")
    # All providers must be OFFLINE/UNVERIFIED — we never invent live data.
    assert summary["offline_provider_count"] == len(srl.PROVIDER_CLASS)
    assert summary["verified_provider_count"] == 0
    assert all(p["blocks_promotion"] for p in summary["providers"])
    # LPQ must be 0 — OFFLINE/UNVERIFIED cannot prop up the score.
    assert summary["lpq"] == 0.0


def test_fallback_and_mock_cannot_be_healthy():
    result = srl.ProviderResult(
        provider="x", source_type="price_mover",
        status="SUCCESS", verification_status="FALLBACK",
        latest_provider_timestamp_utc="2026-05-24T10:00:00Z",
    )
    s = result.as_summary("2026-05-24T10:00:00Z")
    # Verification score for FALLBACK is 0; weighted sum still includes the
    # freshness/availability/schema terms — but blocks_promotion must be true.
    assert s["blocks_promotion"] is True
    assert s["verification_score"] == 0.0


def test_offline_provider_does_not_update_latest_success_timestamp():
    summary = srl.refresh(mode="live")
    for p in summary["providers"]:
        assert p["status"] == "OFFLINE"
        # OFFLINE providers must not carry a freshness timestamp — verify the
        # contract: their latest_provider_timestamp_utc is None (or stale-ish).
        assert p["latest_provider_timestamp_utc"] is None


def test_stale_source_blocks_promotion():
    result = srl.ProviderResult(
        provider="x", source_type="news_event",
        status="STALE", verification_status="STALE",
        latest_provider_timestamp_utc="2026-04-01T10:00:00Z",
    )
    s = result.as_summary("2026-05-24T10:00:00Z")
    assert s["blocks_promotion"] is True
    assert s["verification_status"] == "STALE"


def test_lpq_uses_best_per_source_class():
    summaries = [
        {"source_type": "price_mover", "source_run_health": 0.9},
        {"source_type": "filing", "source_run_health": 0.8},
        {"source_type": "news_event", "source_run_health": 0.5},
        {"source_type": "news_event", "source_run_health": 0.9},  # better
        {"source_type": "ai_report", "source_run_health": 0.3},
    ]
    lpq = srl.compute_lpq(summaries)
    expected = (
        0.30 * 0.9 + 0.25 * 0.8 + 0.25 * 0.9 + 0.20 * 0.3
    )
    assert abs(lpq - round(expected, 6)) < 1e-6


def test_freshness_score_half_life_behaviour():
    # At one half-life the score should be ~0.5.
    assert abs(srl.freshness_score(6.0, 6.0) - 0.5) < 1e-6
    # At zero age, exactly 1.0.
    assert srl.freshness_score(0.0, 6.0) == 1.0
    # Far past the half-life, well below 0.5.
    assert srl.freshness_score(48.0, 6.0) < 0.05


def test_release_gate_can_read_summary(tmp_path):
    target = tmp_path / "summary.json"
    srl.write_summary(target, mode="fixture")
    summary = srl.read_summary(target)
    assert summary is not None
    assert summary["mode"] == "fixture"
    assert summary["advisory_only"] is True
    assert summary["broker_api_called"] is False
    assert summary["ai_execution_count"] == 0


def test_invalid_mode_rejected():
    with pytest.raises(ValueError):
        srl.refresh(mode="paper")
