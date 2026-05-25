"""
Tests for the operator-visible CLIs added to scripts/source_health_summary.py
and scripts/source_health_score.py.

These tests do not require a live DB — they monkeypatch the persistence
helpers so the CLIs run against an in-memory fixture.  They guard the
operator-readable text path AND the ``--json`` machine path.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from contextlib import redirect_stdout

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _fake_latest_runs() -> list[dict]:
    return [
        {
            "source_name": "kalshi",
            "status": "TIMEOUT",
            "timestamp_utc": "2026-05-24T09:00:00Z",
            "skipped_reason": "upstream 503",
            "error_message": "",
            "fetched_count": 0,
            "duration_ms": 1000,
        },
        {
            "source_name": "gdelt",
            "status": "TIMEOUT",
            "timestamp_utc": "2026-05-24T22:30:00Z",
            "skipped_reason": "timeout",
            "error_message": "upstream timeout after 10s",
            "fetched_count": 0,
            "duration_ms": 10000,
        },
        {
            "source_name": "polymarket",
            "status": "OK",
            "timestamp_utc": "2026-05-25T10:00:00Z",
            "skipped_reason": "",
            "error_message": "",
            "fetched_count": 12,
            "duration_ms": 800,
        },
    ]


def _fake_event_counts() -> dict[str, int]:
    return {"polymarket": 120, "kalshi": 4, "gdelt": 73}


def _fake_refresh_runs() -> dict[str, dict]:
    return {
        "gdelt": {
            "success": 0,
            "skipped": 1,
            "error_message": "upstream timeout after 10s",
            "skipped_reason": "timeout",
            "finished_at": "2026-05-25T10:34:00+00:00",
            "started_at": "2026-05-25T10:33:50+00:00",
        },
        "kalshi": {
            "success": 0,
            "skipped": 1,
            "error_message": "upstream 503",
            "skipped_reason": "rate_limited",
            "finished_at": "2026-05-25T10:34:00+00:00",
            "started_at": "2026-05-25T10:33:55+00:00",
        },
        "polymarket": {
            "success": 1,
            "skipped": 0,
            "error_message": "",
            "skipped_reason": "",
            "finished_at": "2026-05-25T10:00:00+00:00",
            "started_at": "2026-05-25T09:59:30+00:00",
        },
    }


@pytest.fixture
def _patched_persistence(monkeypatch):
    import scripts.persistence as p
    monkeypatch.setattr(p, "get_latest_source_run_per_source", lambda *a, **kw: _fake_latest_runs())
    monkeypatch.setattr(p, "count_signal_events_by_source", lambda *a, **kw: _fake_event_counts())
    monkeypatch.setattr(
        p, "get_latest_refresh_run_per_source", lambda *a, **kw: _fake_refresh_runs()
    )
    monkeypatch.setattr(p, "get_persisted_row_stats_per_source", lambda *a, **kw: {})
    return p


# ---------------------------------------------------------------------------
# source_health_summary.py
# ---------------------------------------------------------------------------


def test_summary_cli_text_includes_kalshi_and_gdelt(_patched_persistence) -> None:
    import scripts.source_health_summary as srv
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = srv._cli([])
    out = buf.getvalue()
    assert rc == 0
    assert "Sleeping Passenger" in out
    assert "kalshi" in out
    assert "gdelt" in out
    assert "Stale active sources" in out


def test_summary_cli_json_emits_valid_json(_patched_persistence) -> None:
    import scripts.source_health_summary as srv
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = srv._cli(["--json"])
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload.get("advisory_status")
    assert "freshness_snapshot" in payload
    src_keys = {s["source_name"] for s in payload.get("sources", [])}
    assert "kalshi" in src_keys
    assert "gdelt" in src_keys
    # Etherscan absent from latest_runs but registry will add it as NO_RUNS.
    assert "etherscan" in src_keys


def test_summary_cli_quiet_only_prints_counts(_patched_persistence) -> None:
    import scripts.source_health_summary as srv
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = srv._cli(["--quiet"])
    assert rc == 0
    out = buf.getvalue().strip()
    assert out.startswith("ok=")
    assert "total=" in out
    assert "kalshi" not in out


# ---------------------------------------------------------------------------
# source_health_score.py
# ---------------------------------------------------------------------------


def test_score_cli_text_lists_sources_and_aggregate(_patched_persistence) -> None:
    import scripts.source_health_score as srv
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = srv._cli([])
    out = buf.getvalue()
    assert rc == 0
    assert "Source Health Scorecard" in out
    assert "core_health_label" in out
    assert "kalshi" in out
    assert "gdelt" in out


def test_score_cli_json(_patched_persistence) -> None:
    import scripts.source_health_score as srv
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = srv._cli(["--json"])
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload["advisory_status"]
    assert payload["broker_api_called"] is False
    assert payload["can_execute"] is False
    assert payload["ai_execution_count"] == 0
    assert "per_source" in payload
    assert "aggregate" in payload
