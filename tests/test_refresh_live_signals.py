"""Tests for the local 6-hour refresh orchestrator and stale-source API.

These tests:
  * Never invoke a live adapter (we monkeypatch the runners).
  * Confirm one source failing does not crash the whole run.
  * Confirm sources missing API keys are skipped with safe reasons.
  * Confirm refresh metadata persists to the new
    ``live_source_refresh_runs`` table.
  * Confirm secrets never appear in stdout.
  * Confirm advisory invariants are stamped on every row and the summary.
  * Confirm the API stale-source builder reports stale rows from old DB
    timestamps and surfaces source_errors.
  * Confirm scheduled-task PowerShell scripts exist and contain no secrets.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _all_keys_set(monkeypatch) -> None:
    monkeypatch.setenv("NEWS_API_KEY", "fake-news-key-not-real-1234567890")
    monkeypatch.setenv("EVENT_REGISTRY_API_KEY", "fake-er-key-not-real-1234567890")
    monkeypatch.setenv("ETHERSCAN_API_KEY", "fake-eth-key-not-real-1234567890")
    monkeypatch.setenv("XAI_API_KEY", "fake-xai-key-not-real-1234567890")
    monkeypatch.setenv("SEC_USER_AGENT", "SleepingPassenger contact@example.com")


def _no_live_keys(monkeypatch) -> None:
    for key in (
        "NEWS_API_KEY",
        "NEWSAPI_KEY",
        "EVENT_REGISTRY_API_KEY",
        "ETHERSCAN_API_KEY",
        "XAI_API_KEY",
        "GROK_API_KEY",
        "SEC_USER_AGENT",
    ):
        monkeypatch.delenv(key, raising=False)


def _isolated_db(tmp_path: Path, monkeypatch) -> Path:
    """Point persistence at a fresh DB and init the schema."""
    import scripts.persistence as p

    db = tmp_path / "refresh.db"
    monkeypatch.setattr(p, "DB_PATH", db)
    p.init_schema(db)
    return db


# ---------------------------------------------------------------------------
# Persistence — new table + helpers
# ---------------------------------------------------------------------------


def test_live_source_refresh_runs_table_exists(tmp_path):
    import scripts.persistence as p

    db = tmp_path / "schema_check.db"
    p.init_schema(db)
    con = sqlite3.connect(db)
    try:
        row = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name='live_source_refresh_runs'"
        ).fetchone()
        assert row is not None
        cols = [r[1] for r in con.execute(
            "PRAGMA table_info(live_source_refresh_runs)"
        )]
    finally:
        con.close()
    for required in (
        "run_id",
        "source_name",
        "attempted",
        "success",
        "skipped",
        "started_at",
        "finished_at",
        "duration_seconds",
        "rows_before",
        "rows_after",
        "rows_added",
        "error_message",
        "skipped_reason",
        "advisory_only",
        "execution_gate",
        "broker_api_called",
        "can_execute",
    ):
        assert required in cols, f"missing column {required}"


def test_record_and_get_latest_refresh_run(tmp_path, monkeypatch):
    import scripts.persistence as p

    db = _isolated_db(tmp_path, monkeypatch)
    p.record_live_source_refresh_run(
        run_id="r1",
        source_name="polymarket",
        attempted=True,
        success=True,
        skipped=False,
        started_at="2026-05-14T17:00:00+00:00",
        finished_at="2026-05-14T17:00:05+00:00",
        duration_seconds=5.0,
        rows_before=100,
        rows_after=110,
        rows_added=10,
        db_path=db,
    )
    p.record_live_source_refresh_run(
        run_id="r2",
        source_name="polymarket",
        attempted=True,
        success=False,
        skipped=True,
        started_at="2026-05-14T17:01:00+00:00",
        finished_at="2026-05-14T17:01:01+00:00",
        duration_seconds=1.0,
        rows_before=110,
        rows_after=110,
        rows_added=0,
        skipped_reason="missing_credentials: NEWS_API_KEY",
        db_path=db,
    )
    latest = p.get_latest_refresh_run_per_source(db)
    assert "polymarket" in latest
    row = latest["polymarket"]
    assert row["run_id"] == "r2"
    assert row["success"] == 0
    assert row["skipped"] == 1
    assert row["advisory_status"] == "ADVISORY_ONLY"
    assert row["execution_gate"] == "LOCKED"
    assert row["broker_api_called"] is False
    assert row["can_execute"] is False


# ---------------------------------------------------------------------------
# Orchestrator — refresh_live_signals
# ---------------------------------------------------------------------------


class _StubRunResult:
    def __init__(self, status: str, fetched: int = 0, persisted: int = 0,
                 skipped_reason: str = "", error_message: str = ""):
        self.status = status
        self.fetched_count = fetched
        self.accepted_count = fetched
        self.rejected_count = 0
        self.events_persisted = persisted
        self.skipped_reason = skipped_reason
        self.error_message = error_message
        self.timestamp_utc = "2026-05-14T17:00:00+00:00"
        self.duration_ms = 10

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "fetched_count": self.fetched_count,
            "events_persisted": self.events_persisted,
            "skipped_reason": self.skipped_reason,
            "error_message": self.error_message,
        }


class _StubReport:
    def __init__(self, source_name: str, status: str, persisted: int = 0,
                 fetched: int = 0):
        self.sources = [_StubRunResult(status, fetched=fetched, persisted=persisted)]


def _make_phase_stub(per_source: dict[str, str]):
    """Return a callable that mimics run_phase1/run_phase2 signatures.

    ``per_source`` maps source_name -> status ("ok", "skipped", "error", "raise").
    """

    def _stub(dry_run: bool = True, sources: list[str] | None = None, **kwargs):
        target = (sources or [None])[0]
        status = per_source.get(target, "ok")
        if status == "raise":
            raise RuntimeError(f"adapter blew up: {target}")
        persisted = 0 if dry_run else 5
        fetched = 5 if status == "ok" else 0
        report = _StubReport(target, status, persisted=persisted, fetched=fetched)
        return report

    return _stub


def test_orchestrator_isolates_one_failing_source(tmp_path, monkeypatch):
    _all_keys_set(monkeypatch)
    _isolated_db(tmp_path, monkeypatch)

    import scripts.refresh_live_signals as orch

    monkeypatch.setattr(
        orch,
        "_invoke_phase1_single",
        lambda key, dry_run: _make_phase_stub({
            "polymarket": "ok", "gdelt": "raise", "sec_edgar": "ok",
        })(dry_run=dry_run, sources=[key]).sources[0].to_dict(),
    )
    monkeypatch.setattr(
        orch,
        "_invoke_phase2_single",
        lambda key, dry_run: _make_phase_stub({
            "newsapi": "ok", "event_registry": "ok", "etherscan": "ok",
            "grok_xai": "ok", "market_data": "ok", "india": "ok",
            "global_filings": "ok",
        })(dry_run=dry_run, sources=[key]).sources[0].to_dict(),
    )

    summary = orch.run_refresh(write_mode=False)
    by_source = {e["source_name"]: e for e in summary["entries"]}
    # gdelt raised — captured as not-success, not-skipped (failed) but loop
    # kept going. polymarket OK.
    assert by_source["polymarket"]["success"] is True
    assert by_source["gdelt"]["success"] is False
    assert by_source["gdelt"]["skipped"] is False
    assert "adapter blew up" in by_source["gdelt"]["error_message"]
    # Loop covered all sources from registry — at least 8 non-failure rows.
    assert summary["total_sources_attempted"] >= 10
    assert summary["total_sources_failed"] >= 1


def test_orchestrator_skips_missing_credentials_safely(tmp_path, monkeypatch, capsys):
    _no_live_keys(monkeypatch)
    _isolated_db(tmp_path, monkeypatch)

    import scripts.refresh_live_signals as orch

    # Even if a runner is invoked, it should NOT be called for sources without
    # credentials. We set the runners to raise so we can catch any call.
    def _explode(*a, **kw):
        raise AssertionError("must not invoke runner for missing-creds source")

    monkeypatch.setattr(orch, "_invoke_phase1_single", lambda key, dry_run: {"status": "ok"})
    monkeypatch.setattr(orch, "_invoke_phase2_single", _explode)

    summary = orch.run_refresh(write_mode=False)
    by_source = {e["source_name"]: e for e in summary["entries"]}
    for src in ("newsapi", "event_registry", "etherscan", "grok_xai"):
        entry = by_source[src]
        assert entry["skipped"] is True
        assert entry["skipped_reason"].startswith("missing_credentials")
        # Secrets must NEVER appear in skip reason.
        assert "fake-" not in entry["skipped_reason"]

    out = capsys.readouterr().out
    assert "fake-" not in out


def test_orchestrator_does_not_print_secret_values(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XAI_API_KEY", "xai-supersecretvaluethatshouldneverappear")
    monkeypatch.setenv("NEWS_API_KEY", "news-supersecretvaluethatshouldneverappear")
    monkeypatch.delenv("EVENT_REGISTRY_API_KEY", raising=False)
    monkeypatch.delenv("ETHERSCAN_API_KEY", raising=False)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    _isolated_db(tmp_path, monkeypatch)

    import scripts.refresh_live_signals as orch

    monkeypatch.setattr(orch, "_invoke_phase1_single", lambda key, dry_run: {"status": "ok"})
    monkeypatch.setattr(orch, "_invoke_phase2_single", lambda key, dry_run: {"status": "ok"})

    rc = orch.main(["--summary", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "supersecretvaluethatshouldneverappear" not in out


def test_orchestrator_summary_carries_safety_stamps(tmp_path, monkeypatch):
    _no_live_keys(monkeypatch)
    _isolated_db(tmp_path, monkeypatch)

    import scripts.refresh_live_signals as orch

    summary = orch.run_refresh(summary_only=True)
    assert summary["advisory_status"] == "ADVISORY_ONLY"
    assert summary["execution_gate"] == "LOCKED"
    assert summary["broker_api_called"] is False
    assert summary["can_execute"] is False
    assert summary["ai_execution_count"] == 0
    assert summary["human_review_required"] is True


def test_orchestrator_persists_summary_json(tmp_path, monkeypatch):
    _no_live_keys(monkeypatch)
    _isolated_db(tmp_path, monkeypatch)

    import scripts.refresh_live_signals as orch

    monkeypatch.setattr(orch, "_invoke_phase1_single", lambda key, dry_run: {"status": "ok"})
    monkeypatch.setattr(orch, "_invoke_phase2_single", lambda key, dry_run: {"status": "ok"})

    target = tmp_path / "live_signal_refresh_summary.json"
    monkeypatch.setattr(orch, "_LOG_DIR", tmp_path)
    monkeypatch.setattr(orch, "_SUMMARY_PATH", target)

    summary = orch.run_refresh(write_mode=False)
    assert target.exists()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    assert payload["run_id"] == summary["run_id"]
    assert payload["broker_api_called"] is False


def test_refresh_runs_table_records_attempt(tmp_path, monkeypatch):
    _all_keys_set(monkeypatch)
    db = _isolated_db(tmp_path, monkeypatch)

    import scripts.refresh_live_signals as orch
    import scripts.persistence as p

    monkeypatch.setattr(orch, "_invoke_phase1_single",
                        lambda key, dry_run: {"status": "ok", "fetched_count": 3,
                                              "events_persisted": 3, "skipped_reason": "",
                                              "error_message": ""})
    monkeypatch.setattr(orch, "_invoke_phase2_single",
                        lambda key, dry_run: {"status": "ok", "fetched_count": 3,
                                              "events_persisted": 3, "skipped_reason": "",
                                              "error_message": ""})

    orch.run_refresh(write_mode=False)
    rows = p.get_latest_refresh_run_per_source(db)
    assert "polymarket" in rows
    assert rows["polymarket"]["advisory_status"] == "ADVISORY_ONLY"
    assert rows["polymarket"]["execution_gate"] == "LOCKED"
    assert rows["polymarket"]["broker_api_called"] is False


# ---------------------------------------------------------------------------
# API stale-source builder
# ---------------------------------------------------------------------------


def test_api_marks_old_latest_fetched_as_stale(tmp_path, monkeypatch):
    db = _isolated_db(tmp_path, monkeypatch)
    import scripts.persistence as p

    # Seed a source_run_log success 3 days ago.
    p.log_source_run(
        source_name="polymarket",
        status="ok",
        fetched_count=10,
        skipped_reason="",
        error_message="",
        timestamp_utc="2026-05-11T17:00:00+00:00",
        duration_ms=10,
        db_path=db,
    )
    p.record_live_source_refresh_run(
        run_id="r1",
        source_name="polymarket",
        attempted=True,
        success=True,
        skipped=False,
        started_at="2026-05-11T17:00:00+00:00",
        finished_at="2026-05-11T17:00:01+00:00",
        duration_seconds=1.0,
        rows_before=0,
        rows_after=10,
        rows_added=10,
        db_path=db,
    )

    from scripts.api_server import _build_live_sources_status

    payload = _build_live_sources_status(now_iso="2026-05-14T17:00:00+00:00")
    assert payload["refresh_configured"] is True
    assert "polymarket" in payload["stale_sources"]
    entry = payload["sources"]["polymarket"]
    assert entry["is_stale"] is True
    assert entry["refresh_age_hours"] is not None
    assert entry["refresh_age_hours"] > 6
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    assert payload["execution_gate"] == "LOCKED"
    assert payload["broker_api_called"] is False
    assert payload["can_execute"] is False


def test_api_reports_no_refresh_configured_when_table_empty(tmp_path, monkeypatch):
    _isolated_db(tmp_path, monkeypatch)
    from scripts.api_server import _build_live_sources_status

    payload = _build_live_sources_status(now_iso="2026-05-14T17:00:00+00:00")
    assert payload["refresh_configured"] is False
    # Pre-fix Live Signals page must not crash on this payload.
    assert "sources" in payload
    assert "stale_threshold_hours" in payload
    assert payload["stale_threshold_hours"] == 6
    assert payload["broker_api_called"] is False


def test_api_response_remains_backward_compatible(tmp_path, monkeypatch):
    _isolated_db(tmp_path, monkeypatch)
    from scripts.api_server import _build_live_sources_status

    payload = _build_live_sources_status()
    for required in ("sources", "source_count", "freshness_distribution",
                     "advisory_status", "execution_gate", "broker_api_called",
                     "ai_execution_count", "can_execute"):
        assert required in payload


def test_api_propagates_source_errors_from_refresh_runs(tmp_path, monkeypatch):
    db = _isolated_db(tmp_path, monkeypatch)
    import scripts.persistence as p

    p.log_source_run(
        source_name="etherscan",
        status="ok",
        fetched_count=10,
        skipped_reason="",
        error_message="",
        timestamp_utc="2026-05-14T16:30:00+00:00",
        duration_ms=10,
        db_path=db,
    )
    p.record_live_source_refresh_run(
        run_id="r1",
        source_name="etherscan",
        attempted=True,
        success=False,
        skipped=False,
        started_at="2026-05-14T16:30:00+00:00",
        finished_at="2026-05-14T16:30:01+00:00",
        duration_seconds=1.0,
        error_message="HTTPError: 429 too many requests",
        db_path=db,
    )

    from scripts.api_server import _build_live_sources_status

    payload = _build_live_sources_status(now_iso="2026-05-14T17:00:00+00:00")
    assert "etherscan" in payload["source_errors"]
    assert payload["source_errors"]["etherscan"].startswith("HTTPError")


# ---------------------------------------------------------------------------
# Scheduled-task PowerShell scripts: exist, no secrets, no execution syntax
# ---------------------------------------------------------------------------


def test_windows_refresh_scripts_exist_and_carry_no_secrets():
    once = _REPO_ROOT / "scripts" / "windows" / "run_live_signal_refresh_once.ps1"
    register = _REPO_ROOT / "scripts" / "windows" / "register_live_signal_refresh_task.ps1"
    assert once.exists(), f"missing {once}"
    assert register.exists(), f"missing {register}"

    # Look for concrete secret-leak patterns and concrete execution code.
    # The word "secret" itself is allowed (we use it in safety docs).
    secret_patterns = (
        "API_KEY=",
        "API_KEY =",
        "ApiKey=",
        "Authorization: Bearer",
        "Bearer eyJ",
        "AKIA",  # AWS access-key prefix
        "ghp_",  # GitHub PAT prefix
    )
    execution_patterns = (
        "place_order",
        "submit_order",
        "execute_trade",
        "broker_execute",
        "place-order",
    )
    for path in (once, register):
        text = path.read_text(encoding="utf-8")
        for needle in secret_patterns:
            assert needle not in text, f"{path.name} contains secret-like pattern {needle!r}"
        lowered = text.lower()
        for needle in execution_patterns:
            assert needle not in lowered, (
                f"{path.name} mentions execution pattern {needle!r}"
            )


def test_register_task_uses_6_hour_cadence_and_correct_name():
    register = _REPO_ROOT / "scripts" / "windows" / "register_live_signal_refresh_task.ps1"
    text = register.read_text(encoding="utf-8")
    assert "SleepingPassengerLiveSignalRefresh" in text
    assert "Hours 6" in text or "/SC HOURLY /MO 6" in text


# ---------------------------------------------------------------------------
# Docs reference the 6-hour cadence and the manual command
# ---------------------------------------------------------------------------


def test_doc_mentions_6_hour_cadence_and_manual_command():
    doc = _REPO_ROOT / "docs" / "LIVE_SIGNAL_REFRESH.md"
    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    assert "every 6 hours" in text.lower() or "6-hour" in text.lower()
    assert "python scripts/refresh_live_signals.py" in text


# ---------------------------------------------------------------------------
# No broker execution route was added in this sprint
# ---------------------------------------------------------------------------


def test_no_new_broker_execution_route_in_api_server():
    api = (_REPO_ROOT / "scripts" / "api_server.py").read_text(encoding="utf-8")
    for forbidden in (
        "place_order",
        "submit_order",
        "execute_trade",
        "broker_execute",
        "/broker/execute",
        "/broker/place_order",
    ):
        assert forbidden not in api, f"forbidden symbol {forbidden!r} reintroduced"
