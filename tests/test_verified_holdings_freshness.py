"""verified_current_holdings.json freshness — proof_loop_hardening_sprint, Phase 13."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.verified_holdings_freshness import (
    STATUS_AGING,
    STATUS_FRESH,
    STATUS_MISSING,
    STATUS_STALE,
    STATUS_UNREADABLE,
    compute_freshness,
    is_safe_for_moltbook_writes,
)


pytestmark = [
    pytest.mark.reliability,
    pytest.mark.moltbook,
]


def _write_holdings(tmp_path: Path, run_date: str) -> Path:
    payload = {
        "run_date": run_date,
        "positions": [],
    }
    path = tmp_path / "verified_current_holdings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_missing_file_returns_missing_status(tmp_path):
    path = tmp_path / "does_not_exist.json"
    state = compute_freshness(path=path)
    assert state.status == STATUS_MISSING
    assert is_safe_for_moltbook_writes(state) is False


def test_unreadable_file_returns_unreadable(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("not json {", encoding="utf-8")
    state = compute_freshness(path=path)
    assert state.status == STATUS_UNREADABLE
    assert is_safe_for_moltbook_writes(state) is False


def test_fresh_when_run_date_is_today(tmp_path):
    today = datetime.now(timezone.utc).date().isoformat()
    path = _write_holdings(tmp_path, today)
    state = compute_freshness(path=path)
    assert state.status == STATUS_FRESH
    assert is_safe_for_moltbook_writes(state) is True


def test_aging_when_run_date_is_two_days_ago(tmp_path):
    two_days_ago = (
        datetime.now(timezone.utc) - timedelta(days=2)
    ).date().isoformat()
    path = _write_holdings(tmp_path, two_days_ago)
    state = compute_freshness(path=path)
    assert state.status == STATUS_AGING
    assert is_safe_for_moltbook_writes(state) is True


def test_stale_when_run_date_is_five_days_ago(tmp_path):
    five_days_ago = (
        datetime.now(timezone.utc) - timedelta(days=5)
    ).date().isoformat()
    path = _write_holdings(tmp_path, five_days_ago)
    state = compute_freshness(path=path)
    assert state.status == STATUS_STALE
    assert is_safe_for_moltbook_writes(state) is False


def test_missing_run_date_marks_unreadable(tmp_path):
    path = tmp_path / "no_run_date.json"
    path.write_text(json.dumps({"positions": []}), encoding="utf-8")
    state = compute_freshness(path=path)
    assert state.status == STATUS_UNREADABLE


def test_safety_stamps_present_in_payload(tmp_path):
    today = datetime.now(timezone.utc).date().isoformat()
    path = _write_holdings(tmp_path, today)
    state = compute_freshness(path=path)
    payload = state.to_dict()
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    assert payload["execution_gate"] == "LOCKED"
    assert payload["broker_api_called"] is False
    assert payload["ai_execution_count"] == 0
