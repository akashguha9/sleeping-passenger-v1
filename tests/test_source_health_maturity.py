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


# --- Workstream D — guarded verify_live_source_readiness --------------------

def _verifiable(**over):
    """A source_result that satisfies every LIVE_VERIFIED condition."""
    base = {
        "source_name": "alpha_readonly",
        "configured": True,
        "enabled": True,
        "mock_mode": False,
        "rows_seen": 12,
        "rows_accepted": 10,
        "rows_filtered": 2,
        "canonical_rows_written": 10,
        "last_fresh_signal_at_utc": "2026-05-30T11:00:00Z",
        "freshness_age_hours": 1.0,
        "freshness_ttl_hours": 24.0,
        "advisory_only": True,
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
        "decision_impact": "ADVISORY_CONTEXT_ONLY",
        "secrets_redacted": True,
        "no_execution_language": True,
        "provider_error": None,
    }
    base.update(over)
    return base


def test_fresh_readonly_source_can_live_verify() -> None:
    out = shm.verify_live_source_readiness(_verifiable())
    assert out["live_verified"] is True
    assert out["status"] == shm.LIVE_VERIFIED
    assert out["live_verified_blockers"] == []


def test_mock_source_cannot_live_verify() -> None:
    out = shm.verify_live_source_readiness(_verifiable(mock_mode=True))
    assert out["live_verified"] is False
    assert out["status"] == shm.MOCK_ONLY
    assert "mock_mode" in out["live_verified_blockers"]


def test_stale_source_cannot_live_verify() -> None:
    out = shm.verify_live_source_readiness(
        _verifiable(freshness_age_hours=48.0, freshness_ttl_hours=24.0)
    )
    assert out["live_verified"] is False
    assert out["status"] == shm.STALE
    assert "stale_or_unknown_freshness" in out["live_verified_blockers"]


def test_no_canonical_rows_cannot_live_verify() -> None:
    out = shm.verify_live_source_readiness(_verifiable(canonical_rows_written=0))
    assert out["live_verified"] is False
    assert out["status"] == shm.NO_FRESH_ROWS
    assert "no_canonical_rows_written" in out["live_verified_blockers"]


def test_missing_safety_stamps_cannot_live_verify() -> None:
    out = shm.verify_live_source_readiness(
        _verifiable(
            advisory_only=None,
            execution_gate=None,
            secrets_redacted=None,
            no_execution_language=None,
        )
    )
    assert out["live_verified"] is False
    assert out["status"] != shm.LIVE_VERIFIED
    for b in (
        "advisory_only_not_true",
        "execution_gate_not_locked",
        "secrets_not_redacted",
        "execution_language_not_cleared",
    ):
        assert b in out["live_verified_blockers"]


def test_live_verified_still_locked() -> None:
    out = shm.verify_live_source_readiness(_verifiable())
    assert out["live_verified"] is True
    assert out["execution_gate"] == "LOCKED"
    assert out["broker_api_called"] is False
    assert out["ai_execution_count"] == 0
    assert out["human_execution_required"] is True


def test_live_verified_no_real_money_sizing() -> None:
    out = shm.verify_live_source_readiness(_verifiable())
    assert out["real_money_sizing_impact"] == "PROHIBITED"
    assert out["real_money_weight_allowed"] is False


def test_no_mock_live_claims_after_continuation() -> None:
    # Every non-clean variant must refuse the LIVE_VERIFIED verdict.
    variants = [
        _verifiable(mock_mode=True),
        _verifiable(is_stub=True),
        _verifiable(configured=False),
        _verifiable(enabled=False),
        _verifiable(rows_accepted=0, rows_seen=5, rows_filtered=5),
        _verifiable(canonical_rows_written=0),
        _verifiable(last_fresh_signal_at_utc=None, freshness_age_hours=None),
        _verifiable(provider_error="HTTP_500"),
        _verifiable(broker_api_called=True),
        _verifiable(ai_execution_count=1),
    ]
    for v in variants:
        out = shm.verify_live_source_readiness(v)
        assert out["live_verified"] is False
        assert out["status"] != shm.LIVE_VERIFIED
        assert out["execution_gate"] == "LOCKED"
