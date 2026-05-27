"""API surface for the Kalshi split-semantic truth.

Freshness contract under test:

    api_health_status = LIVE_VERIFIED  iff source_freshness_status == LIVE_VERIFIED
                                         AND 0 <= age_api_hours <= TTL_api (default 6)
                        STALE_HEALTH   iff age_api_hours > TTL_api

To stay deterministic forever, any artifact timestamp that gets compared
against a freshness TTL MUST be generated relative to the current wall
clock (or an explicitly-injected ``now_utc``).  Hardcoded ISO strings
silently become stale once wall-clock time crosses the TTL and turn the
test into a time-bomb.  See [[runtime-db-fake-rows]] and
[[kalshi-truth-split]] for the broader truth-state contract.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from scripts.api.routers.source_health_router import (
    _build_kalshi_truth_response,
)


def _utc_iso(dt: _dt.datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def _write_health_artifact(path: Path, *, completed_at_utc: str) -> None:
    path.write_text(
        json.dumps(
            {
                "source_freshness_status": "LIVE_VERIFIED",
                "completed_at_utc": completed_at_utc,
                "records_seen_total": 20,
                "records_allowed": 1,
                "records_quarantined": 19,
            }
        ),
        encoding="utf-8",
    )


def _patch_health_loader(monkeypatch, health_path: Path) -> None:
    """Redirect the in-router health loader at the fixture path.

    ``_build_kalshi_truth_response`` re-imports ``load_health_artifact``
    from ``scripts.kalshi_semantic_freshness`` on every call (local
    ``from`` inside the function), so patching the attribute on that
    module suffices for both the direct sanitization-load AND the
    nested call from ``build_kalshi_truth``.
    """
    from scripts import kalshi_semantic_freshness as sf

    original_load = sf.load_health_artifact

    def _fake_load(_path):
        return original_load(health_path)

    monkeypatch.setattr(sf, "load_health_artifact", _fake_load)


def _patch_canonical_stats(monkeypatch, *, fresh_count: int = 0) -> None:
    import scripts.persistence as persistence

    monkeypatch.setattr(
        persistence,
        "count_fresh_signal_events_by_source",
        lambda **_kw: {
            "fresh_count": fresh_count,
            "latest_fetched_at": None,
            "latest_age_hours": None,
            "total_count": 0,
            "ttl_hours": 6.0,
        },
    )


def test_kalshi_truth_api_exposes_split_state(tmp_path, monkeypatch):
    """The API must surface api_health_status + canonical_signal_status separately.

    The artifact timestamp is generated relative to ``datetime.now(UTC)``
    so the assertion stays valid regardless of when the test runs.
    """
    now_utc = _dt.datetime.now(_dt.timezone.utc)
    fresh_completed_at = _utc_iso(now_utc - _dt.timedelta(minutes=1))

    health_path = tmp_path / "kalshi_source_health.json"
    _write_health_artifact(health_path, completed_at_utc=fresh_completed_at)

    _patch_health_loader(monkeypatch, health_path)
    _patch_canonical_stats(monkeypatch, fresh_count=0)

    body = _build_kalshi_truth_response()
    assert body["api_health_status"] == "LIVE_VERIFIED"
    assert body["canonical_signal_status"] in {
        "ZERO_FRESH_ROWS",
        "MISSING_CANONICAL",
        "FILTERED",
    }
    # Safety invariants must always be present.
    assert body["advisory_status"] == "ADVISORY_ONLY"
    assert body["broker_api_called"] is False
    assert body["execution_gate"] == "LOCKED"
    assert body["can_execute"] is False
    assert body["ai_execution_count"] == 0
    # No secret-looking keys may appear in the body
    for forbidden in (
        "api_key_id",
        "private_key_path",
        "authorization",
        "kalshi-access-key",
        "kalshi-access-signature",
        "kalshi-access-timestamp",
    ):
        assert forbidden not in body


def test_kalshi_truth_api_marks_old_health_artifact_as_stale(tmp_path, monkeypatch):
    """Old Kalshi health artifacts MUST still degrade to STALE_HEALTH.

    Pinned negative test that guards against TTL weakening: any
    completed_at_utc older than the 6h api-health TTL must NOT classify
    as LIVE_VERIFIED.  We deliberately use ``now - 24h`` so this stays
    well past the TTL boundary regardless of clock skew.
    """
    now_utc = _dt.datetime.now(_dt.timezone.utc)
    stale_completed_at = _utc_iso(now_utc - _dt.timedelta(hours=24))

    health_path = tmp_path / "kalshi_source_health.json"
    _write_health_artifact(health_path, completed_at_utc=stale_completed_at)

    _patch_health_loader(monkeypatch, health_path)
    _patch_canonical_stats(monkeypatch, fresh_count=0)

    body = _build_kalshi_truth_response()
    assert body["api_health_status"] == "STALE_HEALTH"
    # Production freshness contract: STALE_HEALTH must keep
    # advisory_only / execution_gate=LOCKED stamps intact and never
    # mark itself semantic-fresh purely from a stale health artifact.
    assert body["semantic_fresh"] is False
    assert body["advisory_status"] == "ADVISORY_ONLY"
    assert body["execution_gate"] == "LOCKED"
    assert body["broker_api_called"] is False
    assert body["can_execute"] is False
