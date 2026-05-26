"""Refresh totals must distinguish succeeded / degraded / failed / skipped."""
from __future__ import annotations

from scripts.refresh_live_signals import run_refresh
import scripts.refresh_live_signals as refresh


def test_degraded_kalshi_entry_does_not_inflate_succeeded(monkeypatch, tmp_path):
    """A DEGRADED Kalshi entry must be counted under total_sources_degraded, not succeeded."""

    def fake_run_one(run_id, source_key, *, write_mode, credential_state, db_path):
        if source_key == "kalshi":
            return {
                "run_id": run_id,
                "source_name": "kalshi",
                "display_name": "Kalshi",
                "phase": "phase1",
                "attempted": True,
                "success": False,
                "degraded": True,
                "skipped": False,
                "started_at": "2026-05-26T20:00:00+00:00",
                "finished_at": "2026-05-26T20:00:01+00:00",
                "duration_seconds": 1.0,
                "rows_before": 0,
                "rows_after": 0,
                "rows_added": 0,
                "skipped_reason": "",
                "error_message": "Kalshi API live; canonical signals ZERO_FRESH_ROWS.",
                "db_path": str(tmp_path / "iso.db"),
                "write_mode": True,
                "runner_status": "ok_filtered",
                "provider_result": "DEGRADED_ZERO_CANONICAL",
                "api_health_status": "LIVE_VERIFIED",
                "canonical_signal_status": "ZERO_FRESH_ROWS",
                "semantic_fresh": True,
            }
        return {
            "run_id": run_id,
            "source_name": source_key,
            "display_name": source_key.title(),
            "phase": "phase1",
            "attempted": True,
            "success": True,
            "degraded": False,
            "skipped": False,
            "started_at": "2026-05-26T20:00:00+00:00",
            "finished_at": "2026-05-26T20:00:01+00:00",
            "duration_seconds": 0.5,
            "rows_before": 0,
            "rows_after": 1,
            "rows_added": 1,
            "skipped_reason": "",
            "error_message": "",
            "db_path": str(tmp_path / "iso.db"),
            "write_mode": True,
            "runner_status": "ok",
        }

    monkeypatch.setattr(refresh, "_run_one_source", fake_run_one)
    summary = run_refresh(
        source_keys=["polymarket", "kalshi"],
        write_mode=True,
        summary_path=tmp_path / "summary.json",
    )
    assert summary["total_sources_attempted"] == 2
    assert summary["total_sources_succeeded"] == 1
    assert summary["total_sources_degraded"] == 1
    assert summary["total_sources_failed"] == 0
    assert summary["total_sources_skipped"] == 0


def test_skipped_counts_separately_from_failed(monkeypatch, tmp_path):
    def fake_run_one(run_id, source_key, *, write_mode, credential_state, db_path):
        return {
            "run_id": run_id,
            "source_name": source_key,
            "display_name": source_key,
            "phase": "phase1",
            "attempted": True,
            "success": False,
            "skipped": True,
            "started_at": "2026-05-26T20:00:00+00:00",
            "finished_at": "2026-05-26T20:00:01+00:00",
            "duration_seconds": 0.0,
            "rows_before": 0,
            "rows_after": 0,
            "rows_added": 0,
            "skipped_reason": "missing_credentials: FOO",
            "error_message": "",
            "db_path": str(tmp_path / "iso.db"),
            "write_mode": True,
            "runner_status": "skipped",
        }

    monkeypatch.setattr(refresh, "_run_one_source", fake_run_one)
    summary = run_refresh(
        source_keys=["kalshi"],
        write_mode=True,
        summary_path=tmp_path / "summary.json",
    )
    assert summary["total_sources_skipped"] == 1
    assert summary["total_sources_failed"] == 0
    assert summary["total_sources_succeeded"] == 0
