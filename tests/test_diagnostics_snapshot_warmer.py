"""Kanté Task 1 — background diagnostics snapshot warmer.

Proves the warmer turns a cache miss from a synchronous cliff into a
pre-warmed read, while staying advisory-only and honest about failure:

* ``--once`` / ``run_once`` refreshes the derived cache.
* ``--status`` / ``status_report`` reads metadata only — it never recomputes.
* ``--loop`` rejects an interval below 60s unless ``--allow-fast-local-test``.
* a refresh that *raises* is reported as DEGRADED, never fake-clean.
* the cache stays ``derived_non_canonical`` with ``canonical_truth_source=sqlite``.
* every payload carries the advisory safety banner.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts import diagnostics_snapshot_warmer as warmer
from scripts import diagnostics_snapshot_cache as cache


def test_once_refreshes_cache_and_marks_non_canonical() -> None:
    result = warmer.warm_once()
    assert result["status"] == warmer.WARM_OK
    assert result["cache_role"] == "derived_non_canonical"
    assert result["canonical_truth_source"] == "sqlite"
    # Banner present.
    assert result["ADVISORY_ONLY"] is True
    assert result["HUMAN_EXECUTION_REQUIRED"] is True
    assert result["NO_BROKER_ACTION_PERFORMED"] is True
    # A real snapshot now exists on disk.
    assert cache.read_snapshot() is not None


def test_status_does_not_recompute(monkeypatch: pytest.MonkeyPatch) -> None:
    # Warm once so a snapshot exists.
    warmer.run_once()
    # If status recomputed, it would call cache.refresh — make that explode.
    def _boom(*a, **k):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("status_report must NOT recompute the snapshot")
    monkeypatch.setattr(cache, "refresh", _boom)
    report = warmer.status_report()
    assert report["report"] == "diagnostics_snapshot_warmer_status"
    assert report["cache_present"] is True
    assert report["cache_role"] == "derived_non_canonical"
    assert report["canonical_truth_source"] == "sqlite"


def test_loop_rejects_low_interval_by_default() -> None:
    with pytest.raises(ValueError):
        warmer.run_loop(5, max_iterations=1)


def test_loop_allows_low_interval_with_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    status = warmer.run_loop(
        1, allow_fast_local_test=True, max_iterations=2,
        sleep=lambda s: sleeps.append(s),
    )
    assert status["warm_refresh_attempts"] == 2
    # max_iterations stops before the final sleep, so at most one sleep.
    assert all(s == 1 for s in sleeps)


def test_failed_refresh_is_degraded_not_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    def _explode(**kwargs):  # noqa: ANN003
        raise RuntimeError("synthetic refresh failure")
    result = warmer.warm_once(refresh=_explode)
    assert result["status"] == warmer.WARM_DEGRADED
    assert result["status"] != warmer.WARM_OK
    assert result["error_type"] == "RuntimeError"
    assert "recovery_command" in result
    # Still advisory-only and non-canonical even on failure.
    assert result["cache_role"] == "derived_non_canonical"
    assert result["NO_BROKER_ACTION_PERFORMED"] is True


def test_run_once_records_degraded_status(monkeypatch: pytest.MonkeyPatch) -> None:
    def _explode(**kwargs):  # noqa: ANN003
        raise RuntimeError("boom")
    monkeypatch.setattr(cache, "refresh", _explode)
    status = warmer.run_once()
    assert status["warm_refresh_successes"] == 0
    assert status["warm_refresh_attempts"] == 1
    assert status["last_result"]["status"] == warmer.WARM_DEGRADED


def test_warmer_health_score_formula() -> None:
    # All success, fresh cache (age 0 → staleness risk 1), visibility 1.
    h = warmer.warmer_health_score(
        successes=4, attempts=4, cache_age_seconds=0.0,
        cache_ttl_seconds=300, degraded_failure_visibility=1)
    assert h["warm_cache_coverage"] == 1.0
    assert h["cache_staleness_risk"] == 1.0
    assert h["warmer_health_score"] == 10.0
    # Half coverage, fully stale cache (age >= ttl → risk 0).
    h2 = warmer.warmer_health_score(
        successes=1, attempts=2, cache_age_seconds=600.0,
        cache_ttl_seconds=300, degraded_failure_visibility=1)
    assert h2["warm_cache_coverage"] == 0.5
    assert h2["cache_staleness_risk"] == 0.0
    # 10 * (0.5*0.5 + 0.3*0 + 0.2*1) = 10*0.45 = 4.5
    assert h2["warmer_health_score"] == 4.5


def test_cli_once_and_status(capsys: pytest.CaptureFixture[str]) -> None:
    assert warmer.main(["--once"]) == 0
    out = capsys.readouterr().out
    assert "ADVISORY_ONLY" in out
    assert warmer.main(["--status"]) == 0
    out2 = capsys.readouterr().out
    assert "derived_non_canonical" in out2
    assert "sqlite" in out2


def test_cli_loop_low_interval_refused(capsys: pytest.CaptureFixture[str]) -> None:
    rc = warmer.main(["--loop", "--interval-seconds", "5"])
    assert rc == 2
    assert "REFUSED" in capsys.readouterr().out
