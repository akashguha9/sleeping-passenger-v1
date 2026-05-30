"""Tests for source-health maturity classification + scoring (WORKSTREAM C)."""
from __future__ import annotations

import pytest

from scripts import source_health_maturity as shm


def _fresh_live(**over):
    base = {
        "source_name": "alpha",
        "source_type": "PRICE",
        "configured": True,
        "enabled": True,
        "freshness_age_hours": 1.0,
        "freshness_ttl_hours": 24.0,
        "rows_seen": 10,
        "rows_accepted": 10,
        "canonical_rows_written": 10,
    }
    base.update(over)
    return base


def test_source_health_score_math() -> None:
    """0.35*ce + 0.25*freshness + 0.20*acceptance + 0.20*canonical_write."""
    out = shm.compute_source_health_score(
        _fresh_live(
            freshness_age_hours=12.0,  # ratio 0.5 -> freshness_score 0.5
            freshness_ttl_hours=24.0,
            rows_seen=10,
            rows_accepted=8,  # acceptance 0.8
            canonical_rows_written=4,  # 4/8 = 0.5
        )
    )
    expected = 0.35 * 1.0 + 0.25 * 0.5 + 0.20 * 0.8 + 0.20 * 0.5
    assert out["configured_enabled_score"] == 1.0
    assert out["freshness_score"] == pytest.approx(0.5)
    assert out["acceptance_score"] == pytest.approx(0.8)
    assert out["canonical_write_score"] == pytest.approx(0.5)
    assert out["source_health_score"] == pytest.approx(expected)


def test_source_health_mock_not_live_verified() -> None:
    out = shm.compute_source_health_score(_fresh_live(is_mock=True))
    assert out["maturity_label"] == shm.MOCK_ONLY
    assert out["maturity_label"] != shm.LIVE_VERIFIED
    stub = shm.compute_source_health_score(_fresh_live(is_stub=True))
    assert stub["maturity_label"] == shm.STUB_SAFE
    assert stub["maturity_label"] != shm.LIVE_VERIFIED


def test_source_health_stale_classification() -> None:
    out = shm.compute_source_health_score(
        _fresh_live(freshness_age_hours=50.0, freshness_ttl_hours=24.0)
    )
    assert out["maturity_label"] == shm.STALE
    assert out["freshness_ratio"] > 1.0
    assert out["freshness_score"] == 0.0


def test_source_health_disabled_has_no_decision_impact() -> None:
    out = shm.compute_source_health_score(
        {
            "source_name": "off",
            "configured": False,
            "enabled": False,
            "disabled_intentionally": True,
        }
    )
    assert out["maturity_label"] == shm.DISABLED
    assert out["decision_impact"] == shm.IMPACT_NONE
    assert out["score_informational_only"] is True


def test_source_health_summary_carries_safety_stamps() -> None:
    summary = shm.build_source_health_maturity_summary(
        [_fresh_live(), _fresh_live(source_name="beta", is_mock=True)]
    )
    assert summary["advisory_status"] == "ADVISORY_ONLY"
    assert summary["execution_gate"] == "LOCKED"
    assert summary["broker_api_called"] is False
    assert summary["ai_execution_count"] == 0
    assert summary["real_money_sizing_impact"] == "PROHIBITED"
    assert summary["source_count"] == 2
    assert summary["live_verified_count"] == 1  # mock is not live-verified
    # Each source carries stamps too.
    for s in summary["sources"]:
        assert s["broker_api_called"] is False
        assert s["real_money_sizing_impact"] == "PROHIBITED"


def test_live_verified_only_for_fresh_canonical_non_mock() -> None:
    out = shm.compute_source_health_score(_fresh_live())
    assert out["maturity_label"] == shm.LIVE_VERIFIED
    assert out["decision_impact"] == shm.IMPACT_ADVISORY_CONTEXT_ONLY
