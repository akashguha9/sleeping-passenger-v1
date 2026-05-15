"""Sprint 7D.1 — source-health reliability scoring.

Test the pure helpers (no I/O) that turn freshness + refresh metadata
into a per-source reliability score / label, plus the API surface
augmentation on /live-sources/status.
"""
from __future__ import annotations

from scripts import source_health_score as shs


def _base_entry(**overrides) -> dict:
    base = {
        "source_key": "x",
        "tier": "core",
        "adapter_status": "implemented",
        "freshness_state": "fresh",
        "credential_configured": True,
        "hours_since_last_success": 1.0,
        "refresh_age_hours": 1.0,
        "last_refresh_error": "",
        "last_refresh_skipped": False,
        "last_refresh_skipped_reason": "",
        "last_refresh_success": True,
    }
    base.update(overrides)
    return base


def test_healthy_recent_successful_core_source() -> None:
    r = shs.score_source(_base_entry())
    assert r["health_label"] == shs.LABEL_HEALTHY
    assert r["health_score"] >= 0.85
    assert r["stale_severity"] == "none"
    assert r["config_state"] == "configured"
    assert r["execution_permission"] is False
    assert r["broker_api_called"] is False


def test_stale_core_source_is_degraded_or_unhealthy() -> None:
    r = shs.score_source(
        _base_entry(freshness_state="stale", hours_since_last_success=12.0)
    )
    assert r["health_label"] in {shs.LABEL_DEGRADED, shs.LABEL_WATCH}
    # stale severity for core source must be loud
    assert r["stale_severity"] == "loud"


def test_failed_core_source_is_unhealthy() -> None:
    r = shs.score_source(
        _base_entry(
            freshness_state="failed",
            hours_since_last_success=48.0,
            last_refresh_error="HTTPError: timeout while contacting upstream",
            last_refresh_success=False,
        )
    )
    assert r["health_label"] in {shs.LABEL_DEGRADED, shs.LABEL_UNHEALTHY}
    assert r["stale_severity"] == "loud"
    assert any("error" in reason.lower() for reason in r["health_reasons"])


def test_planned_asia_disclosure_returns_planned_not_scored() -> None:
    """Planned adapter must NOT be scored as a failure."""
    r = shs.score_source(
        _base_entry(
            source_key="asia_disclosure",
            tier="planned",
            adapter_status="planned",
            freshness_state="never_run",
        )
    )
    assert r["health_label"] == shs.LABEL_PLANNED_NOT_SCORED
    assert r["health_score"] is None
    assert r["stale_severity"] == "none"


def test_optional_missing_credential_is_soft_state() -> None:
    """Optional source with no credential is NOT a failure."""
    r = shs.score_source(
        _base_entry(
            tier="optional",
            credential_configured=False,
            freshness_state="skipped",
        )
    )
    assert r["health_label"] == shs.LABEL_OPTIONAL_MISSING_CONFIG
    assert r["config_state"] == "optional_missing"
    assert r["stale_severity"] == "soft"


def test_gdelt_timeout_classified_by_severity() -> None:
    """GDELT-style timeout on a core source -> degraded/unhealthy."""
    r = shs.score_source(
        _base_entry(
            source_key="gdelt",
            tier="core",
            freshness_state="overdue",
            hours_since_last_success=36.0,
            last_refresh_error="HTTPError: 504 gateway timeout",
        )
    )
    assert r["health_label"] in {shs.LABEL_DEGRADED, shs.LABEL_UNHEALTHY}
    assert r["stale_severity"] == "loud"


def test_secondary_stale_is_moderate_not_loud() -> None:
    r = shs.score_source(
        _base_entry(
            tier="secondary",
            freshness_state="stale",
            hours_since_last_success=20.0,
        )
    )
    assert r["stale_severity"] == "moderate"
    # Score should not collapse to unhealthy purely for being secondary-stale.
    assert r["health_score"] is not None and r["health_score"] >= 0.40


def test_aggregate_picks_worst_core_label() -> None:
    per_source = {
        "a": shs.score_source(_base_entry(source_key="a", tier="core")),
        "b": shs.score_source(
            _base_entry(
                source_key="b",
                tier="core",
                freshness_state="overdue",
                hours_since_last_success=72.0,
            )
        ),
        "c": shs.score_source(
            _base_entry(
                source_key="c",
                tier="planned",
                adapter_status="planned",
                freshness_state="never_run",
            )
        ),
    }
    summary = shs.aggregate_health(per_source)
    assert summary["scored_count"] == 2
    assert summary["planned_count"] == 1
    assert summary["core_health_label"] in {
        shs.LABEL_DEGRADED, shs.LABEL_UNHEALTHY, shs.LABEL_WATCH
    }


def test_safety_stamps_present_on_every_scored_entry() -> None:
    """No matter the label, advisory stamps must be carried through."""
    for tier in ("core", "secondary", "optional", "planned"):
        adapter = "planned" if tier == "planned" else "implemented"
        r = shs.score_source(
            _base_entry(tier=tier, adapter_status=adapter, freshness_state="fresh")
        )
        assert r["advisory_status"] == "ADVISORY_ONLY"
        assert r["execution_gate"] == "LOCKED"
        assert r["broker_api_called"] is False
        assert r["execution_permission"] is False
        assert r["can_execute"] is False
