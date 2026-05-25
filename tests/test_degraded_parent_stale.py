"""
Tests for the explicit DEGRADED_PARENT_STALE freshness state and the
Kalshi dependency-critical grading.

Asserts:
  - ``compute_source_freshness`` flips a derived source to
    ``degraded_parent_stale`` when a required parent is not fresh
  - ``score_source`` recognises the new state as stale and overrides
    Kalshi's stale_severity to ``dependency_blocking``
  - the watchdog snapshot loader marks derived rows as stale_active
    when the parent is stale, and emits the new tracked top-level
    summary keys
  - the operator-readable summary CLI prints the explicit
    ``DEGRADED_PARENT_STALE`` line
"""
from __future__ import annotations

import io
import sys
import time
import types
from contextlib import redirect_stdout
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.live_source_registry import (
    DEPENDENCY_CRITICAL_SOURCES,
    DERIVED_SOURCE_PARENTS,
    FRESHNESS_DEGRADED_PARENT_STALE,
    compute_source_freshness,
    get_dependency_critical_info,
)


def _row(name: str, status: str, ts: str) -> dict:
    return {
        "source_name": name,
        "status": status,
        "timestamp_utc": ts,
    }


def _iso_from_epoch(epoch: float) -> str:
    import datetime as _dt

    return (
        _dt.datetime.fromtimestamp(epoch, tz=_dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def test_disagreement_marked_degraded_parent_stale_when_kalshi_stale() -> None:
    now = time.time()
    rows = [
        _row("polymarket", "OK", _iso_from_epoch(now - 600)),  # 10 min ago → fresh
        _row("kalshi", "OK", _iso_from_epoch(now - 48 * 3600)),  # 48h ago → stale
        _row(
            "prediction_market_disagreement",
            "OK",
            _iso_from_epoch(now - 600),  # 10 min ago → fresh, then overridden
        ),
    ]
    out = compute_source_freshness(rows, cadence_hours=6, now_epoch=now)
    assert out["polymarket"]["freshness_state"] == "fresh"
    assert out["kalshi"]["freshness_state"] in {"stale", "overdue"}
    pmd = out["prediction_market_disagreement"]
    assert pmd["freshness_state"] == FRESHNESS_DEGRADED_PARENT_STALE
    assert "kalshi" in pmd.get("degraded_parent_stale_parents", [])
    # Polymarket fresh — not in offending parent list.
    assert "polymarket" not in pmd.get("degraded_parent_stale_parents", [])


def test_disagreement_remains_fresh_when_all_parents_fresh() -> None:
    now = time.time()
    rows = [
        _row("polymarket", "OK", _iso_from_epoch(now - 600)),
        _row("kalshi", "OK", _iso_from_epoch(now - 600)),
        _row("prediction_market_disagreement", "OK", _iso_from_epoch(now - 600)),
    ]
    out = compute_source_freshness(rows, cadence_hours=6, now_epoch=now)
    assert out["polymarket"]["freshness_state"] == "fresh"
    assert out["kalshi"]["freshness_state"] == "fresh"
    assert out["prediction_market_disagreement"]["freshness_state"] == "fresh"


def test_kalshi_dependency_critical_info_known() -> None:
    info = get_dependency_critical_info("kalshi")
    assert info["dependency_critical"] is True
    assert "prediction_market_disagreement" in info["used_by"]
    assert info["stale_severity_when_active"] == "dependency_blocking"


def test_score_source_marks_kalshi_dependency_blocking_when_stale() -> None:
    from scripts.source_health_score import score_source

    out = score_source(
        {
            "source_key": "kalshi",
            "tier": "optional",
            "adapter_status": "implemented",
            "credential_configured": True,
            "freshness_state": "stale",
            "hours_since_last_success": 25.0,
            "dependency_critical": True,
            "used_by_derived": ["prediction_market_disagreement"],
            "last_refresh_success": False,
        }
    )
    assert out["stale_severity"] == "dependency_blocking"
    # Reason list should mention the cascade.
    assert any(
        "dependency_critical" in r and "prediction_market_disagreement" in r
        for r in out["health_reasons"]
    )


def test_score_source_recognises_degraded_parent_stale() -> None:
    from scripts.source_health_score import score_source

    out = score_source(
        {
            "source_key": "prediction_market_disagreement",
            "tier": "optional",
            "adapter_status": "implemented",
            "credential_configured": True,
            "freshness_state": "degraded_parent_stale",
            "hours_since_last_success": 1.0,
            "dependency_critical": False,
            "degraded_parent_stale_parents": ["kalshi"],
        }
    )
    assert out["stale_severity"] in {"soft", "moderate", "loud"}
    assert any("kalshi" in r for r in out["health_reasons"])


def test_watchdog_snapshot_marks_disagreement_stale_active_via_parent(tmp_path: Path, monkeypatch) -> None:
    """When the freshness layer reports degraded_parent_stale the watchdog's
    snapshot loader must treat the derived source as stale_active and emit
    the new top-level tracking keys."""
    import scripts.watchdog_refresh_stale_sources as wd

    monkeypatch.setattr(
        wd,
        "_load_snapshot",
        lambda **_: _build_pmd_parent_stale_snapshot(),
    )
    result = wd.run_watchdog(
        ttl_hours=6,
        max_retries=0,
        backoff_seconds=(1,),
        no_sleep=True,
        summary_path=tmp_path / "summary.json",
        subprocess_runner=lambda cmd: types.SimpleNamespace(returncode=0, stdout="", stderr=""),
        sleep_fn=lambda s: None,
    )
    summary = result.summary
    assert "prediction_market_disagreement" in summary["stale_sources_before"]
    assert summary["kalshi_freshness_before"] == "stale"
    assert (
        summary["prediction_market_disagreement_freshness_before"]
        == FRESHNESS_DEGRADED_PARENT_STALE
    )
    pmd_after_chip = summary["prediction_market_disagreement_freshness_after"]
    assert pmd_after_chip == FRESHNESS_DEGRADED_PARENT_STALE
    assert "kalshi" in summary["dependency_critical_sources"]
    # Per-source status chip (rich dict) carries dependency_critical and used_by.
    k_after = summary["kalshi_status_after"]
    assert k_after["dependency_critical"] is True
    assert "prediction_market_disagreement" in k_after["used_by"]
    assert k_after["stale_severity"] == "dependency_blocking"


def _build_pmd_parent_stale_snapshot():
    """Replicate _stale_snapshot_current_scenario without test imports."""
    from scripts.watchdog_refresh_stale_sources import (
        Snapshot,
        SourceSnapshotEntry,
    )

    return Snapshot(
        generated_at_utc="2026-05-25T10:35:00+00:00",
        entries={
            "polymarket": SourceSnapshotEntry(
                source_key="polymarket",
                tier="core",
                adapter_status="implemented",
                requires_api_key=False,
                credential_configured=True,
                freshness_state="fresh",
                last_success_at="2026-05-25T10:00:00+00:00",
                last_refresh_attempt_at="2026-05-25T10:00:00+00:00",
                last_refresh_success=True,
                last_refresh_skipped=False,
                last_refresh_error="",
                last_refresh_skipped_reason="",
                latest_event_at="2026-05-25T10:00:00+00:00",
                hours_since_last_success=0.5,
                excluded_reason=None,
                is_stale_active=False,
                is_derived=False,
                parent_sources=(),
                dependency_critical=False,
                used_by_derived=(),
                stale_severity="",
                degraded_parent_stale_parents=(),
            ),
            "kalshi": SourceSnapshotEntry(
                source_key="kalshi",
                tier="optional",
                adapter_status="implemented",
                requires_api_key=False,
                credential_configured=True,
                freshness_state="stale",
                last_success_at="2026-05-24T09:00:00+00:00",
                last_refresh_attempt_at="2026-05-25T10:30:00+00:00",
                last_refresh_success=False,
                last_refresh_skipped=False,
                last_refresh_error="upstream 503",
                last_refresh_skipped_reason="",
                latest_event_at="2026-05-24T09:00:00+00:00",
                hours_since_last_success=25.0,
                excluded_reason=None,
                is_stale_active=True,
                is_derived=False,
                parent_sources=(),
                dependency_critical=True,
                used_by_derived=("prediction_market_disagreement",),
                stale_severity="dependency_blocking",
            ),
            "prediction_market_disagreement": SourceSnapshotEntry(
                source_key="prediction_market_disagreement",
                tier="optional",
                adapter_status="implemented",
                requires_api_key=False,
                credential_configured=True,
                freshness_state=FRESHNESS_DEGRADED_PARENT_STALE,
                last_success_at="2026-05-24T09:30:00+00:00",
                last_refresh_attempt_at="2026-05-25T10:30:00+00:00",
                last_refresh_success=False,
                last_refresh_skipped=False,
                last_refresh_error="",
                last_refresh_skipped_reason="",
                latest_event_at="2026-05-24T09:30:00+00:00",
                hours_since_last_success=25.0,
                excluded_reason=None,
                is_stale_active=True,
                is_derived=True,
                parent_sources=("polymarket", "kalshi"),
                dependency_critical=False,
                used_by_derived=(),
                stale_severity="soft",
                degraded_parent_stale_parents=("kalshi",),
            ),
        },
        ttl_hours=6,
    )


def test_source_health_summary_cli_prints_degraded_parent_stale(monkeypatch) -> None:
    """The summary CLI must print the explicit ``DEGRADED_PARENT_STALE`` line
    so the operator sees the cascade in plain text."""
    import scripts.source_health_summary as srv

    def _fake_freshness() -> dict[str, dict]:
        return {
            "polymarket": {
                "freshness_state": "fresh",
                "tier": "core",
                "credential_configured": True,
            },
            "kalshi": {
                "freshness_state": "stale",
                "tier": "optional",
                "credential_configured": True,
            },
            "prediction_market_disagreement": {
                "freshness_state": FRESHNESS_DEGRADED_PARENT_STALE,
                "tier": "optional",
                "credential_configured": True,
                "degraded_parent_stale_parents": ["kalshi"],
            },
        }

    monkeypatch.setattr(srv, "_gather_freshness_snapshot", _fake_freshness)
    monkeypatch.setattr(srv, "_gather_summary_payload", lambda: srv.empty_summary())

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = srv._cli([])
    assert rc == 0
    out = buf.getvalue()
    assert "DEGRADED_PARENT_STALE" in out
    assert "kalshi" in out
    assert "prediction_market_disagreement" in out
