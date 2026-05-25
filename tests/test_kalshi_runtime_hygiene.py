"""Runtime hygiene tests for the Kalshi source-health surface.

Covers:
- Atomic source-health writes (no partial JSON survives an interrupted
  write).
- Sanitized JSONL history ledger (no auth headers, no API Key ID, no
  private-key contents).
- Quarantine rotation when the rolling cap is exceeded.
- Runtime secret scanner returns zero matches against the canonical
  source-health summary.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts.kalshi_runner import (
    DEFAULT_KALSHI_HEALTH_HISTORY_MAX_LINES,
    _atomic_write_json,
    append_kalshi_source_health_history,
    rotate_kalshi_quarantine,
    write_kalshi_source_health,
)


def test_atomic_write_json_does_not_leave_tmp_behind(tmp_path: Path):
    target = tmp_path / "kalshi_source_health.json"
    payload = {
        "source_name": "kalshi",
        "status": "OK",
        "records_allowed": 0,
        "records_quarantined": 0,
        "advisory_only": True,
        "broker_api_called": False,
        "ai_execution_count": 0,
    }
    _atomic_write_json(target, payload)
    assert target.exists()
    assert not target.with_suffix(target.suffix + ".tmp").exists()
    assert json.loads(target.read_text(encoding="utf-8"))["status"] == "OK"


def test_interrupted_atomic_write_does_not_corrupt_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    target = tmp_path / "kalshi_source_health.json"
    target.write_text(
        json.dumps({"status": "OK", "records_allowed": 7}),
        encoding="utf-8",
    )
    real_replace = os.replace

    def _boom(src, dst):
        raise OSError("simulated power loss before replace")

    monkeypatch.setattr(os, "replace", _boom)
    with pytest.raises(OSError):
        _atomic_write_json(target, {"status": "ERROR", "records_allowed": -1})
    # Original file is untouched and still valid JSON.
    assert json.loads(target.read_text(encoding="utf-8"))["status"] == "OK"
    # Restore replace and verify a real write still works.
    monkeypatch.setattr(os, "replace", real_replace)
    _atomic_write_json(target, {"status": "OK", "records_allowed": 1})
    assert json.loads(target.read_text(encoding="utf-8"))["status"] == "OK"


def test_history_ledger_appended_and_sanitized(tmp_path: Path):
    summary = {
        "completed_at_utc": "2026-05-25T15:00:00+00:00",
        "mode": "live_read_only",
        "env": "demo",
        "status": "OK",
        "source_freshness_status": "LIVE_VERIFIED",
        "records_seen_total": 100,
        "records_allowed": 7,
        "records_quarantined": 90,
        "auth_used": True,
        "api_base_url": "https://external-api.demo.kalshi.co/trade-api/v2",
        "dry_run": True,
        "seek_allowed": True,
        "allowed_found": True,
        "pages_scanned": 3,
        # These keys MUST be scrubbed.
        "api_key_id": "leak-this-id-and-the-test-fails",
        "Authorization": "Bearer SECRET",
        "KALSHI-ACCESS-KEY": "SECRET",
    }
    target = append_kalshi_source_health_history(summary, base_path=tmp_path)
    assert target.exists()
    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    obj = json.loads(lines[0])
    # Safety stamps present.
    assert obj["advisory_only"] is True
    assert obj["broker_api_called"] is False
    assert obj["ai_execution_count"] == 0
    # Auth material scrubbed.
    blob = json.dumps(obj)
    for forbidden in (
        "leak-this-id-and-the-test-fails",
        "Bearer SECRET",
        "KALSHI-ACCESS-KEY",
    ):
        assert forbidden not in blob
    # Append again — should keep growing.
    append_kalshi_source_health_history(summary, base_path=tmp_path)
    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


def test_history_ledger_rotates_when_max_lines_exceeded(tmp_path: Path):
    base_summary = {
        "completed_at_utc": "2026-05-25T15:00:00+00:00",
        "mode": "live_read_only",
        "env": "demo",
        "status": "OK",
    }
    for _ in range(DEFAULT_KALSHI_HEALTH_HISTORY_MAX_LINES + 10):
        append_kalshi_source_health_history(base_summary, base_path=tmp_path)
    target = tmp_path / "kalshi_source_health_history.jsonl"
    lines = [ln for ln in target.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == DEFAULT_KALSHI_HEALTH_HISTORY_MAX_LINES


def test_quarantine_rotation_writes_summary_when_over_cap(tmp_path: Path):
    target = tmp_path / "kalshi_quarantine.jsonl"
    target.write_bytes(b"x" * 2048)
    info = rotate_kalshi_quarantine(target, max_bytes=1024)
    assert info["rotated"] is True
    assert (tmp_path / "kalshi_quarantine.jsonl.1").exists()
    assert target.exists() and target.read_text(encoding="utf-8") == ""
    summary = json.loads(
        target.with_suffix(target.suffix + ".rotation.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["advisory_only"] is True
    assert summary["broker_api_called"] is False


def test_quarantine_rotation_no_op_when_under_cap(tmp_path: Path):
    target = tmp_path / "kalshi_quarantine.jsonl"
    target.write_text("one\n", encoding="utf-8")
    info = rotate_kalshi_quarantine(target, max_bytes=1024 * 1024)
    assert info["rotated"] is False
    assert (tmp_path / "kalshi_quarantine.jsonl").read_text(encoding="utf-8") == "one\n"


def test_write_kalshi_source_health_atomic_and_appends_history(tmp_path: Path):
    health = tmp_path / "kalshi_source_health.json"
    quarantine = tmp_path / "kalshi_quarantine.jsonl"
    summary = write_kalshi_source_health(
        attempted_at_utc="2026-05-25T15:00:00+00:00",
        completed_at_utc="2026-05-25T15:00:01+00:00",
        status="OK",
        records_seen_total=0,
        accepted=[],
        quarantined=[],
        events_persisted=0,
        last_successful_fetch_at_utc="2026-05-25T15:00:01+00:00",
        health_path=health,
        quarantine_path=quarantine,
    )
    # No tmp leftover, valid JSON.
    assert health.exists()
    assert not health.with_suffix(health.suffix + ".tmp").exists()
    assert summary["advisory_only"] is True
    # History ledger appended next to the source-health file.
    ledger = tmp_path / "kalshi_source_health_history.jsonl"
    assert ledger.exists()
    obj = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    assert obj["status"] == "OK"
    assert obj["broker_api_called"] is False


def test_runtime_secret_scanner_against_source_health(tmp_path: Path):
    health = tmp_path / "kalshi_source_health.json"
    quarantine = tmp_path / "kalshi_quarantine.jsonl"
    write_kalshi_source_health(
        attempted_at_utc="2026-05-25T15:00:00+00:00",
        completed_at_utc="2026-05-25T15:00:01+00:00",
        status="OK",
        records_seen_total=0,
        accepted=[],
        quarantined=[],
        events_persisted=0,
        last_successful_fetch_at_utc="2026-05-25T15:00:01+00:00",
        health_path=health,
        quarantine_path=quarantine,
    )
    needles = [
        "KALSHI-ACCESS-KEY",
        "KALSHI-ACCESS-SIGNATURE",
        "KALSHI-ACCESS-TIMESTAMP",
        "BEGIN PRIVATE KEY",
        "BEGIN RSA PRIVATE KEY",
        "Authorization",
        "private_key_path",
    ]
    blob = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in tmp_path.rglob("*")
        if p.is_file() and p.suffix in {".json", ".jsonl", ".log", ".txt"}
    )
    for needle in needles:
        assert needle not in blob, f"runtime leakage: {needle!r}"
