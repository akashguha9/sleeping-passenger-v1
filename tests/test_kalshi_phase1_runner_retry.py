"""Tests for the Kalshi phase-1 refresh runner — retry + classification."""
from __future__ import annotations

from pathlib import Path

import pytest

import scripts.kalshi_phase1_runner as runner_module
from scripts.kalshi_phase1_runner import run_kalshi_phase1


class _FakeLegacyAttempt:
    """Helper that lets a test script a sequence of legacy attempt results.

    We monkeypatch ``_attempt_legacy`` so retries don't hit the network and
    the test can prove the retry predicate fires at the right moments.
    """

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0

    def __call__(self, **kwargs):
        self.calls += 1
        if self._outcomes:
            return self._outcomes.pop(0)
        return self._outcomes[-1] if self._outcomes else {}


def _outcome(
    *,
    records_seen_total=0,
    records_allowed=0,
    records_quarantined=0,
    accepted=None,
    error_present=False,
    error_message="",
    skipped=False,
):
    return {
        "skipped": skipped,
        "skip_reason": "",
        "records_seen_total": records_seen_total,
        "records_allowed": records_allowed,
        "records_quarantined": records_quarantined,
        "accepted": accepted or [],
        "fetched_at": "2026-05-26T20:00:00+00:00",
        "source_freshness_status": "LIVE_VERIFIED",
        "health_path": "",
        "auth_used": False,
        "error_present": error_present,
        "error_message": error_message,
        "http_error": False,
        "timeout_error": False,
    }


def test_retry_on_empty_then_success(monkeypatch):
    """First attempt empty, second attempt accepts -> rows_added=1, retry_count=1."""
    accepted_payload = {
        "event_id": "kalshi_X",
        "title": "Test",
    }
    fake_attempts = _FakeLegacyAttempt(
        [
            _outcome(records_seen_total=0, records_allowed=0, records_quarantined=0),
            _outcome(
                records_seen_total=10,
                records_allowed=1,
                records_quarantined=9,
                accepted=[accepted_payload],
            ),
        ]
    )

    monkeypatch.setattr(runner_module, "_attempt_legacy", fake_attempts)
    monkeypatch.setattr(runner_module, "_attempt_live", lambda **kw: _outcome())

    sleeps: list[float] = []
    out = run_kalshi_phase1(
        dry_run=False,
        max_attempts=3,
        sleep_fn=lambda s: sleeps.append(s),
        force_live=False,
        db_path=None,  # default test isolation via conftest
    )
    assert fake_attempts.calls == 2
    assert out["records_allowed"] == 1
    assert out["retry_count"] == 1
    # No-op sleep monkeypatched but should still record the backoff.
    assert sleeps  # non-empty
    # First attempt's reason should have been EMPTY_RESPONSE.
    assert out["attempts"][0]["retry_reason"] == "EMPTY_RESPONSE"
    # Final outcome carried at least one accepted; with default conftest
    # DB redirect, rows_added=1.
    assert out["rows_added"] >= 1


def test_retry_exhausted_remains_degraded(monkeypatch):
    """All attempts return filtered=no allowed -> retry exhausted, rows=0."""
    fake = _FakeLegacyAttempt(
        [
            _outcome(records_seen_total=20, records_allowed=0, records_quarantined=20),
            _outcome(records_seen_total=20, records_allowed=0, records_quarantined=20),
        ]
    )
    monkeypatch.setattr(runner_module, "_attempt_legacy", fake)
    monkeypatch.setattr(runner_module, "_attempt_live", lambda **kw: _outcome())

    out = run_kalshi_phase1(
        dry_run=False,
        max_attempts=2,
        sleep_fn=lambda s: None,
        force_live=False,
    )
    assert fake.calls == 2
    assert out["rows_added"] == 0
    assert out["rows_refreshed"] == 0
    assert out["records_seen_total"] == 20
    assert out["records_allowed"] == 0
    assert out["retry_count"] == 1
    assert out["final_retry_reason"] == "FILTERED_NO_ALLOWED"


def test_no_retry_when_first_attempt_succeeds(monkeypatch):
    """First attempt accepted+persisted -> retry_count=0."""
    accepted_payload = {"event_id": "kalshi_Y", "title": "T"}
    fake = _FakeLegacyAttempt(
        [
            _outcome(
                records_seen_total=5,
                records_allowed=1,
                records_quarantined=4,
                accepted=[accepted_payload],
            ),
            # Second outcome should never be consumed.
            _outcome(records_seen_total=0, records_allowed=0, records_quarantined=0),
        ]
    )
    monkeypatch.setattr(runner_module, "_attempt_legacy", fake)
    monkeypatch.setattr(runner_module, "_attempt_live", lambda **kw: _outcome())

    out = run_kalshi_phase1(
        dry_run=False,
        max_attempts=3,
        sleep_fn=lambda s: None,
        force_live=False,
    )
    assert fake.calls == 1
    assert out["retry_count"] == 0
    assert out["records_allowed"] == 1
