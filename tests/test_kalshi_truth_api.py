"""API surface for the Kalshi split-semantic truth."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.api.routers.source_health_router import (
    _build_kalshi_truth_response,
)


def test_kalshi_truth_api_exposes_split_state(tmp_path, monkeypatch):
    """The API must surface api_health_status + canonical_signal_status separately."""
    # Re-root the artifact path via monkeypatch on the resolver inside
    # the helper.  Since the helper resolves repo_root from __file__, we
    # instead write to the canonical runtime/release path under tmp via
    # symlink-ish redirection by monkeypatching Path.exists logic.  The
    # cleaner approach is to monkeypatch the count_fresh_signal_events_by_source
    # AND the load_health_artifact import to point at our temp.
    import scripts.api.routers.source_health_router as router

    health_path = tmp_path / "kalshi_source_health.json"
    health_path.write_text(
        json.dumps(
            {
                "source_freshness_status": "LIVE_VERIFIED",
                "completed_at_utc": "2026-05-26T20:00:00+00:00",
                "records_seen_total": 20,
                "records_allowed": 1,
                "records_quarantined": 19,
            }
        ),
        encoding="utf-8",
    )

    from scripts import kalshi_semantic_freshness as sf
    original_load = sf.load_health_artifact

    def _fake_load(_path):
        return original_load(health_path)

    monkeypatch.setattr(sf, "load_health_artifact", _fake_load)
    # Also patch persistence.count_fresh_signal_events_by_source to return
    # canonical zero so we exercise the ZERO_FRESH_ROWS branch.
    import scripts.persistence as persistence

    monkeypatch.setattr(
        persistence,
        "count_fresh_signal_events_by_source",
        lambda **_kw: {
            "fresh_count": 0,
            "latest_fetched_at": None,
            "latest_age_hours": None,
            "total_count": 0,
            "ttl_hours": 6.0,
        },
    )

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
