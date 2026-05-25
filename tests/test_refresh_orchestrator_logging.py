"""
Tests for the orchestrator-level ``source_run_log`` fallback added in
``scripts/refresh_live_signals.py``.

The cockpit/watchdog read ``source_run_log`` to decide
freshness_state.  Before this sprint, an early failure inside the
runner (import error, loader crash, malformed config) could leave
``source_run_log`` empty for a source the orchestrator actually
attempted, so the cockpit chip would show ``never_run`` instead of
``error``/``skipped``/``timeout``.

These tests pin the new contract:

  - every ``_run_one_source`` invocation writes at least one
    ``source_run_log`` row, regardless of inner-runner outcome
  - the orchestrator status taxonomy maps cleanly to log statuses
    (OK / OK_EMPTY / SKIPPED / CONFIG_MISSING / ERROR / TIMEOUT /
    HTTP_ERROR / RATE_LIMITED)
  - a persistence failure inside the fallback never crashes the
    orchestrator
  - no broker/order/execute keys are introduced anywhere
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts import refresh_live_signals as rls


# ---------------------------------------------------------------------------
# Status taxonomy mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "success,skipped,error_message,skipped_reason,runner_status,expected",
    [
        (True, False, "", "", "ok", "OK"),
        (True, False, "", "", "ok_empty", "OK_EMPTY"),
        (True, False, "", "", "ok_filtered", "OK_FILTERED"),
        (False, True, "", "rate_limited", "rate_limited", "RATE_LIMITED"),
        (False, True, "", "timeout: gdelt", "timeout", "TIMEOUT"),
        (False, True, "", "missing_credentials: NEWS_API_KEY", "skipped", "CONFIG_MISSING"),
        (False, True, "", "adapter_planned_not_implemented", "skipped", "PLACEHOLDER"),
        (False, True, "", "auth failed upstream", "http_error", "HTTP_ERROR"),
        (False, False, "ImportError: requests", "", "", "ERROR"),
    ],
)
def test_status_mapping(
    monkeypatch,
    success,
    skipped,
    error_message,
    skipped_reason,
    runner_status,
    expected,
):
    """Each orchestrator outcome produces the documented source_run_log status."""
    captured: list[dict] = []

    def _fake_log(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(
        "scripts.persistence.log_source_run", _fake_log
    )
    rls._safe_log_source_run_attempt(
        source_name="kalshi",
        success=success,
        skipped=skipped,
        error_message=error_message,
        skipped_reason=skipped_reason,
        runner_status=runner_status,
        runner_fetched_count=3,
        timestamp_utc="2026-05-25T17:30:00+00:00",
        duration_seconds=0.5,
    )
    assert len(captured) == 1
    row = captured[0]
    assert row["source_name"] == "kalshi"
    assert row["status"] == expected
    assert row["duration_ms"] == 500
    # Reason / error fields are clamped to 240 chars but otherwise verbatim.
    assert row["skipped_reason"] == skipped_reason
    assert row["error_message"] == error_message


def test_persistence_failure_does_not_raise(monkeypatch):
    """A persistence-layer crash must never propagate into the orchestrator."""

    def _boom(**kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr("scripts.persistence.log_source_run", _boom)
    # Must not raise.
    rls._safe_log_source_run_attempt(
        source_name="kalshi",
        success=False,
        skipped=False,
        error_message="ImportError: requests",
        skipped_reason="",
        runner_status="",
        runner_fetched_count=0,
        timestamp_utc="2026-05-25T17:30:00+00:00",
        duration_seconds=0.1,
    )


# ---------------------------------------------------------------------------
# Integration: _run_one_source writes a row even when the runner raises
# ---------------------------------------------------------------------------


def test_run_one_source_writes_log_row_on_runner_exception(monkeypatch):
    """If the inner phase1 runner raises (e.g. ImportError), the orchestrator
    fallback must still produce a source_run_log row so the cockpit chip
    flips to ``error`` instead of ``never_run``."""
    captured: list[dict] = []

    def _fake_log(**kwargs):
        captured.append(kwargs)

    def _explode(*args, **kwargs):
        raise RuntimeError("simulated runner crash")

    monkeypatch.setattr("scripts.persistence.log_source_run", _fake_log)
    monkeypatch.setattr(rls, "_invoke_phase1_single", _explode)
    monkeypatch.setattr(rls, "_count_rows_for_source", lambda *a, **kw: 0)
    monkeypatch.setattr(
        rls,
        "_safe_record_metadata",
        lambda **kw: None,  # bypass the live_source_refresh_runs INSERT
    )

    entry = rls._run_one_source(
        run_id="test-run",
        source_key="kalshi",
        write_mode=True,
        credential_state={"kalshi": {"configured": True}},
        db_path="runtime/test.db",
    )

    assert entry["success"] is False
    assert entry["skipped"] is False
    # At least one fallback log row must have landed.
    kalshi_rows = [c for c in captured if c["source_name"] == "kalshi"]
    assert kalshi_rows, "orchestrator fallback did not write a source_run_log row"
    # Status taxonomy: orchestrator caught an exception -> ERROR.
    assert any(r["status"] == "ERROR" for r in kalshi_rows)


def test_run_one_source_writes_log_row_on_skipped_runner_result(monkeypatch):
    """A runner that returns status=skipped must still produce a log row."""
    captured: list[dict] = []

    monkeypatch.setattr(
        "scripts.persistence.log_source_run",
        lambda **kwargs: captured.append(kwargs),
    )
    monkeypatch.setattr(rls, "_count_rows_for_source", lambda *a, **kw: 0)
    monkeypatch.setattr(rls, "_safe_record_metadata", lambda **kw: None)
    monkeypatch.setattr(
        rls,
        "_invoke_phase1_single",
        lambda *a, **kw: {
            "status": "timeout",
            "skipped_reason": "gdelt timeout",
            "fetched_count": 0,
        },
    )

    entry = rls._run_one_source(
        run_id="test-run",
        source_key="gdelt",
        write_mode=True,
        credential_state={"gdelt": {"configured": True}},
        db_path="runtime/test.db",
    )
    assert entry["skipped"] is True
    assert any(c["status"] == "TIMEOUT" for c in captured)


# ---------------------------------------------------------------------------
# Safety: no broker / execute / order keys ever appear in the row
# ---------------------------------------------------------------------------


def test_log_row_carries_no_execution_keys(monkeypatch):
    captured: list[dict] = []
    monkeypatch.setattr(
        "scripts.persistence.log_source_run",
        lambda **kwargs: captured.append(kwargs),
    )
    rls._safe_log_source_run_attempt(
        source_name="kalshi",
        success=True,
        skipped=False,
        error_message="",
        skipped_reason="",
        runner_status="ok",
        runner_fetched_count=10,
        timestamp_utc="2026-05-25T17:30:00+00:00",
        duration_seconds=0.4,
    )
    assert captured, "log row not written"
    row = captured[0]
    forbidden = {"order_placed", "broker_order_id", "execute_trade", "broker_url"}
    for k in forbidden:
        assert k not in row, f"forbidden key present in log row: {k}"
